"""Stop conquer's direct run of a cube once its split subtree is closed (summary.py rules).

Run from the repository root: python3 -I scripts/close_watch.py NODE_DIR:INDEX [...]
Exits when every target has a record from conquer (UNSAT, or UNKNOWN after being stopped)."""
import json, os, signal, sys, time
sys.path.insert(0, "scripts")
import summary

def log(m): print(time.strftime("%F %T"), "close_watch:", m, flush=True)

def rec(d, i):
    rs = {}
    for line in open(os.path.join(d, "results.jsonl")):
        try:
            r = json.loads(line); rs[r["cube"]] = r
        except ValueError:
            pass
    return rs.get(i)

def pids(path):
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                argv = open(f"/proc/{p}/cmdline", "rb").read().split(b"\0")
            except OSError:
                continue
            if argv and os.path.basename(argv[0]) == b"cadical" and path.encode() in argv[1:]:
                out.append(int(p))
    return out

targets = [(s.rsplit(":", 1)[0].rstrip("/"), int(s.rsplit(":", 1)[1])) for s in sys.argv[1:]]
stopped = set()
while True:
    left = 0
    for d, i in targets:
        r = rec(d, i)
        if r is not None:
            continue
        left += 1
        if (d, i) in stopped:
            continue
        sub = os.path.join(d, f"c{i}")
        cov = os.path.join(sub, "cover.out")
        try:
            ok = os.path.exists(cov) and "cover=VERIFIED" in open(cov).read() and \
                summary.walk(os.path.join(sub, "sub.icnf"), sub,
                             {"verified": 0, "cpu": 0, "splits": 0, "sat": [], "open": []})
        except (ValueError, KeyError):
            ok = False
        if ok:
            ps = pids(os.path.join(d, f"cube{i}.cnf"))
            log(f"{d} cube {i}: split subtree closed; stopping direct run {ps}")
            for pid in ps:
                os.kill(pid, signal.SIGTERM)
            stopped.add((d, i))
    if left == 0:
        log("all targets have a conquer record: exit")
        break
    time.sleep(60)
