#!/usr/bin/env python3
"""
GCVR Budget Dashboard: builds the page from Streamline data.

Reads the Streamline reservations that the pacing project keeps in pacing.db (plus
custom_groups.json), works out revenue per property, adds the private 2026 budget
targets and writes the finished dashboard page. It can also post a weekly summary to
Teams. It makes no Streamline API calls and needs no token.

Revenue recognized:
  * every booking counts once, with its whole rent in the month of CHECK-IN;
  * cancelled bookings (status 8), inquiries (status 9), owner / admin / maintenance
    blocks and $0 stays are left out;
  * months after today are bookings already on the books (future check-ins).

Last Year (Pace) is the same calculation for the previous year, keeping only bookings
created on or before the same weekday one year ago (today minus 364 days). Streamline
zeroes the rent of bookings cancelled later, so last-year pace can read ~1-4% low, and
Colony Inn has no Streamline history before Dec 2025.

Unit groups:
  Sandalfoot        active units named Sandalfoot + retired ("z...") ones found by
                    name in the reservations
  Signal Inn        custom group "Signal Inn Total"
  GBB               custom group "Gulf and Bay Total"
  YCA               custom group "YCBR"
  Colony Inn        custom group "Colony Inn"
  Island Vacations  units in "Island Vacations" that are also in a Non-Resort group or
                    in "Lais (ALL- NonResort)"
  Non-Resort        the two Non-Resort groups MINUS Island Vacations

Private inputs (never in Git: the repo is public):
  budgets_2026.json  {"Sandalfoot": [12 monthly numbers], ...} one entry per property.
                     The template dashboard_template.html holds no figures at all; the
                     script fills in targets, actuals and last year.
  teams_webhook.url  the Teams Workflows webhook address (a secret), next to the budgets.

Teams notification: with --notify monday (or daily) the script posts a full-width card:
revenue recognized vs target per property, how much each moved since last week and how
much is left to book. Each run saves a private snapshot in --history-dir; the message
compares with the snapshot from about 7 days earlier (or, the first time, an estimate
from booking dates). A failed post never blocks the page.

Usage:
  python3 build_dashboard.py                     # writes dashboard.preview.html (git-ignored)
  python3 build_dashboard.py --out /var/www/budget/index.html     # the server job
  python3 build_dashboard.py --dry-run           # calculate and print, write nothing
  python3 build_dashboard.py --dry-run --notify monday --force-notify   # preview the Teams message
Options: --pacing-dir DIR, --budgets FILE, --template FILE, --out FILE, --today YYYY-MM-DD,
         --max-age-hours N, --notify off|monday|daily, --force-notify, --history-dir DIR,
         --webhook-file FILE
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_TYPES = {"OWN", "ABL", "MaintenanceBlock"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PROPERTY_ORDER = ["Sandalfoot", "Signal Inn", "GBB", "YCA", "Colony Inn", "Non-Resort", "Island Vacations"]
JS_NAMES = {"Non-Resort": "Non-Resort Portfolio"}          # dashboard unit name if different
REQUIRED_GROUPS = ["Non-Resort (14 Min Below)", "Non-Resort (30 Min Above)", "Island Vacations",
                   "Lais (ALL- NonResort)", "Signal Inn Total", "Gulf and Bay Total", "YCBR", "Colony Inn"]


# ── Locating and reading the Streamline data ──────────────────────────────────
def find_pacing_dir(arg):
    candidates = [arg, os.environ.get("PACING_DIR"), "/home/ubuntu/gulf-coast-pacing",
                  os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/"
                                     "Desktop/GBB LOS/resort-blocks/03-pacing")]
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "pacing.db")) \
                and os.path.exists(os.path.join(c, "custom_groups.json")):
            return c
    sys.exit("Could not find pacing.db + custom_groups.json. Pass --pacing-dir DIR "
             "or set PACING_DIR (on the server it is /home/ubuntu/gulf-coast-pacing).")


def find_budgets(arg):
    candidates = [arg, os.environ.get("BUDGETS_FILE"), "/home/ubuntu/budget-data/budgets_2026.json",
                  os.path.join(HERE, "budgets_2026.json")]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("Could not find budgets_2026.json (the private 2026 budget targets, not kept in Git).\n"
             "Put it at /home/ubuntu/budget-data/budgets_2026.json on the server, next to this script on "
             "the Mac, or pass --budgets FILE.")


def load_budgets(path):
    data = json.load(open(path))
    bad = [p for p in PROPERTY_ORDER if p not in data or len(data[p]) != 12]
    if bad:
        sys.exit(f"{path} must have 12 monthly numbers for each of: {bad}")
    return {p: [float(x) for x in data[p]] for p in PROPERTY_ORDER}


def parse_day(s):
    return datetime.strptime(s[:10], "%m/%d/%Y").date()


def has(text, word):
    return word in (text or "").lower()


def load_streamline(pacing_dir):
    """Returns (property -> set of unit ids, qualifying bookings, last_sync datetime)."""
    groups = {k: set(v) for k, v in json.load(open(os.path.join(pacing_dir, "custom_groups.json"))).items()}
    missing = [g for g in REQUIRED_GROUPS if g not in groups]
    if missing:
        sys.exit(f"custom_groups.json is missing these groups: {missing}")

    con = sqlite3.connect(f"file:{os.path.join(pacing_dir, 'pacing.db')}?mode=ro", uri=True)
    last_sync = con.execute("select value from meta where key='last_sync'").fetchone()
    last_sync = datetime.fromisoformat(last_sync[0]) if last_sync else None

    sandalfoot = {uid for uid, name, ctype, resort in
                  con.execute("select id, name, condo_type_name, location_resort_name from units")
                  if has((name or "") + (ctype or "") + (resort or ""), "sandalfoot")}
    bookings = []
    for uid, uname, ctype, typ, status, start, nights, rent, created in con.execute(
            "select unit_id, unit_name, condo_type_name, type_name, status_id, startdate, "
            "days_number, price_nightly, creation_date from reservations"):
        if has((uname or "") + (ctype or ""), "sandalfoot"):
            sandalfoot.add(uid)                      # retired units are only visible here
        if (status in (8, 9) or typ in BLOCK_TYPES or not nights or nights <= 0
                or not rent or rent <= 0 or not start or not created):
            continue
        bookings.append((uid, parse_day(start), parse_day(created), rent))
    con.close()

    non_resort_all = groups["Non-Resort (14 Min Below)"] | groups["Non-Resort (30 Min Above)"]
    island = groups["Island Vacations"] & (non_resort_all | groups["Lais (ALL- NonResort)"])
    units = {
        "Sandalfoot": sandalfoot,
        "Signal Inn": groups["Signal Inn Total"],
        "GBB": groups["Gulf and Bay Total"],
        "YCA": groups["YCBR"],
        "Colony Inn": groups["Colony Inn"],
        "Non-Resort": non_resort_all - island,
        "Island Vacations": island,
    }
    return units, bookings, last_sync


def monthly_revenue(bookings, units, year, asof=None):
    """Whole rent in the check-in month; optional 'as of' = created on/before that day."""
    owner = defaultdict(list)
    for prop, ids in units.items():
        for uid in ids:
            owner[uid].append(prop)
    out = {prop: [0.0] * 12 for prop in units}
    for uid, start, created, rent in bookings:
        if start.year != year or (asof and created > asof) or uid not in owner:
            continue
        for prop in owner[uid]:
            out[prop][start.month - 1] += rent
    return out


# ── Reading / patching the dashboard ──────────────────────────────────────────
def js_arr(vals):
    return "[" + ", ".join(str(round(v, 2)) for v in vals) + "]"


def js_name(prop):
    return JS_NAMES.get(prop, prop)


def patch_dashboard(html, budgets, current, last_year, today, generated):
    for prop in PROPERTY_ORDER:
        for key, vals in (("goals", budgets[prop]), ("actuals", current[prop]), ("lastYear", last_year[prop])):
            pattern = re.compile(r'(unit:\s*"' + re.escape(js_name(prop)) + r'".*?' + key + r':\s*)\[[^\]]*\]', re.S)
            html, n = pattern.subn(lambda m, v=vals: m.group(1) + js_arr(v), html, count=1)
            if n != 1:
                sys.exit(f'Template has no "{key}" array for unit "{js_name(prop)}" — nothing written.')
    for pattern, replacement in (
            (r'const GENERATED\s*=\s*"[^"]*"', f'const GENERATED = "{generated}"'),
            (r'const CURRENT_MONTH\s*=\s*\d+', f'const CURRENT_MONTH = {today.month}'),
            (r'const AS_OF_DATE\s*=\s*"[^"]*"', f'const AS_OF_DATE = "{today.isoformat()}"')):
        html, n = re.subn(pattern, replacement, html)
        if n != 1:
            sys.exit(f"Template is missing {pattern.split()[1]} — nothing written.")
    return html


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)                      # Caddy runs as another user and must be able to read it
    os.replace(tmp, path)


# ── Reports ───────────────────────────────────────────────────────────────────
def print_summary(budgets, current, today):
    cm = today.month
    print(f"\n  {'Property':<17}{'Budget YTD':>12}{'Actual YTD':>12}{'Attain':>8}   {'Full-year recognized + booked':>30}")
    print(f"  {'-'*17}{'-'*12}{'-'*12}{'-'*8}   {'-'*30}")
    tb = ta = tf = 0.0
    for prop in PROPERTY_ORDER:
        a, f = sum(current[prop][:cm]), sum(current[prop])
        b = sum(budgets[prop][:cm])
        tb, ta, tf = tb + b, ta + a, tf + f
        print(f"  {prop:<17}{b:>12,.0f}{a:>12,.0f}{(a / b * 100 if b else 0):>7.1f}%   {f:>30,.0f}")
    print(f"  {'GCVR TOTAL':<17}{tb:>12,.0f}{ta:>12,.0f}{(ta / tb * 100 if tb else 0):>7.1f}%   {tf:>30,.0f}")


# ── Teams notification: weekly summary with the change since last week ────────
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://budget.choosegulfcoast.com/")


def money(n):
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"${n / 1_000_000:,.2f}M"
    if abs(n) >= 1_000:
        return f"${n / 1_000:,.0f}K"
    return f"${n:,.0f}"


def portfolio_numbers(budgets, current):
    """Per property: full-year target and revenue recognized (checked in + already booked)."""
    rows = {p: {"target": sum(budgets[p]), "recognized": sum(current[p])} for p in PROPERTY_ORDER}
    rows["GCVR TOTAL"] = {k: sum(r[k] for r in rows.values()) for k in ("target", "recognized")}
    return rows


def save_snapshot(history_dir, today, rows, data_as_of):
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, f"{today.isoformat()}.json")
    with open(path, "w") as f:
        json.dump({"date": today.isoformat(), "data_as_of": data_as_of, "rows": rows}, f, indent=1)
    os.chmod(path, 0o600)


def find_previous(history_dir, today):
    """The saved snapshot closest to 7 days ago (accepted: 5 to 9 days ago)."""
    best = None
    if history_dir and os.path.isdir(history_dir):
        for name in os.listdir(history_dir):
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", name)
            if not m:
                continue
            day = date.fromisoformat(m.group(1))
            gap = (today - day).days
            if 5 <= gap <= 9 and (best is None or abs(gap - 7) < best[0]):
                best = (abs(gap - 7), day, os.path.join(history_dir, name))
    if not best:
        return None
    with open(best[2]) as f:
        return best[1], json.load(f)["rows"]


def status_emoji(pct):
    """Same bands as the dashboard's progress colours."""
    return "🟢" if pct >= 100 else ("🟡" if pct >= 75 else "🔴")


def status_color(pct):
    return "Good" if pct >= 100 else ("Warning" if pct >= 75 else "Attention")


def progress_bar(pct):
    filled = max(0, min(10, round(pct / 10)))
    return "▰" * filled + "▱" * (10 - filled)


def week_change(delta):
    """(text, Adaptive Card colour) for the change since last week."""
    if delta is None:
        return "—", "Default"
    if abs(delta) < 500:
        return "➖ no change", "Default"
    if delta > 0:
        return f"📈 ▲ {money(delta)}", "Good"
    return f"📉 ▼ {money(-delta)}", "Attention"


def to_go(remaining):
    if remaining > 0:
        return f"🎯 {money(remaining)}", "Default"
    return f"✅ Met (+{money(-remaining)})", "Good"


def build_message(rows, prev_rows, prev_label, today, data_as_of):
    """Returns (plain text for the log, Adaptive Card payload for Teams)."""
    def cells(name):
        r = rows[name]
        pct = r["recognized"] / r["target"] * 100 if r["target"] else 0
        delta = (r["recognized"] - prev_rows[name]["recognized"]) if prev_rows and name in prev_rows else None
        change, change_color = week_change(delta)
        go, go_color = to_go(r["target"] - r["recognized"])
        return {"pct": pct, "money": f"{money(r['recognized'])} / {money(r['target'])}",
                "bar": f"{progress_bar(pct)} {pct:.0f}%", "change": change, "change_color": change_color,
                "go": go, "go_color": go_color}

    title = f"📊 GCVR Budget Dashboard — {today:%A, %b} {today.day}"
    subtitle = (f"🗓️ Change vs last week ({prev_label}) · 🕒 Data as of {data_as_of}"
                if prev_rows else f"🕒 Data as of {data_as_of}")
    tot = cells("GCVR TOTAL")
    headline = (f"💰 **GCVR total: {tot['money'].replace(' / ', ' of ')}** {tot['bar']} · "
                f"{tot['change']} vs last week · {tot['go']}" if prev_rows else
                f"💰 **GCVR total: {tot['money'].replace(' / ', ' of ')}** {tot['bar']} · {tot['go']}")
    footer = (f"ℹ️ Recognized = stays already checked in + bookings already on the books for the rest of "
              f"{today.year}. To go = target minus that. Non-Resort excludes Island Vacations.")

    # plain-text copy for the log
    lines = [title, subtitle, "", headline, ""]
    for name in PROPERTY_ORDER:
        c = cells(name)
        lines.append(f"{status_emoji(c['pct'])} {name}: {c['money']} · {c['bar']} · {c['change']} · {c['go']}")
    text = "\n".join(lines + ["", footer])

    def row(values, header=False):
        """One table row as an Adaptive Card ColumnSet (weights give full-width columns)."""
        widths = ["auto", 3, 4, 4, 3, 3]
        columns = []
        for w, (txt, color) in zip(widths, values):
            block = {"type": "TextBlock", "text": txt, "wrap": True, "color": color}
            if header:
                block.update({"size": "Small", "weight": "Bolder", "isSubtle": True})
            columns.append({"type": "Column", "width": w, "verticalContentAlignment": "Center",
                            "items": [block]})
        return {"type": "ColumnSet", "columns": columns, "spacing": "Small", "separator": True}

    body = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Large", "wrap": True},
        {"type": "TextBlock", "text": subtitle, "isSubtle": True, "spacing": "None", "wrap": True},
        {"type": "Container", "style": "emphasis", "spacing": "Medium", "bleed": False,
         "items": [{"type": "TextBlock", "text": headline, "wrap": True}]},
        row([("", "Default"), ("Property", "Default"), ("Recognized / Target", "Default"),
             ("Progress", "Default"), ("vs last week", "Default"), ("To go", "Default")], header=True),
    ]
    for name in PROPERTY_ORDER:
        c = cells(name)
        body.append(row([(status_emoji(c["pct"]), "Default"), (f"**{name}**", "Default"),
                         (c["money"], "Default"), (c["bar"], status_color(c["pct"])),
                         (c["change"], c["change_color"]), (c["go"], c["go_color"])]))
    body.append({"type": "TextBlock", "text": footer, "isSubtle": True, "size": "Small",
                 "wrap": True, "spacing": "Medium"})
    card = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard", "version": "1.4",
            "msteams": {"width": "Full"},
            "body": body,
            "actions": [{"type": "Action.OpenUrl", "title": "🔗 Open the dashboard", "url": DASHBOARD_URL}],
        }}]}
    return text, card


def post_to_teams(webhook_url, payload):
    req = urllib.request.Request(webhook_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:      # never print the URL: it is a secret
        raise RuntimeError(f"Teams answered HTTP {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        raise RuntimeError(f"could not reach Teams ({type(e).__name__})")


def notify_teams(args, today, rows, data_as_of, bookings, units, budgets, history_dir, webhook_file):
    """Post the weekly summary when it is due. Never raises: the page is already written."""
    due = (args.force_notify or args.notify == "daily"
           or (args.notify == "monday" and today.weekday() == 0))
    if args.notify == "off" and not args.force_notify:
        return
    if not due:
        print("  Teams: not a notification day (Mondays only), skipping.")
        return
    state_path = os.path.join(history_dir, "notified.json") if history_dir else None
    if state_path and os.path.exists(state_path) and not args.force_notify and not args.dry_run:
        with open(state_path) as f:
            if json.load(f).get("last") == today.isoformat():
                print("  Teams: already posted today, skipping.")
                return
    webhook = None
    if os.path.exists(webhook_file):
        with open(webhook_file) as f:
            webhook = f.read().strip()
    if not webhook and not args.dry_run:
        print(f"  Teams: no webhook configured (create {webhook_file}), skipping.")
        return

    previous = find_previous(history_dir, today)
    if previous:
        prev_day, prev_rows = previous
        prev_label = f"{prev_day:%b} {prev_day.day}"
    else:                                   # first week: estimate from booking dates
        asof = today - timedelta(days=7)
        prev_rows = portfolio_numbers(budgets, monthly_revenue(bookings, units, today.year, asof))
        prev_label = f"{asof:%b} {asof.day}, estimated from booking dates"
    text, card = build_message(rows, prev_rows, prev_label, today, data_as_of)
    print("\n  Teams message:\n" + "\n".join("    " + t for t in text.splitlines()))
    if args.dry_run:
        print("\n  Dry run: not posting.")
        return
    try:
        status = post_to_teams(webhook, card)
    except RuntimeError as e:
        print(f"  !! Teams post failed: {e}")
        return
    print(f"  Teams message posted (HTTP {status}).")
    if state_path:
        with open(state_path, "w") as f:
            json.dump({"last": today.isoformat()}, f)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pacing-dir")
    ap.add_argument("--budgets", help="private budgets_2026.json (default: server path, or next to this script)")
    ap.add_argument("--template", default=os.path.join(HERE, "dashboard_template.html"))
    ap.add_argument("--out", default=os.path.join(HERE, "dashboard.preview.html"),
                    help="where to write the finished page (default: dashboard.preview.html, git-ignored)")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    ap.add_argument("--max-age-hours", type=float, default=48, help="warn if pacing.db is older than this")
    ap.add_argument("--dry-run", action="store_true", help="calculate and report, write nothing")
    ap.add_argument("--notify", choices=["off", "monday", "daily"], default="off",
                    help="post the written summary to Teams (default: off)")
    ap.add_argument("--force-notify", action="store_true", help="post now, even if it is not a notification day")
    ap.add_argument("--history-dir", default=os.environ.get("HISTORY_DIR"),
                    help="private folder for weekly snapshots (server: /home/ubuntu/budget-data/history)")
    ap.add_argument("--webhook-file", default=os.environ.get("TEAMS_WEBHOOK_FILE"),
                    help="file holding the Teams webhook URL (default: teams_webhook.url next to budgets_2026.json)")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    pacing_dir = find_pacing_dir(args.pacing_dir)
    budgets_path = find_budgets(args.budgets)
    budgets = load_budgets(budgets_path)
    webhook_file = args.webhook_file or os.path.join(os.path.dirname(budgets_path), "teams_webhook.url")
    units, bookings, last_sync = load_streamline(pacing_dir)

    print("=" * 66)
    print(f"  GCVR Budget Dashboard — Streamline  —  {today.month}/{today.day}/{today.year}")
    print("=" * 66)
    print(f"  Data: {pacing_dir}")
    if last_sync:
        age = (datetime.now() - last_sync).total_seconds() / 3600
        print(f"  Streamline last synced: {last_sync:%Y-%m-%d %H:%M}  ({age:.1f} hours ago)")
        if age > args.max_age_hours:
            print(f"  !! WARNING: data is more than {args.max_age_hours:.0f} hours old — the sync may be stuck.")
    print("  Units: " + ", ".join(f"{p} {len(units[p])}" for p in PROPERTY_ORDER))

    ly_asof = today - timedelta(days=364)           # same weekday last year
    current = monthly_revenue(bookings, units, today.year)
    last_year = monthly_revenue(bookings, units, today.year - 1, ly_asof)

    html = open(args.template).read()
    generated = (last_sync or datetime.now()).strftime("%-m/%-d/%Y %-I:%M %p")
    html = patch_dashboard(html, budgets, current, last_year, today, generated)

    print_summary(budgets, current, today)

    rows = portfolio_numbers(budgets, current)
    if args.dry_run:
        notify_teams(args, today, rows, generated, bookings, units, budgets, args.history_dir, webhook_file)
        print("\n  Dry run: nothing written.\n")
        return
    target = args.out
    write_atomic(target, html)
    print(f"\n  Dashboard written: {target}")
    if args.history_dir:
        save_snapshot(args.history_dir, today, rows, generated)
    notify_teams(args, today, rows, generated, bookings, units, budgets, args.history_dir, webhook_file)
    print()


if __name__ == "__main__":
    main()
