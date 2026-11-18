"""
National Broadband partner panel -> ISP software sync (runs on your PC).

Why on the PC: the panel (partner.nationalbroadband.pk) does not answer
requests from the hosting server, but it works from a normal PC in Pakistan.

Usage:
    python nbb_sync.py login    # opens a browser window; you log in once yourself
    python nbb_sync.py sync     # reads all customers and saves / uploads them

Login is never automated: you type the password and security answer yourself.
The browser profile in ./profile keeps you logged in until the panel ends
the session; when that happens, `sync` tells you to run `login` again.
"""

import asyncio
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / "profile"
OUTPUT_DIR = HERE / "output"

PANEL = "https://partner.nationalbroadband.pk"
LOGIN_PATH = "/site/login"
# One request returns every customer (the panel has ~157, so 2000 leaves room).
CUSTOMERS_URL = PANEL + "/customer/customers?CustomerSearch[perPage]=2000"

# Panel column -> our field name. Columns not listed (Password, CNIC, MAC,
# Model, Action ...) are deliberately NOT copied.
COLUMNS = {
    "Status": "status",
    "Full Name": "full_name",
    "Customer ID": "login_name",
    "Package Name": "package",
    "Total (Mbps)": "bandwidth_mbps",
    "Address": "address",
    "Mobile": "mobile",
    "Activation Date": "activation_date",
    "Expiration Date": "expiration_date",
    "Remaining Days": "remaining_days",
    "Inactive/Block Reason": "block_reason",
    "Comments": "comments",
}
DATE_FIELDS = ("activation_date", "expiration_date")


def load_env(path: Path = HERE / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (no extra package needed)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def parse_panel_date(text: str) -> str:
    """'06-12-2026 11:59:59' (day-month-year) -> '2026-12-06T11:59:59'. Blank stays blank."""
    text = (text or "").strip()
    for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    return text


def parse_customers(html: str) -> list[dict]:
    """Turn the panel's Customer List table into a list of dicts."""
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in t.select("thead th")]
        if "Customer ID" in heads and "Expiration Date" in heads:
            table = t
            break
    if table is None:
        raise RuntimeError("Customer table not found - the panel layout may have changed.")

    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    customers = []
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < len(headers):  # "No results found." row, etc.
            continue
        row = {}
        for head, value in zip(headers, cells):
            field = COLUMNS.get(head)
            if field:
                row[field] = value
        for f in DATE_FIELDS:
            if f in row:
                row[f] = parse_panel_date(row[f])
        if row.get("login_name"):
            customers.append(row)
    return customers


def browser(headless: bool) -> AsyncWebCrawler:
    PROFILE_DIR.mkdir(exist_ok=True)
    return AsyncWebCrawler(
        config=BrowserConfig(
            headless=headless,
            use_persistent_context=True,
            user_data_dir=str(PROFILE_DIR),
            verbose=False,
        )
    )


async def login() -> None:
    print("A browser window will open. Log in to the panel yourself")
    print("(password + security question). You have 5 minutes.")
    async with browser(headless=False) as crawler:
        result = await crawler.arun(
            PANEL + LOGIN_PATH,
            config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                wait_for=f"js:() => !location.pathname.startsWith('{LOGIN_PATH}')",
                page_timeout=300_000,
            ),
        )
    if result.success:
        print("Logged in. The session is saved; you can now run: python nbb_sync.py sync")
    else:
        print("Login was not completed:", result.error_message)
        sys.exit(1)


def upload(customers: list[dict]) -> None:
    url = os.environ.get("SYNC_URL", "").strip()
    if not url:
        print("SYNC_URL not set in .env - skipped upload (files saved locally).")
        return
    body = json.dumps(
        {"synced_at": datetime.now().isoformat(timespec="seconds"), "customers": customers}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ.get("SYNC_TOKEN", ""),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(f"Uploaded {len(customers)} customers -> {url} (HTTP {resp.status})")


def save(customers: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "customers.json").write_text(
        json.dumps(customers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with open(OUTPUT_DIR / "customers.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS.values()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(customers)
    print(f"Saved {len(customers)} customers to {OUTPUT_DIR}")


async def sync() -> None:
    async with browser(headless=True) as crawler:
        result = await crawler.arun(
            CUSTOMERS_URL,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=60_000),
        )
    final_url = result.redirected_url or result.url or ""
    if LOGIN_PATH in final_url:
        print("Panel session expired. Run:  python nbb_sync.py login")
        sys.exit(2)
    if not result.success:
        print("Could not load the panel:", result.error_message)
        sys.exit(1)

    customers = parse_customers(result.html)
    expiring = [c for c in customers if c.get("status") == "Active"
                and c.get("remaining_days", "").lstrip("-").isdigit()
                and int(c["remaining_days"]) <= 5]
    print(f"{len(customers)} customers read, {len(expiring)} active ones expire within 5 days.")
    save(customers)
    upload(customers)


def main() -> None:
    load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "login":
        asyncio.run(login())
    elif cmd == "sync":
        asyncio.run(sync())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
