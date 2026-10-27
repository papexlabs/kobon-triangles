"""Check a cube-and-conquer tree made by run_cubes.py and conquer.py.

A cube is closed when its latest record is UNSAT with check = VERIFIED, or when it is UNKNOWN,
its split directory c{i} has cover=VERIFIED, and every sub-cube is closed in turn. The top split
needs its own cover file (check_cover.py output) passed as COVER.

Usage: python3 summary.py ICNF DIR COVER_OUT
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_cubes import read_cubes  # noqa: E402


def latest(d):
    rs = {}
    p = os.path.join(d, "results.jsonl")
    if os.path.exists(p):
        for line in open(p):
            r = json.loads(line)
            rs[r["cube"]] = r
    return rs


def walk(icnf, d, stats, depth=0):
    """Returns True when every cube of icnf (results in d) is closed."""
    n = len(read_cubes(icnf))
    rs = latest(d)
    ok = True
    for i in range(n):
        r = rs.get(i)
        if r and r["status"] == "UNSAT" and r.get("check") == "VERIFIED":
            stats["verified"] += 1
            stats["cpu"] += r["secs"]
            continue
        if r and r["status"] == "SAT":
            stats["sat"].append((d, i))
            ok = False
            continue
        sub = os.path.join(d, f"c{i}")
        cov = os.path.join(sub, "cover.out")
        if r and r["status"] == "UNKNOWN" and os.path.exists(cov) \
                and "cover=VERIFIED" in open(cov).read():
            stats["cpu"] += r["secs"]
            stats["splits"] += 1
            if walk(os.path.join(sub, "sub.icnf"), sub, stats, depth + 1):
                continue
        stats["open"].append((d, i, r["status"] if r else "not run"))
        ok = False
    return ok


def main():
    icnf, d, cover = sys.argv[1:4]
    stats = {"verified": 0, "splits": 0, "cpu": 0.0, "open": [], "sat": []}
    top_cover = "cover=VERIFIED" in open(cover).read()
    closed = walk(icnf, d, stats) and top_cover
    print(f"top cover: {'VERIFIED' if top_cover else 'MISSING'}")
    print(f"verified UNSAT leaves: {stats['verified']}, splits: {stats['splits']}, "
          f"solver time: {stats['cpu'] / 3600:.1f} h")
    print(f"open: {len(stats['open'])} {stats['open'][:10]}")
    print(f"SAT: {stats['sat']}")
    print("ALL CLOSED: the CNF is unsatisfiable" if closed and not stats["sat"] else "not closed")


if __name__ == "__main__":
    main()
