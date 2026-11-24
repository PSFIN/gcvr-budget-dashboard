#!/usr/bin/env python3
"""Saves unit edits made in dashboard Version 2, for everyone.

Listens on 127.0.0.1 only. Caddy forwards https://budget.choosegulfcoast.com/v2/api/* to it.
Writes /home/ubuntu/budget-data/unit_settings.json (the file build_dashboard.py reads), keeps a copy of every
previous version and a log of who changed what, then rebuilds both pages.

  GET  /v2/api/status   {"enabled": bool, "version": n, "rebuilding": bool}      (public, no secrets)
  POST /v2/api/save     {"code", "by", "id", "changes": {p,c,s,t,tm,rg}}         (needs the edit code)
  POST /v2/api/reset    {"code", "by", "id"}   removes a unit's published settings (needs the edit code)

The edit code is the single line in /home/ubuntu/budget-data/edit_code. Without that file editing is disabled and
the page falls back to edits kept in the visitor's own browser. Nothing here touches Streamline or the budgets.
"""
import fcntl
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.environ.get("DATA_DIR", "/home/ubuntu/budget-data")
SETTINGS = os.path.join(DATA, "unit_settings.json")
CODE_FILE = os.path.join(DATA, "edit_code")
LOG_FILE = os.path.join(DATA, "unit_settings_log.jsonl")
HISTORY = os.path.join(DATA, "settings_history")
REBUILD = os.environ.get("REBUILD_CMD", "/home/ubuntu/budget-dashboard/deploy/rebuild.sh")
PORT = int(os.environ.get("PORT", "8010"))
MAX_BODY = 20_000
KEEP_HISTORY = 300

PROPS = {"Non-Resort", "Island Vacations", "Sandalfoot", "Signal Inn", "GBB", "YCBR", "Colony Inn", "Not in any property"}
CATS = {"Resort", "Non-Resort", "Unclassified"}
TAGS = {"", "Seasonal", "Luxury"}
TEAMS = {"", "Dave", "Jessica"}
REGIONS = {"", "North", "South", "Central"}
SUB_OK = re.compile(r"^[A-Za-z0-9 ()/&.,'+\-]{0,40}$")

_lock = threading.RLock()
_rb = {"worker": False, "dirty": False, "running": False}


def read_code():
    try:
        return open(CODE_FILE).read().strip()
    except OSError:
        return ""


def load():
    try:
        d = json.load(open(SETTINGS))
        d.setdefault("units", {})
        d["version"] = int(d.get("version", 0))
        return d
    except (OSError, ValueError):
        return {"version": 0, "units": {}}


def clean(changes):
    """Returns (validated dict, error message)."""
    out = {}
    for k, v in (changes or {}).items():
        if k not in ("p", "c", "s", "t", "tm", "rg"):
            continue                                    # ignore unknown keys (such as the unit name)
        v = "" if v is None else str(v).strip()
        ok = {"p": v in PROPS, "c": v in CATS, "t": v in TAGS, "tm": v in TEAMS, "rg": v in REGIONS,
              "s": bool(SUB_OK.match(v))}[k]
        if not ok:
            return None, f"'{v}' is not allowed for {k}"
        out[k] = v
    return out, ""


def write_settings(data):
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".unit_settings.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SETTINGS)


def backup_previous():
    if not os.path.exists(SETTINGS):
        return
    os.makedirs(HISTORY, mode=0o700, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    with open(SETTINGS) as src, open(os.path.join(HISTORY, f"unit_settings-{stamp}.json"), "w") as dst:
        dst.write(src.read())
    old = sorted(os.listdir(HISTORY))
    for name in old[:-KEEP_HISTORY]:
        try:
            os.remove(os.path.join(HISTORY, name))
        except OSError:
            pass


def log(entry):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    os.chmod(LOG_FILE, 0o600)


def apply(op, uid, changes, by, ip):
    """Merge (save) or remove (reset) one unit's settings. Returns the new version."""
    with _lock:
        lockf = open(os.path.join(DATA, ".unit_settings.lock"), "w")
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            data = load()
            before = dict(data["units"].get(str(uid), {}))
            backup_previous()
            if op == "reset":
                data["units"].pop(str(uid), None)
            else:
                data["units"].setdefault(str(uid), {}).update(changes)
            data["version"] += 1
            write_settings(data)
            log({"ts": datetime.now().isoformat(timespec="seconds"), "by": by, "ip": ip, "op": op, "id": uid,
                 "before": before, "after": data["units"].get(str(uid), {}), "version": data["version"]})
            return data["version"]
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
            lockf.close()


def trigger_rebuild():
    with _lock:
        _rb["dirty"] = True
        if _rb["worker"]:
            return
        _rb["worker"] = True
    threading.Thread(target=_rebuild_worker, daemon=True).start()


def _rebuild_worker():
    while True:
        time.sleep(2)                                    # let quick successive saves share one rebuild
        with _lock:
            if not _rb["dirty"]:
                _rb["worker"] = False
                _rb["running"] = False
                return
            _rb["dirty"] = False
            _rb["running"] = True
        try:
            r = subprocess.run([REBUILD], capture_output=True, text=True, timeout=300)
            if r.returncode:
                print("rebuild failed:", (r.stderr or r.stdout)[-400:], file=sys.stderr, flush=True)
        except Exception as e:                           # a failed rebuild must never stop the service
            print("rebuild error:", e, file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "unit-settings"

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/").endswith("/api/status"):
            with _lock:
                busy = _rb["dirty"] or _rb["running"]
            return self.reply(200, {"ok": True, "enabled": bool(read_code()), "version": load()["version"], "rebuilding": busy})
        self.reply(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        route = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if route not in ("save", "reset"):
            return self.reply(404, {"ok": False, "error": "not found"})
        code = read_code()
        if not code:
            return self.reply(503, {"ok": False, "error": "editing is not set up on the server"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_BODY:
                return self.reply(413, {"ok": False, "error": "request too large"})
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):
            return self.reply(400, {"ok": False, "error": "could not read the request"})
        if not hmac.compare_digest(str(req.get("code", "")).encode(), code.encode()):
            time.sleep(1)                                # slows down guessing
            return self.reply(403, {"ok": False, "error": "wrong edit code"})
        try:
            uid = int(req.get("id"))
        except (TypeError, ValueError):
            return self.reply(400, {"ok": False, "error": "missing unit id"})
        by = re.sub(r"[^A-Za-z0-9 .'_@-]", "", str(req.get("by", "")))[:40] or "unknown"
        changes = {}
        if route == "save":
            changes, err = clean(req.get("changes"))
            if err:
                return self.reply(400, {"ok": False, "error": err})
            if not changes:
                return self.reply(400, {"ok": False, "error": "nothing to change"})
        version = apply(route, uid, changes, by, self.ip())
        trigger_rebuild()
        self.reply(200, {"ok": True, "version": version, "rebuilding": True})


def main():
    os.makedirs(DATA, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"unit settings service on 127.0.0.1:{PORT}, data in {DATA}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
