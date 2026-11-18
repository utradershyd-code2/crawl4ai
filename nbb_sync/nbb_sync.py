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

import os as _os
_os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")  # hide crawl4ai's advert banner

import asyncio
import csv
import json
import re
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
# The panel's login cookie only lasts while a browser window stays open, so login
# saves the cookies here and every sync puts them back. Keep this file private.
COOKIES_FILE = PROFILE_DIR / "panel_cookies.json"

PANEL = "https://partner.nationalbroadband.pk"
LOGIN_PATH = "/site/login"
# One request returns every customer (the panel has ~157, so 2000 leaves room).
# The panel accepts at most 500 per page (bigger numbers fall back to 25), so pages are
# also followed in case you ever have more than 500 customers.
CUSTOMERS_URL = PANEL + "/customer/customers?CustomerSearch%5BperPage%5D=500&page={page}"
# Present only on pages you see when logged in ("Available Balance = ...").
LOGGED_IN_MARK = 'label[for="available_credit_limit"]'
# The panel shows a short browser check (a script page) before real pages; wait until
# either a logged-in page or the login form has appeared.
PAGE_READY = ("js:() => !!document.querySelector('label[for=\"available_credit_limit\"]')"
              " || !!document.querySelector('input[type=\"password\"]')")
# Report pages have no balance line: ready when the report table or summary is there.
REPORT_READY = ("js:() => !!document.querySelector('table, .summary, .empty')"
                " || !!document.querySelector('input[type=\"password\"]')")

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

# Real Time Billing Report: one row per recharge. ISP Desk turns these into
# recharge invoices and deducts each recharge's real cost from the panel wallet.
# The panel shows 10 rows per page, so pages are read one by one.
REPORT_URL = (PANEL + "/report/view?ispRates=0&dateRange=&report_type=5&partner_id=20575"
              "&subdealerRates=0&allowsubdealer=0&billing_cycle=&billing_mode=1"
              "&merged_checkbox_checked=false&subdealer_rates_checkbox_checked=false"
              "&package_id=&pkg_id=&per-page=10&page={page}")
MAX_REPORT_PAGES = 50


def load_env(path: Path = HERE / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (no extra package needed)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def item_total(html: str) -> int:
    """'Showing 1-25 of 157 items.' -> 157 (0 if not shown)."""
    summary = BeautifulSoup(html, "lxml").select_one(".summary")
    nums = re.findall(r"\d+", summary.get_text().replace(",", "")) if summary else []
    return int(nums[-1]) if nums else 0


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


def parse_balance(html: str) -> str:
    """'Available Balance = 869.45' shown at the top of every panel page (ISP Desk doubles it)."""
    soup = BeautifulSoup(html, "lxml")
    label = soup.find("label", attrs={"for": "available_credit_limit"})
    value = label.find("b").get_text(strip=True) if label and label.find("b") else ""
    return value.replace(",", "")


def parse_report(html: str) -> tuple[list[dict], int]:
    """Rows of the Real Time Billing Report page, plus the report's total item count (0 if unknown)."""
    soup = BeautifulSoup(html, "lxml")
    total = 0
    summary = soup.select_one(".summary")
    if summary:
        nums = [int(n) for n in re.findall(r"\d+", summary.get_text().replace(",", ""))]
        total = nums[-1] if nums else 0
    for t in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in t.select("thead th")]
        if "Customer ID" in heads and "Last Activation Date" in heads:
            rows = []
            for tr in t.select("tbody tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) < len(heads):
                    continue
                row = {h: v for h, v in zip(heads, cells) if h and h != "#"}
                if row.get("Customer ID"):
                    rows.append(row)
            return rows, total
    return [], total


def saved_cookies() -> list[dict]:
    try:
        return json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def browser(headless: bool) -> AsyncWebCrawler:
    PROFILE_DIR.mkdir(exist_ok=True)
    return AsyncWebCrawler(
        config=BrowserConfig(
            headless=headless,
            use_persistent_context=True,
            user_data_dir=str(PROFILE_DIR),
            cookies=saved_cookies(),
            verbose=False,
        )
    )


async def login() -> None:
    """Opens a normal browser window on the panel; you log in yourself. Waits until a
    logged-in page appears (up to 5 minutes), then keeps the session in ./profile."""
    from playwright.async_api import async_playwright

    print("A browser window will open. Log in to the panel yourself")
    print("(password + security question). You have 5 minutes.")
    PROFILE_DIR.mkdir(exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, no_viewport=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(PANEL + "/site/index", wait_until="domcontentloaded", timeout=120_000)
        try:
            await page.wait_for_selector(LOGGED_IN_MARK, timeout=300_000)
        except Exception:
            print("Login was not completed within 5 minutes. Run login.bat again.")
            await ctx.close()
            sys.exit(1)
        await page.wait_for_timeout(2000)  # let the panel finish saving its cookies
        cookies = [c for c in await ctx.cookies() if "nationalbroadband" in c.get("domain", "")
                   or c.get("domain", "").startswith(("127.0.0.1", "localhost"))]
        COOKIES_FILE.write_text(json.dumps(cookies), encoding="utf-8")
        await ctx.close()
    print("Logged in. The session is saved; syncing now works on its own.")


def upload(customers: list[dict], recharges: list[dict] | None = None, balance: str = "") -> None:
    """Send the rows to ISP Desk's /cron/panel-push (same key as CRON_KEY on the server)."""
    key = os.environ.get("CRON_KEY", "").strip()
    if not key:
        print("CRON_KEY not set in .env - skipped upload (files saved locally).")
        return
    url = os.environ.get("SYNC_URL", "").strip() or DEFAULT_SYNC_URL
    stamp = datetime.now().strftime("%d-%m-%Y %H:%M")
    payload = {"rows": customers, "notes": [f"crawl4ai helper, {stamp}"]}
    if recharges:
        payload["recharges"] = recharges
    if balance:
        payload["balance"] = balance
    body = json.dumps(payload).encode("utf-8")
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
          f"{res.get('changed', 0)} changed, {res.get('not_in_panel', 0)} not in panel, "
          f"{res.get('payments_new', 0)} recharge invoices created.")
    for note in res.get("notes") or []:
        print("  -", note)


def save(customers: list[dict], recharges: list[dict] | None = None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    if recharges:
        with open(OUTPUT_DIR / "recharges.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(recharges[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(recharges)
    (OUTPUT_DIR / "customers.json").write_text(
        json.dumps(customers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with open(OUTPUT_DIR / "customers.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(customers)
    print(f"Saved {len(customers)} customers to {OUTPUT_DIR}")


async def read_panel(headless: bool):
    run = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=90_000,
                           wait_for=PAGE_READY, wait_for_timeout=60_000)
    report_run = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=90_000,
                                  wait_for=REPORT_READY, wait_for_timeout=30_000)
    async with browser(headless=headless) as crawler:
        result = await crawler.arun(CUSTOMERS_URL.format(page=1), config=run)
        html = result.html or ""
        final_url = result.redirected_url or result.url or ""
        if LOGIN_PATH in final_url or ('type="password"' in html and "available_credit_limit" not in html):
            return "logged_out", None
        if not result.success or "available_credit_limit" not in html:
            return "failed", result.error_message or "the panel page did not load"
        balance = parse_balance(html)
        customers = parse_customers(html)
        total = item_total(html)
        page = 1
        while total and len(customers) < total and page < 40:
            page += 1
            more = await crawler.arun(CUSTOMERS_URL.format(page=page), config=run)
            try:
                rows = parse_customers(more.html or "")
            except RuntimeError:
                rows = []
            known = {c["Customer ID"] for c in customers}
            rows = [r for r in rows if r["Customer ID"] not in known]
            if not rows:
                break
            customers.extend(rows)
        if total and len(customers) < total:
            return "failed", f"only {len(customers)} of {total} customers could be read; nothing was sent"

        recharges, seen = [], set()
        for page in range(1, MAX_REPORT_PAGES + 1):
            rep = await crawler.arun(REPORT_URL.format(page=page), config=report_run)
            if not rep.success and "available_credit_limit" not in (rep.html or ""):
                print(f"Recharge report page {page} could not be read:", rep.error_message)
                break
            rows, total = parse_report(rep.html or "")
            new = [r for r in rows if tuple(r.items()) not in seen]
            seen.update(tuple(r.items()) for r in new)
            recharges.extend(new)
            if not new or len(rows) < 10 or (total and len(recharges) >= total):
                break
    return "ok", (customers, balance, recharges)


async def sync() -> None:
    status, data = await read_panel(headless=True)
    if status == "failed":
        print("Hidden browser was stopped by the panel's check (" + str(data) + "); retrying in a window...")
        status, data = await read_panel(headless=False)
    if status == "logged_out":
        print("Panel session expired. Double-click login.bat (or run: python nbb_sync.py login)")
        sys.exit(2)
    if status != "ok":
        print("Could not load the panel:", data)
        sys.exit(1)
    customers, balance, recharges = data

    expiring = [c for c in customers if c.get("Status") == "Active"
                and c.get("Remaining Days", "").lstrip("-").isdigit()
                and int(c["Remaining Days"]) <= 5]
    print(f"{len(customers)} customers read, {len(expiring)} active ones expire within 5 days.")
    print(f"{len(recharges)} recharges in the Real Time Billing Report. Panel balance: {balance or 'not found'}.")
    save(customers, recharges)
    upload(customers, recharges, balance)


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
