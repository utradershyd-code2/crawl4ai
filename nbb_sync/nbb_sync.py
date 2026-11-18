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
import urllib.error
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

# Panel columns that are copied, under the panel's own headings (ISP Desk's
# /cron/panel-push recognises these). Columns not listed (Password, CNIC,
# MAC Address, Model, Action ...) are deliberately NOT copied.
COLUMNS = [
    "Status",
    "Full Name",
    "Customer ID",
    "Package Name",
    "Total (Mbps)",
    "Address",
    "Mobile",
    "Activation Date",
    "Expiration Date",
    "Remaining Days",
    "Inactive/Block Reason",
    "Comments",
]
DEFAULT_SYNC_URL = "https://net.universalfarmaco.com.pk/cron/panel-push"


def load_env(path: Path = HERE / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (no extra package needed)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def parse_customers(html: str) -> list[dict]:
    """Turn the panel's Customer List table into a list of dicts keyed by panel heading.

    Dates are left exactly as the panel shows them (day-month-year); ISP Desk reads them.
    """
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
        row = {head: value for head, value in zip(headers, cells) if head in COLUMNS}
        if row.get("Customer ID"):
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
    """Send the rows to ISP Desk's /cron/panel-push (same key as CRON_KEY on the server)."""
    key = os.environ.get("CRON_KEY", "").strip()
    if not key:
        print("CRON_KEY not set in .env - skipped upload (files saved locally).")
        return
    url = os.environ.get("SYNC_URL", "").strip() or DEFAULT_SYNC_URL
    stamp = datetime.now().strftime("%d-%m-%Y %H:%M")
    body = json.dumps({"rows": customers, "notes": [f"crawl4ai helper, {stamp}"]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Push-Key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:300]
        hint = " (CRON_KEY does not match the server)" if ex.code == 403 else ""
        print(f"Upload refused: HTTP {ex.code}{hint} {detail}")
        sys.exit(3)
    if res.get("error"):
        print("ISP Desk reported an error:", res["error"])
        sys.exit(3)
    print(f"ISP Desk: {res.get('rows', 0)} rows, {res.get('new', 0)} new, "
          f"{res.get('changed', 0)} changed, {res.get('not_in_panel', 0)} not in panel.")


def save(customers: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "customers.json").write_text(
        json.dumps(customers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with open(OUTPUT_DIR / "customers.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
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
    expiring = [c for c in customers if c.get("Status") == "Active"
                and c.get("Remaining Days", "").lstrip("-").isdigit()
                and int(c["Remaining Days"]) <= 5]
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
