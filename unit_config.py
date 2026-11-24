"""Unit configuration for dashboard Version 2.

Turns the Streamline data, the custom groups and (optionally) the private Sales Master Matrix
into one row per unit: property, category, subcategory, tag, team, plus its monthly revenue.

  Category     Resort (Sandalfoot, Signal Inn, GBB, YCBR, Colony Inn) or Non-Resort
               (Non-Resort and Island Vacations). Units in no property use the Streamline
               portfolio type (the first words of the unit's condo type name).
  Subcategory  the "Restriction Class" column of the Master Matrix (30x12, 7 Min, NR With Pool...)
  Tag          Luxury (Matrix account manager "... LUXURY") or Seasonal (Matrix "VR or Seasonal");
               falls back to the Streamline portfolio type, then the KeyData groups
  Team         Dave or Jessica, from the Matrix account manager, else the KeyData groups

The Master Matrix is private (owner contracts, cancellation policies): it lives next to the
budgets on the server and is never committed. Without it Version 2 still works; the subcategory
is then empty. Only these fields reach the page: name, id, property, category, subcategory, tag,
team, region, status, onboard date and the monthly revenue.
"""
import csv
import difflib
import json
import os
import re
import sqlite3
from collections import defaultdict

DISPLAY = {"YCA": "YCBR", "Non-Resort": "Non-Resort"}           # property name shown on the page
RESORT_PROPS = {"Sandalfoot", "Signal Inn", "GBB", "YCBR", "Colony Inn"}
NONRESORT_PROPS = {"Non-Resort", "Island Vacations"}
RESORT_PORTFOLIOS = {"Sandalfoot", "GBB", "Colony Inn", "YCBR", "Signal Inn"}
UNASSIGNED = "Not in any property"


# ── Master Matrix ─────────────────────────────────────────────────────────────
def _squash(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def matrix_key(name):
    """Normalises a unit name so the Matrix and Streamline spellings meet."""
    s = (name or "").replace("\xa0", " ").lower().strip()
    s = re.sub(r"\*+.*?\*+", "", s)                      # ** LIVE **
    s = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}", "", s)        # dates typed into the name
    s = re.sub(r"\(.*?\)", "", s)
    m = re.match(r"^gulf (?:&|and) bay(?: bayside)?\s*-?\s*(\d{4})", s)
    if m:
        return "gb" + m.group(1)
    m = re.match(r"^signal inn\s*-?\s*(?:unit)?\s*(\d+)", s)
    if m:
        return "si" + m.group(1).zfill(2)
    m = re.match(r"^ycbr\s*(\d+)", s)
    if m:
        return "ycbr" + m.group(1).zfill(2)
    s = re.sub(r"\s+/\s+.*$", "", s)
    s = re.sub(r"\s+-\s+(calusa|wellen park)\s*$", "", s)
    return re.sub(r"[^a-z0-9]", "", s.replace("&", "and"))


def _unz(key):
    return key[1:] if key.startswith("z") else key


def load_matrix(path):
    """Returns a list of dicts (one per Matrix row), or [] when there is no file."""
    if not path or not os.path.exists(path):
        return []
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    head = [_squash(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if r and _squash(r[0]):
            out.append({head[i]: _squash(r[i]) for i in range(min(len(head), len(r))) if head[i]})
    return out


def _col(row, *starts):
    for s in starts:
        for k, v in row.items():
            if k.lower().startswith(s.lower()):
                return v
    return ""


class MatrixIndex:
    def __init__(self, rows):
        self.rows = rows
        self.by_key = {}
        for r in rows:
            self.by_key.setdefault(matrix_key(_col(r, "Unit Name")), r)
        self.used = set()

    def find(self, name):
        k = matrix_key(name)
        hit = self.by_key.get(k)
        if hit is None:
            for mk, r in self.by_key.items():
                if _unz(mk) == _unz(k):
                    hit = r
                    break
        if hit is None:
            close = difflib.get_close_matches(k, list(self.by_key), n=1, cutoff=0.86)
            hit = self.by_key[close[0]] if close else None
        if hit is not None:
            self.used.add(id(hit))
        return hit


def clean_class(s):
    s = _squash(s)
    return "NR With Pool" if s.lower() == "nr with pool" else s


def team_of(text):
    t = (text or "").lower()
    return "Dave" if t.startswith("dave") else "Jessica" if t.startswith("jessica") else ""


def tag_of(text):
    t = (text or "").lower()
    return "Luxury" if t.startswith("luxury") else ("Seasonal" if t.startswith("seasonal") else "")


# ── Published unit settings (private file, applied for everyone) ───────────────
SETTING_FIELDS = ("p", "c", "s", "t", "tm", "rg")


def load_settings(path):
    """Optional unit_settings.json: {"units": {"<unit id>": {"p": property, "c": category, "s": subcategory,
    "t": tag, "tm": Dave/Jessica, "rg": region}}}. Only the fields present are changed. Returns {id: fields}."""
    if not path or not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
        raw = data.get("units") or {}
        out = {}
        for k, v in raw.items():
            fields = {f: str(v[f]) for f in SETTING_FIELDS if f in v}
            if fields:
                out[int(k)] = fields
        return out
    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"{path} is not valid ({e})")


# ── Monthly revenue per unit (same rules as the property totals) ───────────────
def unit_monthly(bookings, year, asof=None):
    """uid -> 12 monthly totals. Whole rent in the check-in month; 'asof' = created on/before it."""
    out = defaultdict(lambda: [0.0] * 12)
    for uid, start, created, rent, _detail in bookings:
        if start.year != year or (asof and created > asof):
            continue
        out[uid][start.month - 1] += rent
    return out


# ── The unit list ─────────────────────────────────────────────────────────────
def build_units(pacing_dir, units_by_prop, bookings, year, ly_asof, matrix_path=None, settings=None):
    """Returns (units, info). units = list of dicts for the page; info = counts for Settings."""
    con = sqlite3.connect(f"file:{os.path.join(pacing_dir, 'pacing.db')}?mode=ro", uri=True)
    active = {r[0]: r for r in con.execute(
        "select id, name, status_name, creation_date, condo_type_name from units")}
    res_name, res_type = {}, {}
    for uid, un, ct in con.execute("select unit_id, unit_name, condo_type_name from reservations"):
        if un:
            res_name[uid] = un
        if ct:
            res_type[uid] = ct
    con.close()

    groups = {k: set(v) for k, v in json.load(open(os.path.join(pacing_dir, "custom_groups.json"))).items()}
    dave = groups.get("Dave", set()) | groups.get("Dave [Central]", set()) | groups.get("Dave(ALL) - Short Stays", set())
    jess = groups.get("Jessica", set()) | groups.get("Jessica(ALL)- Short Stays", set())
    g_lux, g_sea = groups.get("LUXURY Portfolio", set()), groups.get("Seasonal", set())

    matrix_rows = load_matrix(matrix_path)
    mx = MatrixIndex(matrix_rows)

    cur = unit_monthly(bookings, year)
    ly = unit_monthly(bookings, year - 1, ly_asof)

    prop_of = {}
    for prop, ids in units_by_prop.items():
        for uid in ids:
            prop_of.setdefault(uid, DISPLAY.get(prop, prop))

    ids = set(active) | set(prop_of) | set(cur) | set(ly)
    out = []
    for uid in ids:
        is_active = uid in active
        if not is_active and uid not in prop_of and uid not in cur and uid not in ly:
            continue
        name = (active[uid][1] if is_active else None) or res_name.get(uid) or f"unit {uid}"
        ctn = (active[uid][4] if is_active else None) or res_type.get(uid) or ""
        portfolio = ctn[:-len(name)].strip() if ctn.endswith(name) and len(ctn) > len(name) else ""
        prop = prop_of.get(uid, UNASSIGNED)
        if prop in RESORT_PROPS:
            cat = "Resort"
        elif prop in NONRESORT_PROPS:
            cat = "Non-Resort"
        else:
            cat = "Resort" if portfolio in RESORT_PORTFOLIOS else ("Non-Resort" if portfolio else "Unclassified")
        m = mx.find(name) if matrix_rows else None
        mgr = _col(m, "Account Manager") if m else ""
        sub = clean_class(_col(m, "Restriction Class")) if m else ""
        vr = _col(m, "VR or Seasonal") if m else ""
        if m:
            tag = "Luxury" if "luxury" in mgr.lower() else ("Seasonal" if vr.lower() == "seasonal" else "")
        else:
            tag = tag_of(portfolio) or tag_of(ctn) or ("Luxury" if uid in g_lux else "Seasonal" if uid in g_sea else "")
        team = team_of(mgr) if m else ""
        if not team:
            team = "Dave" if uid in dave else "Jessica" if uid in jess else ""
        row = {
            "id": uid, "n": name, "p": prop, "c": cat, "s": sub, "t": tag, "tm": team,
            "rg": _col(m, "Region") if m else "", "on": _col(m, "Date Onboard") if m else "",
            "mx": 1 if m else 0, "pf": portfolio,
            "st": "Active" if is_active else "Retired",
            "a": [round(v, 2) for v in cur.get(uid, [0.0] * 12)],
            "l": [round(v, 2) for v in ly.get(uid, [0.0] * 12)],
        }
        if settings and uid in settings:                  # published settings win over everything computed above
            row.update(settings[uid])
            row["pub"] = 1
        out.append(row)
    order = ["GBB", "Colony Inn", "Signal Inn", "YCBR", "Sandalfoot", "Island Vacations", "Non-Resort", UNASSIGNED]
    out.sort(key=lambda u: (order.index(u["p"]) if u["p"] in order else 99, u["n"].lower()))
    info = {"matrixLoaded": bool(matrix_rows), "matrixRows": len(matrix_rows),
            "matrixMatched": sum(1 for u in out if u["mx"]),
            "settingsApplied": sum(1 for u in out if u.get("pub")),
            "matrixUnmatched": [_col(r, "Unit Name") for r in matrix_rows if id(r) not in mx.used][:40]}
    return out, info


def budgets_for_page(budgets):
    """Budget arrays keyed by the names the page shows."""
    return {DISPLAY.get(p, p): [round(float(x), 2) for x in v] for p, v in budgets.items()}


def js_json(obj):
    """JSON that is safe inside an inline <script>."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
