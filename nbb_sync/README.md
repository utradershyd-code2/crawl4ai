# National Broadband panel sync

Reads your customer list from `partner.nationalbroadband.pk` **on your own PC**
(the panel doesn't answer your hosting server), saves it as
`output/customers.csv` / `customers.json`, and sends it to ISP Desk's
`/cron/panel-push` on net.universalfarmaco.com.pk, which adds new customers and
updates packages, expiry dates and status.

## What it copies
Status, name, customer ID, package, bandwidth, address, mobile, activation date,
expiration date, remaining days, block reason, comments.

It does **not** copy passwords, CNIC numbers or MAC addresses.

## One-time setup (Windows)
1. Install Python 3.11 from python.org (tick "Add Python to PATH").
2. Open Command Prompt in this folder and run:
   ```
   pip install crawl4ai
   crawl4ai-setup
   ```
3. Copy `.env.example` to `.env` and set `CRON_KEY` to the same long secret as
   `CRON_KEY` in ISP Desk on the server (cPanel > Setup Python App > environment
   variables; restart the app after adding it). Leave it empty to only save files.
4. Log in once:
   ```
   python nbb_sync.py login
   ```
   A browser opens: type your password and security answer yourself.

## Every sync
```
python nbb_sync.py sync
```
Or double-click `run_sync.bat`. Results land in `output/`.

It prints what ISP Desk did, e.g. `ISP Desk: 157 rows, 0 new, 3 changed`.

* **"Panel session expired"**: run `python nbb_sync.py login` again.
* **"Upload refused: HTTP 403"**: `CRON_KEY` in `.env` doesn't match the server.

## Run it automatically
Task Scheduler → Create Basic Task → trigger **"When I log on"** → action: start
`run_sync.bat`. Add a second trigger that repeats every hour if you like. Because
your PC isn't always on, the "at log on" trigger catches up each time it starts.

## Privacy
`profile/` (your logged-in session), `output/` (customer data) and `.env` are in
`.gitignore`: never upload them to GitHub.
