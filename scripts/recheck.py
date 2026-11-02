"""Re-check any part of a cube-and-conquer tree from the published files.

The formula of a node is the top CNF with the cube literals on its path appended as unit clauses,
exactly as conquer.split wrote it. For each selected leaf, the leaf formula (node formula plus the
leaf's cube) is solved again by CaDiCaL with its LRAT proof streamed into lrat-check. With
--covers, the cover of every split on the selected paths is checked again (check_cover.py: node
formula plus the negations of all its cubes must be refuted with a checked LRAT proof).
The tree is walked with the closure rule of summary.py, so only leaves the proof relies on are
selected.

Usage, from the repository root:
  python3 -I scripts/recheck.py CNF ICNF TREE [--sample N] [--seed S] [--node PATH]
                                [--max-secs X] [--covers] [--workers W]
    --sample N    re-solve N leaves chosen at random (default 20; 0 = all selected leaves)
    --node PATH   only leaves below PATH, a node directory relative to TREE (e.g. c201/c63/c15)
    --max-secs X  only leaves whose recorded solve time is at most X seconds
    --covers      also re-check the covers of the splits on the selected leaves' paths
Example (case B, 11 lines):
  python3 -I scripts/recheck.py build/k11_33_caseB.lex.cnf build/k11B_lex_d8.icnf \\
      results/cubes_k11B_lex_d8 --sample 50 --max-secs 120 --covers
Exit status 0 only if every re-check gives UNSAT with lrat-check VERIFIED.
"""

import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_cubes import read_cnf, read_cubes, solve_cube, arg  # noqa: E402
from summary import latest  # noqa: E402


def leaves(icnf, d, path, out, splits):
    """Collect the leaves the closure rule uses: (path of (dir, index, cube), recorded secs)."""
    cubes = read_cubes(icnf)
    rs = latest(d)
    for i, cube in enumerate(cubes):
        r = rs.get(i)
        step = path + [(d, i, cube)]
        if r and r["status"] == "UNSAT" and r.get("check") == "VERIFIED":
            out.append((step, r["secs"]))
            continue
        sub = os.path.join(d, f"c{i}")
        cov = os.path.join(sub, "cover.out")
        if r and r["status"] == "UNKNOWN" and os.path.exists(cov) \
                and "cover=VERIFIED" in open(cov).read():
            splits[sub] = step
            leaves(os.path.join(sub, "sub.icnf"), sub, step, out, splits)
        else:
            raise SystemExit(f"open cube in the tree: {d} cube {i} ({r})")


def node_formula(top, path):
    """Top CNF plus the units of every cube on the path."""
    nv, nc, body = top
    units = [lit for _, _, cube in path for lit in cube]
    return nv, nc + len(units), body + "".join(f"{lit} 0\n" for lit in units)


def main():
    cnf, icnf, tree = sys.argv[1:4]
    sample = arg("--sample", 20, int)
    seed = arg("--seed", 1, int)
    node = arg("--node", "", str).strip("/")
    max_secs = arg("--max-secs", 0.0, float)
    workers = arg("--workers", os.cpu_count() or 4, int)
    covers = "--covers" in sys.argv

    top = read_cnf(cnf)
    found, splits = [], {}
    leaves(icnf, tree, [], found, splits)
    print(f"tree: {len(found)} leaves, {len(splits)} splits below the top split", flush=True)
    want = os.path.normpath(os.path.join(tree, node)) if node else None
    pick = [(p, s) for p, s in found
            if (not want or os.path.normpath(p[-1][0]) == want
                or os.path.normpath(p[-1][0]).startswith(want + os.sep))
            and (not max_secs or s <= max_secs)]
    if sample and len(pick) > sample:
        pick = random.Random(seed).sample(pick, sample)
    print(f"re-solving {len(pick)} leaves with {workers} workers", flush=True)

    tmp = tempfile.mkdtemp(prefix="kobon-recheck-")
    jobs = []
    for k, (p, secs) in enumerate(pick):
        jobs.append(("leaf", k, p, secs))
    if covers:
        jobs.append(("cover", "top", [], None))
        dirs = {os.path.join(d, f"c{i}") for p, _ in pick for d, i, _ in p[:-1]}
        for k, sub in enumerate(sorted(dirs)):
            jobs.append(("cover", k, splits[sub], sub))

    def run(job):
        kind, k, p, extra = job
        work = os.path.join(tmp, f"{kind}{k}")
        os.makedirs(work)
        try:
            if kind == "leaf":
                nv, nc, body = node_formula(top, p[:-1])
                rec = solve_cube(nv, nc, body, p[-1][2], work, 0, 0, True, True)
                ok = rec["status"] == "UNSAT" and rec.get("check") == "VERIFIED"
                where = f"{p[-1][0]} cube {p[-1][1]}"
                return ok, f"{where}: {rec['status']} {rec.get('check')} {rec['secs']} s" \
                           f" (recorded {extra} s)"
            nv, nc, body = node_formula(top, p)
            path = os.path.join(work, "node.cnf")
            with open(path, "w") as fh:
                fh.write(f"p cnf {nv} {nc}\n")
                fh.write(body)
            cubes = os.path.join(extra, "sub.icnf") if extra else icnf
            r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_cover.py"),
                                path, cubes, work],
                               capture_output=True, text=True)
            ok = "cover=VERIFIED" in r.stdout
            return ok, f"cover {extra or 'top split'}: {r.stdout.strip()}"
        finally:
            shutil.rmtree(work, ignore_errors=True)

    bad = 0
    with ThreadPoolExecutor(workers) as ex:
        for fut in as_completed([ex.submit(run, j) for j in jobs]):
            try:
                ok, msg = fut.result()
            except Exception as e:  # report and count, never stop silently
                ok, msg = False, f"error: {e!r}"
            bad += not ok
            print(("ok   " if ok else "FAIL ") + msg, flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(jobs) - bad} of {len(jobs)} re-checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
