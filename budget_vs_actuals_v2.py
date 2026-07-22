#!/usr/bin/env python3
"""
GCVR Portfolio — 2026 Budget vs Actuals
Fetches month-by-month revenue actuals from KeyData and compares against
the 2026 budget targets set in the portfolio budget document.

Properties tracked:
  Sandalfoot       — Resort Wide (55 Units)  → Group 42553
  Signal Inn       — Resort Wide (19 Units)  → Group 32414
  GBB              — Resort Wide (46 Units)  → Group 30479
  Colony Inn       — Resort Wide (32 Units)  → Group 48143
  YCA              — ⚠️  Set YCA_GROUP_ID below once known
  Non-Resort       — ⚠️  Not in KeyData; enter actuals manually if needed

How to run:
  1. Open Chrome — make sure you're logged into KeyData
  2. Open token_bookmarklet.html in any property folder and copy your token
  3. Run:  python3 budget_vs_actuals.py
  4. Paste the token when prompted (or pass it as an argument)

Output:
  - Console table (variance by month and property)
  - budget_vs_actuals_v2_YYYY-MM-DD.html  (visual report saved to this folder)
  - dashboard_v2.html  (interactive dashboard, patched locally — not pushed to git)
"""

import sys, json, urllib.request, os, re
from datetime import date, timedelta

# ── Configuration ──────────────────────────────────────────────────────────────
TODAY        = date.today()
from datetime import datetime as _dt
NOW          = _dt.now()
TODAY_STR    = TODAY.strftime("%-m/%-d/%Y")
TODAY_TS     = NOW.strftime("%-m/%-d/%Y %-I:%M %p")   # e.g. 6/16/2026 2:34 PM
REPORT_DATE  = TODAY.strftime("%Y-%m-%d")
OUTPUT_FOLDER = os.path.dirname(os.path.abspath(__file__))

PRIMARY_SEASON_ID = "d16a0dca-aa77-4e79-b55c-8b89f754a6f3"   # 2026
COMPARE_SEASON_ID = "c4e68241-6fdf-49ec-9107-e47f7885fbcf"   # compare

MARKET_IDS = [
    "486f67bd-bbf4-46ca-a0b3-939acc2dae85","d50a110f-d134-4c64-894c-1cdfaef206c0",
    "8e2290c2-74a7-4e4d-8fc2-447e511d102b","4851f0a3-7d14-4536-a87c-f344ac9e1917",
    "9b607b14-a304-47ac-a0f5-355dd3586dcb","a2e7ae05-7736-4629-8ec0-8fb0aaa04403",
    "024aae58-05b9-4c66-acaa-dd6d8e31cdf9","6668ed34-d4e1-4907-b127-2e5bde7a6667",
    "db0a8e79-01b3-440b-b5d7-abe3148f2606","2c71bfe9-8609-4081-98c8-ff7e4ea48dd8",
    "82280d17-312b-4484-b5df-ac832a4a8550","de288757-759d-4f0f-a1c7-327be28a6eb4",
    "c6d35be4-191a-41dc-ae53-50b974df096b","cb56c4cc-7481-494d-8589-3e6601d4b156",
    "1d9a4bd0-51ad-445f-8c3d-837d68b30b0c","794c21e1-242d-4095-8ded-94f8323de963",
    "b88fca08-0a5a-4b75-9f02-b41d96a40f6d","ab988d5c-2382-44a8-87ed-0bbb93019426",
    "5994aeac-0b0f-41ff-8ee3-6b13b13485d0","ae27a43e-b047-4c55-a74e-2722b6e4d8b6",
    "f876cd2f-d33b-4cb6-8d42-b9f5ad2ad95c","20deccd1-a147-40cb-adb3-52aa8a38a7ef",
    "1a5d846f-397e-49f8-8fe7-46554f2f40df","9f89f8a5-7bf3-47ce-b413-3bcac3b26bce",
    "5044858f-5b64-44d9-bb1d-30aaa1dbb924","0a1bef69-0b4b-48b6-9b63-ce99cee60149",
    "46751949-d896-49fe-8491-b6cd7aa0722b","80a538dd-73f0-4e1d-94ef-5a070fb945a9",
    "37826529-2639-4f95-ad9e-cf68baa0e7b7"
]

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ── 2026 Budget targets (from GCVR Full Portfolio 2026 Budget.pdf) ─────────────
# Values are monthly revenue budgets per property
BUDGET_2026 = {
    "Sandalfoot": [
        394680.80, 469024.80, 550054.40, 369689.60,
        252362.40, 271476.80, 251369.60, 195699.20,
        160876.80, 207887.20, 214428.00, 281435.20,
    ],
    "Signal Inn": [
        164362.40, 210023.20, 225773.60, 147772.00,
        118719.20, 122458.40, 140344.80,  87899.20,
         46405.60,  73036.00,  68592.00, 100679.20,
    ],
    "GBB": [
        184947.20, 306651.20, 303221.60, 171528.80,
         85338.40, 112631.20, 122884.00,  65480.00,
         38009.60,  64680.00,  69324.00,  75524.00,
    ],
    "YCA": [
        250884.00, 290628.00, 333684.00, 209952.00,
         91432.80, 170674.56, 201032.64,  89640.00,
         59760.00, 104580.00, 104580.00, 134460.00,
    ],
    "Colony Inn": [
        150530.40, 203439.60, 266947.20, 188956.80,
        110160.00, 205632.00, 242208.00, 108000.00,
         72000.00, 126000.00, 126000.00, 162000.00,
    ],
    # Non-Resort is rent/non-STR revenue — not in KeyData, shown as budget-only
    "Non-Resort": [
        619146.40, 961272.00, 979237.60, 468624.80,
        157331.20, 185928.80, 187572.80,  86636.00,
         60847.20,  85866.40, 107206.40, 218600.80,
    ],
}

# Which months have passed (or are in progress) as of today
CURRENT_MONTH = TODAY.month   # 1-indexed

# Properties with KeyData group IDs (Resort Wide)
KEYDATA_PROPERTIES = [
    {"name": "Sandalfoot",  "group": [42553]},
    {"name": "Signal Inn",  "group": [32414]},
    {"name": "GBB",         "group": [30479]},
    {"name": "Colony Inn",  "group": [48143]},
    {"name": "YCA",         "group": [50606]},
    {"name": "Non-Resort",  "group": [51378, 51379]},
]

# ── Token ──────────────────────────────────────────────────────────────────────
if len(sys.argv) > 1:
    token = sys.argv[1].strip()
else:
    print("\nPaste your KeyData token (from the bookmarklet) and press Enter:")
    token = input("> ").strip()

if not token:
    print("No token provided. Exiting.")
    sys.exit(1)

headers = {
    "authorization": f"Bearer {token}",
    "content-type":  "application/json",
    "x-currency":    "usd",
    "x-date-culture": "en-US",
    "x-language-culture": "en-US",
    "origin":  "https://pm.keydatadashboard.com",
    "referer": "https://pm.keydatadashboard.com/"
}

# ── API helpers ────────────────────────────────────────────────────────────────
def make_pacing_body(groups):
    compare_dt = TODAY - timedelta(days=364)
    return {
        "page": "pacing-standard-view",
        "selections": {
            "marketIds": MARKET_IDS,
            "range": {
                "rangeType": "Season",
                "rangeSeasonId": PRIMARY_SEASON_ID,
                "range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T00:00:00"},
                "asOfDate": {
                    "asOfDateType": "Today",
                    "asOf": f"{TODAY.isoformat()}T00:00:00",
                    "summary": TODAY_STR
                }
            },
            "compareRange": {
                "rangeType": "Season",
                "rangeSeasonId": COMPARE_SEASON_ID,
                "range": {"start": "2025-01-01T00:00:00", "end": "2025-12-31T00:00:00"},
                "asOfDate": {
                    "asOfDateType": "TodayMinusOneYearSameDayOfWeek",
                    "asOf": f"{compare_dt.isoformat()}T00:00:00",
                    "summary": compare_dt.strftime("%-m/%-d/%Y")
                }
            },
            "kpi1": "ADR", "kpi2": "AvailableOccupancy",
            "kpi3": "NightsSold", "kpi4": "RecognizedUnitRevenue",
            "timeSeriesScale": "Month", "currencyCode": None
        },
        "filters": {
            "sleeps": None, "bedrooms": None, "propertyLocations": None,
            "propertyTypes": None, "amenities": None, "areas": None,
            "customGroups": groups,
            "unitGroupFilteringType": "Unique",
            "unitGroupFilteringDataSetNameType": "UsePropertyManagerName",
            "properties": [], "marketingSources": None, "managerType": None,
            "hostName": None, "rentalChannel": "All", "geoNameIds": []
        }
    }

def fetch(body):
    req = urllib.request.Request(
        "https://pm-api.keydatadashboard.com/api/views/pace/standard",
        data=json.dumps(body).encode(), headers=headers, method='POST'
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())['result']

def extract_monthly_revenue(result):
    """Returns (current_year_values, last_year_values) — each a list of 12 monthly
    revenue values (or None if no comparison data was present).
    Prefers RecognizedUnitRevenue; falls back to UnitRevenue if not present.
    Searches all kpi slots since the position varies by property/request.
    The comparison (last-year, same-day-of-week) series comes from the same
    request — make_pacing_body() already asks for it via compareRange."""
    preferred = ('RecognizedUnitRevenue', 'UnitRevenue')
    found = {t: None for t in preferred}
    found_ly = {t: None for t in preferred}
    for slot in ('kpi1', 'kpi2', 'kpi3', 'kpi4'):
        ds = result.get(slot, {}).get('timeSeries', {}).get('datasets', [])
        if not ds:
            continue
        kpi_type = ds[0].get('kpi', {}).get('type')
        if kpi_type in found:
            primary = next(d for d in ds if not d['isComparisonData'])
            values = list(primary['data'])
            while len(values) < 12:
                values.append(0.0)
            found[kpi_type] = [round(v, 2) for v in values[:12]]

            compare = next((d for d in ds if d['isComparisonData']), None)
            if compare:
                ly_values = list(compare['data'])
                while len(ly_values) < 12:
                    ly_values.append(0.0)
                found_ly[kpi_type] = [round(v, 2) for v in ly_values[:12]]
    for t in preferred:
        if found[t] is not None:
            return found[t], found_ly[t]
    raise ValueError("No revenue KPI found in response")

# ── Fetch actuals from KeyData ─────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  GCVR 2026 Budget vs Actuals (v2 — with YoY)  —  Generated {TODAY_STR}")
print(f"{'='*60}\n")

actuals = {}
actuals_ly = {}
for prop in KEYDATA_PROPERTIES:
    print(f"  Fetching {prop['name']}...", end=' ', flush=True)
    try:
        result = fetch(make_pacing_body(prop['group']))
        monthly, monthly_ly = extract_monthly_revenue(result)
        actuals[prop['name']] = monthly
        actuals_ly[prop['name']] = monthly_ly
        ytd = sum(monthly[:CURRENT_MONTH])
        print(f"YTD through {MONTHS[CURRENT_MONTH-1]}: ${ytd:,.0f}")
    except Exception as e:
        print(f"ERROR: {e}")
        actuals[prop['name']] = [0.0] * 12
        actuals_ly[prop['name']] = None


# ── Compute summary table ──────────────────────────────────────────────────────
def fmt(v):
    if v is None:
        return "N/A"
    return f"${v:,.0f}"

def pct(actual, budget):
    if actual is None or budget == 0:
        return "N/A"
    return f"{(actual/budget*100):.1f}%"

def var(actual, budget):
    if actual is None:
        return None
    return actual - budget

PROPERTY_ORDER = ["Sandalfoot", "Signal Inn", "GBB", "YCA", "Colony Inn", "Non-Resort"]

print(f"\n{'='*60}")
print(f"  YTD SUMMARY (Jan – {MONTHS[CURRENT_MONTH-1]} 2026)")
print(f"{'='*60}")
print(f"  {'Property':<16} {'Budget YTD':>12} {'Actual YTD':>12} {'Variance':>12} {'Attain':>8}")
print(f"  {'-'*16} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")

gcvr_budget_ytd = 0
gcvr_actual_ytd = 0

for prop_name in PROPERTY_ORDER:
    budget_months = BUDGET_2026[prop_name]
    actual_months = actuals.get(prop_name)
    budget_ytd = sum(budget_months[:CURRENT_MONTH])
    actual_ytd = sum(actual_months[:CURRENT_MONTH]) if actual_months else None
    v = var(actual_ytd, budget_ytd)
    gcvr_budget_ytd += budget_ytd
    if actual_ytd is not None:
        gcvr_actual_ytd += actual_ytd
    v_str = (f"+${v:,.0f}" if v and v >= 0 else f"-${abs(v):,.0f}") if v is not None else "N/A"
    print(f"  {prop_name:<16} {fmt(budget_ytd):>12} {fmt(actual_ytd):>12} {v_str:>12} {pct(actual_ytd, budget_ytd):>8}")

print(f"  {'='*52}")
gcvr_v = gcvr_actual_ytd - gcvr_budget_ytd
gcvr_v_str = f"+${gcvr_v:,.0f}" if gcvr_v >= 0 else f"-${abs(gcvr_v):,.0f}"
gcvr_pct = f"{gcvr_actual_ytd/gcvr_budget_ytd*100:.1f}%" if gcvr_budget_ytd else "N/A"
print(f"  {'GCVR TOTAL':<16} {fmt(gcvr_budget_ytd):>12} {fmt(gcvr_actual_ytd):>12} {gcvr_v_str:>12} {gcvr_pct:>8}")

# ── Month-by-month detail per property ────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  MONTHLY DETAIL — Revenue by Property")
print(f"{'='*60}")

for prop_name in PROPERTY_ORDER:
    budget_months = BUDGET_2026[prop_name]
    actual_months = actuals.get(prop_name)
    print(f"\n  {prop_name}")
    print(f"  {'Month':<6} {'Budget':>10} {'Actual':>10} {'Variance':>12} {'%':>7}  Status")
    print(f"  {'-'*6} {'-'*10} {'-'*10} {'-'*12} {'-'*7}  {'-'*10}")
    for i, month in enumerate(MONTHS):
        b = budget_months[i]
        if actual_months:
            a = actual_months[i]
            v = a - b
            v_str = (f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}")
            p_str = pct(a, b)
            if i + 1 < CURRENT_MONTH:
                status = "✓ Actual"
            elif i + 1 == CURRENT_MONTH:
                status = "~ Current"
            else:
                status = "  Future"
            a_str = fmt(a)
            if i + 1 > CURRENT_MONTH:
                status = "  Booked"
        else:
            a_str, v_str, p_str = "N/A", "", ""
            status = "No Data"
        print(f"  {month:<6} {fmt(b):>10} {a_str:>10} {v_str:>12} {p_str:>7}  {status}")

# ── Generate HTML report ───────────────────────────────────────────────────────
html_path = os.path.join(OUTPUT_FOLDER, f"budget_vs_actuals_v2_{REPORT_DATE}.html")

def html_var(v, show_pct=False, budget=None):
    if v is None:
        return '<td class="na">N/A</td>'
    if v > 0:
        cls = "pos"
        s = f"+${v:,.0f}"
    elif v < 0:
        cls = "neg"
        s = f"-${abs(v):,.0f}"
    else:
        cls = ""
        s = "$0"
    p = f'<small> ({v/budget*100:.1f}%)</small>' if (show_pct and budget) else ''
    return f'<td class="{cls}">{s}{p}</td>'

rows_html = ""
gcvr_b_ytd = 0
gcvr_a_ytd = 0

for prop_name in PROPERTY_ORDER:
    budget_months = BUDGET_2026[prop_name]
    actual_months = actuals.get(prop_name)
    b_ytd = sum(budget_months[:CURRENT_MONTH])
    a_ytd = sum(actual_months[:CURRENT_MONTH]) if actual_months else None
    v_ytd = (a_ytd - b_ytd) if a_ytd is not None else None
    p_ytd = f"{a_ytd/b_ytd*100:.1f}%" if (a_ytd is not None and b_ytd) else "N/A"
    gcvr_b_ytd += b_ytd
    if a_ytd is not None:
        gcvr_a_ytd += a_ytd
    cls_row = "no-data" if actual_months is None else ""
    rows_html += f"""
    <tr class="{cls_row}">
      <td class="prop">{prop_name}</td>
      <td>${b_ytd:,.0f}</td>
      <td>{"$"+f"{a_ytd:,.0f}" if a_ytd is not None else "N/A"}</td>
      {html_var(v_ytd)}
      <td>{p_ytd}</td>
    </tr>"""

gcvr_v = gcvr_a_ytd - gcvr_b_ytd
rows_html += f"""
    <tr class="total">
      <td class="prop">GCVR TOTAL</td>
      <td>${gcvr_b_ytd:,.0f}</td>
      <td>${gcvr_a_ytd:,.0f}</td>
      {html_var(gcvr_v)}
      <td>{gcvr_a_ytd/gcvr_b_ytd*100:.1f}%</td>
    </tr>"""

# Monthly detail tables
detail_html = ""
for prop_name in PROPERTY_ORDER:
    budget_months = BUDGET_2026[prop_name]
    actual_months = actuals.get(prop_name)
    month_rows = ""
    for i, month in enumerate(MONTHS):
        b = budget_months[i]
        if actual_months:
            a = actual_months[i]
            v = a - b
            if i + 1 < CURRENT_MONTH:
                status_cls, status_lbl = "actual", "Actual"
                a_cell = f"<td>${a:,.0f}</td>"
                v_cell = html_var(v, show_pct=True, budget=b)
            elif i + 1 == CURRENT_MONTH:
                status_cls, status_lbl = "current", "In Progress"
                a_cell = f'<td class="pacing">${a:,.0f}</td>'
                v_cell = html_var(v, show_pct=True, budget=b)
            else:
                status_cls, status_lbl = "future", "Pacing"
                a_cell = f'<td class="pacing dim">${a:,.0f} <small>est</small></td>'
                v_cell = "<td></td>"
        else:
            status_cls, status_lbl = "no-data", "No Data"
            a_cell = "<td class='na'>N/A</td>"
            v_cell = "<td></td>"
        month_rows += f"""
        <tr class="{status_cls}">
          <td>{month}</td>
          <td>${b:,.0f}</td>
          {a_cell}
          {v_cell}
          <td class="status-lbl">{status_lbl}</td>
        </tr>"""

    detail_html += f"""
    <div class="prop-section">
      <h3>{prop_name}</h3>
      <table class="detail-table">
        <thead><tr><th>Month</th><th>Budget</th><th>Actual / Pacing</th><th>Variance</th><th>Status</th></tr></thead>
        <tbody>{month_rows}</tbody>
      </table>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GCVR 2026 Budget vs Actuals — {TODAY_STR}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f0f2f5; color: #1a1a2e; padding: 24px; }}
  h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: 0.9rem; margin-bottom: 24px; }}
  .card {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 24px;
           box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
  h2 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; color: #1a1a2e;
        padding-bottom: 8px; border-bottom: 2px solid #e8eaf0; }}
  h3 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #2c3e50; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th {{ text-align: right; padding: 8px 12px; background: #f8f9fc;
        font-weight: 600; color: #555; border-bottom: 2px solid #e8eaf0; }}
  th:first-child {{ text-align: left; }}
  td {{ padding: 9px 12px; text-align: right; border-bottom: 1px solid #f0f2f5; }}
  td:first-child {{ text-align: left; }}
  td.prop {{ font-weight: 500; }}
  td.pos {{ color: #27ae60; font-weight: 600; }}
  td.neg {{ color: #e74c3c; font-weight: 600; }}
  td.na {{ color: #aaa; font-style: italic; }}
  td.pacing {{ color: #7f8c8d; }}
  td.dim {{ opacity: 0.6; }}
  tr.total td {{ font-weight: 700; background: #f8f9fc; border-top: 2px solid #e8eaf0; }}
  tr.no-data td {{ color: #aaa; }}
  tr.actual {{ background: white; }}
  tr.current {{ background: #fffde7; }}
  tr.future {{ background: #fafafa; color: #888; }}
  tr.future td.status-lbl {{ color: #aaa; }}
  td.status-lbl {{ font-size: 0.8rem; color: #888; }}
  .prop-section {{ margin-bottom: 28px; }}
  .detail-table th, .detail-table td {{ padding: 7px 12px; }}
  .legend {{ display: flex; gap: 20px; font-size: 0.8rem; color: #666;
             margin-bottom: 16px; align-items: center; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 4px; }}
  .note {{ font-size: 0.82rem; color: #888; margin-top: 12px; font-style: italic; }}
</style>
</head>
<body>
<h1>GCVR Portfolio — 2026 Budget vs Actuals</h1>
<div class="subtitle">Generated {TODAY_STR} &nbsp;·&nbsp; YTD through {MONTHS[CURRENT_MONTH-1]} 2026 &nbsp;·&nbsp; Revenue (RecognizedUnitRevenue)</div>

<div class="card">
  <h2>YTD Summary — Jan through {MONTHS[CURRENT_MONTH-1]}</h2>
  <table>
    <thead>
      <tr>
        <th>Property</th>
        <th>2026 Budget YTD</th>
        <th>Actual YTD</th>
        <th>Variance $</th>
        <th>Attainment %</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p class="note">* YCA and Non-Resort shown as budget-only; actuals require manual entry or KeyData group ID setup.<br>
     * Non-Resort Portfolio is rent/non-STR revenue — not tracked in KeyData.</p>
</div>

<div class="card">
  <h2>Monthly Detail by Property</h2>
  <div class="legend">
    <span><span class="legend-dot" style="background:#27ae60"></span>Positive variance (ahead of budget)</span>
    <span><span class="legend-dot" style="background:#e74c3c"></span>Negative variance (behind budget)</span>
    <span style="background:#fffde7;padding:2px 6px;border-radius:4px;">Current month (in progress)</span>
    <span style="color:#aaa">Future = pacing estimate</span>
  </div>
  {detail_html}
</div>

</body>
</html>"""

with open(html_path, 'w') as f:
    f.write(html)

# ── Patch dashboard_v2.html with fresh actuals + last-year comparison ─────────
DASHBOARD_PATH = os.path.join(OUTPUT_FOLDER, "dashboard_v2.html")

PROP_JS_NAMES = {
    "Sandalfoot":  "Sandalfoot",
    "Signal Inn":  "Signal Inn",
    "GBB":         "GBB",
    "Colony Inn":  "Colony Inn",
    "YCA":         "YCA",
    "Non-Resort":  "Non-Resort Portfolio",
}

def js_arr(vals):
    if vals is None:
        return '[null, null, null, null, null, null, null, null, null, null, null, null]'
    return '[' + ', '.join(str(round(v, 2)) for v in vals) + ']'

if os.path.exists(DASHBOARD_PATH):
    with open(DASHBOARD_PATH) as f:
        dash = f.read()

    for prop_name, js_name in PROP_JS_NAMES.items():
        monthly = actuals.get(prop_name)
        monthly_ly = actuals_ly.get(prop_name)
        if not monthly:
            continue
        # Match the actuals array for this unit in the JS rawData block
        pattern = (
            r'(unit:\s*"' + re.escape(js_name) + r'".*?actuals:\s*)\[[^\]]*\]'
        )
        replacement = r'\g<1>' + js_arr(monthly)
        dash, n = re.subn(pattern, replacement, dash, flags=re.DOTALL)
        if n:
            print(f"  dashboard_v2.html ← {prop_name} actuals patched")

        # Match the lastYear array for this unit in the JS rawData block
        ly_pattern = (
            r'(unit:\s*"' + re.escape(js_name) + r'".*?lastYear:\s*)\[[^\]]*\]'
        )
        ly_replacement = r'\g<1>' + js_arr(monthly_ly)
        dash, n_ly = re.subn(ly_pattern, ly_replacement, dash, flags=re.DOTALL)
        if n_ly:
            print(f"  dashboard_v2.html ← {prop_name} last-year patched")

    # Update GENERATED date, CURRENT_MONTH, and AS_OF_DATE (drives weeks-left math)
    dash = re.sub(r'const GENERATED\s*=\s*"[^"]*"',
                  f'const GENERATED = "{TODAY_TS}"', dash)
    dash = re.sub(r'const CURRENT_MONTH\s*=\s*\d+',
                  f'const CURRENT_MONTH = {CURRENT_MONTH}', dash)
    dash = re.sub(r'const AS_OF_DATE\s*=\s*"[^"]*"',
                  f'const AS_OF_DATE = "{REPORT_DATE}"', dash)

    with open(DASHBOARD_PATH, 'w') as f:
        f.write(dash)
    print(f"  dashboard_v2.html updated")

print(f"\n{'='*60}")
print(f"  Report saved: {html_path}")
print(f"  Dashboard (local preview only, not pushed to git): {DASHBOARD_PATH}")
print(f"{'='*60}\n")

import subprocess

subprocess.run(['open', DASHBOARD_PATH])
