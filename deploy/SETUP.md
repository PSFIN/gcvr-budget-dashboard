# Rebuilding the server setup

Use this only to rebuild the dashboard on a new or reset Lightsail server. For day-to-day use, see the
[README](../README.md).

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

**5. Create the private budgets folder**, then create `budgets_2026.json` in it (the file format is in the README). Paste the JSON from
the Mac copy with a `cat > /home/ubuntu/budget-data/budgets_2026.json <<'EOF' ... EOF` command, then
`chmod 600` the file:

```bash
mkdir -p /home/ubuntu/budget-data && chmod 700 /home/ubuntu/budget-data
```

**6. Build the first page:**

```bash
chmod +x /home/ubuntu/budget-dashboard/deploy/update.sh && /home/ubuntu/budget-dashboard/deploy/update.sh
```

**7. Back up both Caddyfiles:**

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-budget && sudo cp /etc/caddy/Caddyfile.pending /etc/caddy/Caddyfile.pending.bak-budget
```

**8. Add the site block to the bottom of both Caddyfiles:**

```bash
sudo tee -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pending < /home/ubuntu/budget-dashboard/deploy/Caddyfile.snippet > /dev/null
```

**9. Validate** (must say "Valid configuration"), then reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

**10. Install the daily 8:00 AM Eastern job:**

```bash
sudo cp /home/ubuntu/budget-dashboard/deploy/budget-update.service /home/ubuntu/budget-dashboard/deploy/budget-update.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now budget-update.timer
```

**11. Check the schedule and test the job once:**

```bash
systemctl list-timers budget-update.timer --no-pager && sudo systemctl start budget-update.service && journalctl -u budget-update.service -n 25 --no-pager
```

**12. Test the website.** Expect `200`, then open it in a browser:

```bash
curl -sI https://budget.choosegulfcoast.com/ | head -n 3
```

If anything fails after step 8, restore the backups, then validate and reload Caddy:

```bash
sudo cp /etc/caddy/Caddyfile.bak-budget /etc/caddy/Caddyfile && sudo cp /etc/caddy/Caddyfile.pending.bak-budget /etc/caddy/Caddyfile.pending && sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

To remove the site: delete the `budget.choosegulfcoast.com` block from both Caddyfiles, validate and
reload Caddy, then `sudo systemctl disable --now budget-update.timer` and delete
`/etc/systemd/system/budget-update.service` and `budget-update.timer`.
