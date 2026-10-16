# GCVR 2026 Budget Dashboard

Budget vs. actual revenue for the GCVR portfolio: Sandalfoot, Signal Inn, GBB, YCA, Colony Inn,
Non-Resort and Island Vacations. One web page that rebuilds itself every morning from Streamline
reservation data, plus a weekly summary posted to Teams.

| | |
|---|---|
| **Dashboard** | https://budget.choosegulfcoast.com/ (no login: open to anyone with the address) |
| Previous GitHub link | https://psfin.github.io/gcvr-budget-dashboard/ (redirects to the dashboard) |
| Code | https://github.com/PSFIN/gcvr-budget-dashboard (public, code only) |
| Server | AWS Lightsail `gulfcoast-tools`, IP `54.243.31.14`, Caddy web server |
| Page refresh | every day at **8:00 AM Eastern**, automatic |
| Teams summary | every **Monday** after the refresh, to a private channel |

## What is running and what is working

Last checked 2026-10-16.

| Piece | What it does | Status |
|---|---|---|
| Streamline sync | The pacing project (`~/gulf-coast-pacing`) keeps `pacing.db` current with Streamline reservations | Working. The page header shows "Data as of" (the last sync time) and "Page updated" (the build time) |
| Daily refresh | `budget-update.timer` runs `deploy/update.sh` every day at 8:00 AM Eastern | Working. The page was rebuilt on the morning of 2026-10-16 |
| Web server | Caddy serves `/var/www/budget/index.html` over HTTPS, no login | Working. Certificate renews itself |
| Private budgets | `budgets_2026.json` holds the monthly targets, on the server and the Mac only | In place. Never in Git |
| Teams summary | Posts a written summary with the change since last week | Working. First post confirmed 2026-10-15, to a private channel |
| GitHub link redirect | `index.html` in this repo is a redirect page | Working |
| This repo | Code only: no budget or revenue figures in the files or history | Clean |

## How it works

Every morning at 8:00 AM Eastern the server runs `deploy/update.sh`, which:

1. pulls the latest code from this repo,
2. runs `build_dashboard.py`, which reads the Streamline reservations from `pacing.db`, works out
   revenue per property and adds the private budget targets,
3. writes the finished page to `/var/www/budget/index.html`,
4. saves a private snapshot of the day's numbers and, on Mondays, posts the Teams summary.

The script reads three local data files (`pacing.db`, `custom_groups.json`, the private
`budgets_2026.json`) and makes no Streamline calls. The only outside call is the Teams post.

### The two times in the page header

The header shows both: **Data as of** and **Page updated**.

- **Page updated** is when the page was built (normally 8:00 AM Eastern).
- **Data as of** is when Streamline last synced. The pacing project syncs about every 3 hours
  (observed at :27 past the hour, for example 6:27, 9:27 and 12:27), and the 8:00 AM build uses the
  newest sync available at that moment, so this normally reads about 6:27 AM.

If "Data as of" is more than 48 hours old, the script prints a warning: the sync, not this job, is stuck.

## How the numbers are calculated

- A booking counts once, with its whole rent in the month of **check-in**.
- Cancelled bookings, inquiries, owner/admin/maintenance blocks and $0 stays are left out.
- Months after today are bookings already on the books (future check-ins).
- **Revenue recognized** is therefore stays already checked in plus bookings already on the books
  for the rest of the year. **Remaining to book** is the target minus that.
- **Last Year (Pace)** is the previous year by the same rule, keeping only bookings created on or
  before the same weekday a year ago (today minus 364 days).

| Property | Streamline units |
|---|---|
| Sandalfoot | active units named Sandalfoot plus retired `z...` units found in reservations (59) |
| Signal Inn | group "Signal Inn Total" (19) |
| GBB | group "Gulf and Bay Total" (46) |
| YCA | group "YCBR" (27) |
| Colony Inn | group "Colony Inn" (33) |
| Island Vacations | units in "Island Vacations" that are also in a Non-Resort group or in "Lais (ALL- NonResort)" (16) |
| Non-Resort | the two Non-Resort groups **minus Island Vacations** (144) |

Known limits:

- Streamline zeroes the rent of bookings cancelled later, so last-year pace can read about 1-4% low.
- Colony Inn has no Streamline history before Dec 2025, so its last year is understated.
- YCA reads about 2.5% low in one month (March). The cause has not been found.

## Teams summary

Every Monday, right after the 8:00 AM refresh, the job posts one full-width card to a Teams channel:

- a headline with the portfolio total, progress toward target and the change since last week,
- a table with one row per property: status colour (🟢 target met, 🟡 75-99%, 🔴 under 75%),
  recognized vs target, a progress bar, the change since last week (📈 up, 📉 down, ➖ none) and
  how much is left to book ("to go") or "Met" with the amount over,
- a button that opens the dashboard.

The change compares with the private snapshot saved a week earlier. In the first weeks, before a
snapshot exists, last week is estimated from booking dates and labelled "estimated". The weekly
change is the net new bookings.

It is sent through a Teams Workflows webhook. The webhook address is a secret (anyone with it can
post to the channel), so it is kept only in the private file `teams_webhook.url` on the server,
never in Git. Without that file the job simply skips the post. A failed post never blocks the page.

**Set up or change the channel:**

1. In Teams, open the channel that should get the message (use a **private** channel: the message
   contains revenue and target figures). Click the **...** next to the channel name, choose
   **Workflows**, and pick **Post to a channel when a webhook request is received**. Name it,
   confirm the team and channel, create it, and copy the web address it shows.
2. On the server, save it without showing it on screen (paste when asked, then press Enter):

```bash
read -rsp "Paste the Teams webhook URL, then press Enter: " U && echo && printf '%s\n' "$U" > /home/ubuntu/budget-data/teams_webhook.url && chmod 600 /home/ubuntu/budget-data/teams_webhook.url && unset U && echo saved
```

3. Send a test message now (it posts whatever day it is):

```bash
FORCE_NOTIFY=1 /home/ubuntu/budget-dashboard/deploy/update.sh
```

The output should include "Teams message posted (HTTP 202)". When changing channel, also delete the
old workflow in the Teams **Workflows** app, which switches the old address off.

**Post every day instead of Mondays:** add `Environment=NOTIFY=daily` under `[Service]` in
`deploy/budget-update.service`, push, then on the server copy it to `/etc/systemd/system/` and run
`sudo systemctl daemon-reload`. **Stop the messages:** `rm /home/ubuntu/budget-data/teams_webhook.url`.
The page keeps refreshing either way.

## Private files (not in Git)

| File | Server location | Holds |
|---|---|---|
| `budgets_2026.json` | `/home/ubuntu/budget-data/` (and next to `build_dashboard.py` on the Mac) | The monthly targets: one entry per property, 12 numbers each, January to December |
| `teams_webhook.url` | `/home/ubuntu/budget-data/` | The Teams webhook address |
| `history/` | `/home/ubuntu/budget-data/` | One small snapshot a day, for the week-over-week change |

```json
{"Sandalfoot": [12 numbers], "Signal Inn": [...], "GBB": [...], "YCA": [...],
 "Colony Inn": [...], "Non-Resort": [...], "Island Vacations": [...]}
```

## Everyday tasks

Run these in the Lightsail browser SSH terminal.

**Refresh the page right now** (instead of waiting for 8:00 AM):

```bash
/home/ubuntu/budget-dashboard/deploy/update.sh
```

**See the next scheduled run and how the last one went:**

```bash
systemctl list-timers budget-update.timer --no-pager; journalctl -u budget-update.service -n 30 --no-pager
```

**Change the budget targets:** edit the file, then refresh the page. Do the same on the Mac copy.

```bash
nano /home/ubuntu/budget-data/budgets_2026.json
```

**Validate and reload Caddy** (always validate first; other apps share this Caddy):

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

**Change the schedule:** edit `OnCalendar` in `deploy/budget-update.timer`, push to GitHub, then on the server:

```bash
cd /home/ubuntu/budget-dashboard && git pull && sudo cp deploy/budget-update.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart budget-update.timer
```

**Test on the Mac without writing anything:**

```bash
cd "/Users/shinodvengaloor/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Budget" && python3 build_dashboard.py --dry-run
```

Without `--dry-run` it writes `dashboard.preview.html` (git-ignored). It never writes figures into the template.

## If something looks wrong

| Symptom | What to check |
|---|---|
| Numbers look old | Compare the two times in the page header. If "Page updated" is recent but "Data as of" is old, Streamline's sync (the pacing project) is behind, not this job. If "Page updated" is old, the job did not run |
| It did not update this morning | `journalctl -u budget-update.service -n 30 --no-pager`, then run `update.sh` by hand |
| Teams message did not arrive | Look for "Teams:" in `journalctl -u budget-update.service -n 40 --no-pager`. "no webhook configured" means the webhook file is missing; "HTTP 4xx" means the workflow was deleted or the address is wrong (create a new one and save it again) |
| "Could not find budgets_2026.json" | Create it in `/home/ubuntu/budget-data/` (see Private files). The page keeps the last good version meanwhile |
| "Could not find pacing.db" | The pacing project folder moved. Set `PACING_DIR` in `deploy/update.sh` |
| Certificate error | DNS for `budget.choosegulfcoast.com` must point at `54.243.31.14`. Wait a minute and retry |

## Files in this repo

| File | Purpose |
|---|---|
| `build_dashboard.py` | Builds the page from Streamline data and the private budgets; posts the Teams summary |
| `dashboard_template.html` | Empty page template (no figures) |
| `deploy/update.sh` | The daily job: pull code, rebuild, publish, notify |
| `deploy/budget-update.service`, `deploy/budget-update.timer` | systemd job and its 8:00 AM Eastern schedule |
| `deploy/Caddyfile.snippet` | The Caddy site block |
| `deploy/SETUP.md` | Step-by-step rebuild of the server setup (only needed on a new or reset server) |
| `index.html` | Redirect from the old GitHub link to the dashboard |

## Security

- The dashboard has **no login**: anyone who has the address can view the figures. It asks search
  engines not to list it (`noindex`), which is not access control, so do not share the address outside
  the company. To add a login again, add a Caddy `basicauth` directive to the site block (never commit a
  password hash: this repo is public).
- The Teams summary shows the same figures to everyone in its channel, so keep that channel private.
- This repo is public and holds code only. Budget targets stay in the private `budgets_2026.json`;
  revenue is read from Streamline on the server. Never commit `budgets_2026.json`, a webhook address
  or a generated dashboard (`.gitignore` blocks them).
- The Streamline token lives only on the server in the pacing project and must never be copied into this repo.
