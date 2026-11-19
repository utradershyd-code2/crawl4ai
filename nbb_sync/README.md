# National Broadband panel sync

Reads your customer list from `partner.nationalbroadband.pk` **on your own PC**
(the panel doesn't answer your hosting server), saves it as
`output/customers.csv` / `customers.json`, and sends it to ISP Desk's
`/cron/panel-push` on net.universalfarmaco.com.pk, which adds new customers and
updates packages, expiry dates and status.

## What it copies
* **Customer list:** status, name, customer ID, package, bandwidth, address, mobile,
  activation and expiration dates, remaining days, block reason, comments.
* **Real Time Billing Report** (all pages): ISP Desk creates a recharge invoice for each
  (at the customer's own sale price, else the package list price; never the panel amount)
  and deducts the real cost (panel amount x 2) from the panel wallet.
* **Panel balance** ("Available Balance"): ISP Desk stores it x 2 as the real balance.

It does **not** copy passwords, CNIC numbers or MAC addresses.

## One-time setup (Windows)
1. Extract the zip (right-click > Extract All).
2. Double-click **setup.bat**. It installs everything, opens `.env` in Notepad
   (paste your `CRON_KEY`, save, close), opens the panel for you to log in once,
   runs the first sync and schedules one every 15 minutes.

## Every sync
```
python nbb_sync.py sync
```
Or double-click `run_sync.bat` (output goes to `sync_log.txt`). Results land in `output/`.

It prints what ISP Desk did, e.g. `ISP Desk: 157 rows, 0 new, 3 changed`.

* **"The National Broadband panel signed this PC out"**: double-click `login.bat` and sign in.
* **"Upload refused: HTTP 403"**: `CRON_KEY` in `.env` doesn't match the server.

## Run it automatically
`setup.bat` creates the Task Scheduler task **"NBB Panel Sync"**. Double-click `schedule.bat`
to create or repair the task on its own. The task:
- runs every 15 minutes, which also keeps the panel login alive;
- wakes the PC from sleep for each run, and runs a missed sync as soon as the PC is back;
- never starts a second copy while one is still running.

Results are written to `sync_log.txt`.

**If the panel signs the PC out**, the panel ends the session, for example after the PC has slept
for a long time. When that happens:
- ISP Desk shows a red alert on the dashboard, and "Panel login expired" under the panel balance;
- this PC shows a Windows notification once.

Double-click `login.bat`, sign in, and syncing continues.

Tip: in Windows Settings > System > Power, set "When plugged in, put my device to sleep" to
**Never** on the PC that runs this. A locked screen is fine; sleep is what stops the sync.

## Privacy
`profile/` (your logged-in session), `output/` (customer data) and `.env` are in
`.gitignore`: never upload them to GitHub.
