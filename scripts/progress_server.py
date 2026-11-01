"""Serve a live progress page for the 11-line case-B run (conquer.py), on 127.0.0.1 only.

GET / is progress.html; GET /status.json is read fresh from the results tree, the conquer log
and the running cadical processes on every request. Nothing is written.

Usage: python3 progress_server.py [--port 8765]
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run_cubes import read_cubes, arg  # noqa: E402

TOP = os.path.join(ROOT, "results", "cubes_k11B_lex_d8")
ICNF = os.path.join(ROOT, "build", "k11B_lex_d8.icnf")
LOG = os.path.join(ROOT, "results", "cubes_k11B_lex_d8.conquer.log")
PAGE = os.path.join(HERE, "progress.html")
LEVELS = 3

_cube_counts = {}


def n_cubes(path):
    m = os.path.getmtime(path)
    c = _cube_counts.get(path)
    if not c or c[0] != m:
        c = _cube_counts[path] = (m, len(read_cubes(path)))
    return c[1]


def latest(path):
    rs = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    rs[r["cube"]] = r
    return rs


def tally(rs):
    t = {"done": len(rs), "unsat": 0, "unknown": 0, "sat": 0, "failed": 0, "cpu": 0.0}
    for r in rs.values():
        t["cpu"] += r.get("secs", 0)
        if r["status"] == "SAT":
            t["sat"] += 1
        elif r["status"] == "UNKNOWN":
            t["unknown"] += 1
        elif r["status"] == "UNSAT" and r.get("check") == "VERIFIED":
            t["unsat"] += 1
        else:
            t["failed"] += 1
    return t


def read_log():
    lines = open(LOG).read().splitlines() if os.path.exists(LOG) else []
    order, phase, open_after = {}, {}, {}
    for ln in lines:
        m = re.match(r"\s*split (\S+):", ln)
        if m:
            order.setdefault(os.path.relpath(os.path.join(ROOT, m.group(1)), TOP), len(order))
        m = re.match(r"level (\d+): (splitting|solving)", ln)
        if m:
            phase[int(m.group(1))] = m.group(2)
        m = re.match(r"level (\d+): done, (\d+)", ln)
        if m:
            phase[int(m.group(1))] = "done"
            open_after[int(m.group(1))] = int(m.group(2))
        if re.match(r"level (\d+): nothing open", ln):
            phase[int(ln.split()[1].rstrip(":"))] = "skipped"
    alert = next((ln.strip() for ln in lines
                  if ln.startswith(("SAT", "!!", "COVER NOT VERIFIED"))), None)
    return order, phase, open_after, alert, bool(lines) and lines[-1] == "finished"


def etime_secs(s):
    days, _, rest = s.rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(days) if days else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def processes():
    # while the run is on the cloud server, sync_back.sh copies its process list here
    remote = TOP + ".remote_ps.txt"
    if os.path.exists(remote) and time.time() - os.path.getmtime(remote) < 1800:
        out = open(remote).read()
    else:
        out = subprocess.run(["ps", "-axo", "etime=,args="], capture_output=True, text=True).stdout
    workers, conquer = [], False
    for ln in out.splitlines():
        et, _, args = ln.strip().partition(" ")
        argv = args.split()
        if "scripts/conquer.py" in args and not argv[0].endswith(("zsh", "nice")):
            conquer = True
        if argv and argv[0] == "cadical":
            cnf = next((a for a in argv if a.endswith(".cnf") and "cubes_k11B_lex_d8/" in a), None)
            if cnf:
                rel = os.path.relpath(os.path.join(ROOT, cnf), TOP)
                limit = int(argv[argv.index("-t") + 1]) if "-t" in argv else 0
                workers.append({"node": os.path.dirname(rel),
                                "cube": int(re.search(r"cube(\d+)\.cnf$", rel).group(1)),
                                "secs": etime_secs(et.strip()), "limit": limit})
    workers.sort(key=lambda w: -w["secs"])
    return workers, conquer


def level_status(level, order, phase, open_after):
    pattern = os.path.join(TOP, *["c*"] * level, "sub.icnf")
    nodes = []
    for sub in glob.glob(pattern):
        d = os.path.dirname(sub)
        rel = os.path.relpath(d, TOP)
        if not all(re.fullmatch(r"c\d+", p) for p in rel.split(os.sep)):
            continue
        res = os.path.join(d, "results.jsonl")
        n = n_cubes(sub)
        t = tally(latest(res))
        if t["sat"]:
            state = "sat"
        elif t["failed"]:
            state = "failed"
        elif t["done"] == 0:
            state = "todo"
        elif t["done"] < n:
            state = "running"
        else:
            state = "open" if t["unknown"] else "closed"
        nodes.append({"name": rel, "n": n, "state": state, "t": t,
                      "mtime": os.path.getmtime(res) if os.path.exists(res) else None})
    nodes.sort(key=lambda x: (order.get(x["name"], 10 ** 6), x["name"]))
    tot = {k: sum(x["t"][k] for x in nodes) for k in ("done", "unsat", "unknown", "sat", "failed", "cpu")}
    total = sum(x["n"] for x in nodes)

    # Rough rate: the last completed nodes of this level, in the order they finished.
    ends = sorted(x["mtime"] for x in nodes if x["state"] in ("closed", "open") and x["mtime"])[-8:]
    eta = rate = None
    if len(ends) >= 4 and ends[-1] > ends[0]:
        rate = (len(ends) - 1) / (ends[-1] - ends[0])
        remaining = sum(1 - x["t"]["done"] / x["n"] for x in nodes if x["n"])
        eta = remaining / rate
    return {"level": level, "phase": phase.get(level, "waiting"), "total": total,
            "nodes": [{"name": x["name"], "n": x["n"], "done": x["t"]["done"],
                       "unknown": x["t"]["unknown"], "state": x["state"]} for x in nodes],
            "open_after": open_after.get(level), "eta_s": eta,
            "nodes_per_h": rate * 3600 if rate else None, **tot}


def status():
    order, phase, open_after, alert, finished = read_log()
    first = tally(latest(os.path.join(TOP, "results.jsonl")))
    first["total"] = n_cubes(ICNF)
    levels = [level_status(lv, order, phase, open_after) for lv in range(1, LEVELS + 1)]
    workers, conquer = processes()
    results = glob.glob(os.path.join(TOP, "**", "results.jsonl"), recursive=True)
    if not alert and (first["sat"] or any(lv["sat"] for lv in levels)):
        alert = "SAT"
    if not alert and any(lv["failed"] for lv in levels):
        alert = "Bir sertifika denetimden geçmedi"
    return {"now": time.time(), "running": conquer, "finished": finished, "alert": alert,
            "first": first, "levels": levels, "workers": workers,
            "last_result": max((os.path.getmtime(p) for p in results), default=None),
            "cpu_h": (first["cpu"] + sum(lv["cpu"] for lv in levels)) / 3600}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status.json":
            body, ctype = json.dumps(status()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = open(PAGE, "rb").read(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = arg("--port", 8765, int)
    print(f"http://127.0.0.1:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
