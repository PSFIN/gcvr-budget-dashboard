# GCVR 2026 Budget Dashboard

Budget vs. actual revenue for the GCVR portfolio: Sandalfoot, Signal Inn, GBB, YCA, Colony Inn,
Non-Resort and Island Vacations. One web page that rebuilds itself every morning from Streamline
reservation data, plus a weekly summary posted to Teams.

| | |
|---|---|
| **Dashboard** | https://budget.choosegulfcoast.com/ (password, user `gulfcoast`) |
| Old link | https://psfin.github.io/gcvr-budget-dashboard/ (redirects to the dashboard) |
| Code | https://github.com/PSFIN/gcvr-budget-dashboard (public, code only) |
| Server | AWS Lightsail `gulfcoast-tools`, IP `54.243.31.14`, Caddy web server |
| Page refresh | every day at **8:00 AM Eastern**, automatic |
| Teams summary | every **Monday** after the refresh, to a private channel |

## What is running and what is working

Last checked 2026-10-15.

| Piece | What it does | Status |
|---|---|---|
| Streamline sync | The pacing project (`~/gulf-coast-pacing`) keeps `pacing.db` current with Streamline reservations | Working. The page header shows "Data as of" (the last sync time) |
| Daily refresh | `budget-update.timer` runs `deploy/update.sh` every day at 8:00 AM Eastern | Working |
| Web server | Caddy serves `/var/www/budget/index.html` over HTTPS behind a login | Working. Certificate renews itself |
| Private budgets | `budgets_2026.json` holds the monthly targets, on the server and the Mac only | In place. Never in Git |
| Teams summary | Posts a written summary with the change since last week | Working. Posts to a private channel |
| Old GitHub link | `index.html` in this repo is a redirect page | Working |
| This repo | Code only: no budget or revenue figures in the files or history | Clean |

## How it works

Every morning at 8:00 AM Eastern the server runs `deploy/update.sh`, which:

1. pulls the latest code from this repo,
2. runs `build_dashboard.py`, which reads the Streamline reservations from `pacing.db`, works out
   revenue per property and adds the private budget targets,
3. writes the finished page to `/var/www/budget/index.html`,
4. saves a private snapshot of the day's numbers and, on Mondays, posts the Teams summary.

The script reads three local data files (`pacing.db`, `custom_groups.json`, the private
`budgets_2026.json`) and makes no Streamline calls. The only outside call is the Teams post. If the
data is more than 48 hours old the script prints a warning, and the page header always shows when
Streamline last synced.

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

**Change the password:** run `caddy hash-password`, replace the hash after `gulfcoast` in the
`budget.choosegulfcoast.com` block in both `/etc/caddy/Caddyfile` and `/etc/caddy/Caddyfile.pending`,
then validate and reload Caddy (below). Never commit a hash.

**Validate and reload Caddy** (always validate first; other apps share this Caddy, which is an older
version, so the directive is `basicauth`, not `basic_auth`):

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
| Numbers look old | The "Data as of" time in the page header. If it is old, Streamline's sync (the pacing project) is behind, not this job |
| It did not update this morning | `journalctl -u budget-update.service -n 30 --no-pager`, then run `update.sh` by hand |
| Teams message did not arrive | Look for "Teams:" in `journalctl -u budget-update.service -n 40 --no-pager`. "no webhook configured" means the webhook file is missing; "HTTP 4xx" means the workflow was deleted or the address is wrong (create a new one and save it again) |
| "Could not find budgets_2026.json" | Create it in `/home/ubuntu/budget-data/` (see Private files). The page keeps the last good version meanwhile |
| "Could not find pacing.db" | The pacing project folder moved. Set `PACING_DIR` in `deploy/update.sh` |
| Certificate error | DNS for `budget.choosegulfcoast.com` must point at `54.243.31.14`. Wait a minute and retry |
| Wrong login | Change the password (see above) |

## Files in this repo

| File | Purpose |
|---|---|
| `build_dashboard.py` | Builds the page from Streamline data and the private budgets; posts the Teams summary |
| `dashboard_template.html` | Empty page template (no figures) |
| `deploy/update.sh` | The daily job: pull code, rebuild, publish, notify |
| `deploy/budget-update.service`, `deploy/budget-update.timer` | systemd job and its 8:00 AM Eastern schedule |
| `deploy/Caddyfile.snippet` | The Caddy site block (the password hash is filled in on the server) |
| `index.html` | Redirect from the old GitHub link to the dashboard |

## Security

- This repo is public and holds code only. Budget targets stay in the private `budgets_2026.json`;
  revenue is read from Streamline on the server. Never commit `budgets_2026.json`, a webhook address
  or a generated dashboard (`.gitignore` blocks them).
- The password protects https://budget.choosegulfcoast.com/, the only place the full numbers appear.
  The Teams summary shows the same figures to everyone in its channel, so keep that channel private.
- The Streamline token lives only on the server in the pacing project and must never be copied into this repo.

<details>
<summary><b>Setting up from scratch</b> (already done; kept for rebuilding the server)</summary>

Run each command in the Lightsail browser SSH terminal, one at a time. The DNS A record
`budget.choosegulfcoast.com` -> `54.243.31.14` must already exist. Nothing here edits an existing
Caddy site block.

**1. Check Caddy is healthy:**

```bash
caddy version && sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

**2. Check nothing for "budget" exists yet** (no output is good):

```bash
grep -n "budget" /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pending
```

**3. Check the Streamline data files exist and create the web folder:**

```bash
ls -l /home/ubuntu/gulf-coast-pacing/pacing.db /home/ubuntu/gulf-coast-pacing/custom_groups.json && sudo mkdir -p /var/www/budget && sudo chown ubuntu:ubuntu /var/www/budget
```

**4. Clone this repo** (public, so no key is needed):

```bash
git clone https://github.com/PSFIN/gcvr-budget-dashboard.git /home/ubuntu/budget-dashboard
```

**5. Create the private budgets folder**, then create `budgets_2026.json` in it. Paste the JSON from
the Mac copy with a `cat > /home/ubuntu/budget-data/budgets_2026.json <<'EOF' ... EOF` command, then
`chmod 600` the file:

```bash
mkdir -p /home/ubuntu/budget-data && chmod 700 /home/ubuntu/budget-data
```

**6. Build the first page:**

```bash
chmod +x /home/ubuntu/budget-dashboard/deploy/update.sh && /home/ubuntu/budget-dashboard/deploy/update.sh
```

**7. Choose the website password** (typed twice; the hash goes to a private file):

```bash
caddy hash-password > /home/ubuntu/.budget-auth-hash && chmod 600 /home/ubuntu/.budget-auth-hash
```

**8. Back up both Caddyfiles:**

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-budget && sudo cp /etc/caddy/Caddyfile.pending /etc/caddy/Caddyfile.pending.bak-budget
```

**9. Add the site block to the bottom of both Caddyfiles:**

```bash
sed "s|REPLACE_WITH_BCRYPT_HASH|$(cat /home/ubuntu/.budget-auth-hash)|" /home/ubuntu/budget-dashboard/deploy/Caddyfile.snippet | sudo tee -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pending > /dev/null
```

**10. Validate** (must say "Valid configuration"), then reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

**11. Install the daily 8:00 AM Eastern job:**

```bash
sudo cp /home/ubuntu/budget-dashboard/deploy/budget-update.service /home/ubuntu/budget-dashboard/deploy/budget-update.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now budget-update.timer
```

**12. Check the schedule and test the job once:**

```bash
systemctl list-timers budget-update.timer --no-pager && sudo systemctl start budget-update.service && journalctl -u budget-update.service -n 25 --no-pager
```

**13. Test the website.** Expect `401` (login required), then log in from a browser:

```bash
curl -sI https://budget.choosegulfcoast.com/ | head -n 3
```

**14. Delete the saved hash file:**

```bash
rm /home/ubuntu/.budget-auth-hash
```

If anything fails after step 9, restore the backups, then validate and reload Caddy:

```bash
sudo cp /etc/caddy/Caddyfile.bak-budget /etc/caddy/Caddyfile && sudo cp /etc/caddy/Caddyfile.pending.bak-budget /etc/caddy/Caddyfile.pending && sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

To remove the site: delete the `budget.choosegulfcoast.com` block from both Caddyfiles, validate and
reload Caddy, then `sudo systemctl disable --now budget-update.timer` and delete
`/etc/systemd/system/budget-update.service` and `budget-update.timer`.

</details>
