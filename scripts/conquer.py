"""Split the cubes that a run_cubes.py pass left open, and solve the pieces, level by level.

For every cube i with status UNKNOWN in DIR/results.jsonl (the latest record per cube counts),
the cube's CNF (CNF + cube literals) goes to DIR/c{i}/cube.cnf, march_cu splits it into
DIR/c{i}/sub.icnf, check_cover.py proves that the sub-cubes leave nothing out of that cube
(LRAT, verified), and every sub-cube is solved with a streamed, verified LRAT proof and the
time limit. Sub-cubes still open are split again one level deeper, up to --levels; at the last
level they run without a time limit. A satisfiable cube stops the run.

Every UNSAT record must carry check = VERIFIED and every split cover = VERIFIED; summary.py
collects them.

Usage: python3 conquer.py CNF ICNF DIR [--workers W] [--timeout S] [--depth D] [--levels L]
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_cubes import read_cnf, read_cubes, solve_cube, arg  # noqa: E402

MARCH = os.path.join(HERE, "..", "tools", "CnC", "march_cu", "march_cu")


def latest(results_path):
    rs = {}
    if os.path.exists(results_path):
        with open(results_path) as fh:
            for line in fh:
                r = json.loads(line)
                rs[r["cube"]] = r
    return rs


def log(msg):
    print(msg, flush=True)


@lru_cache(maxsize=32)
def node_cnf(cube_cnf):
    return read_cnf(cube_cnf)


def solve(cube_cnf, cube, d, i, limit):
    # the node's CNF (3.6 MB) is read when its sub-cube starts, not held for every open node
    return solve_cube(*node_cnf(cube_cnf), cube, d, i, limit, True, True)


def split(node_dir, cnf_path, cube, depth):
    """Write the cube's CNF, split it with march_cu and verify the cover. Returns the paths."""
    os.makedirs(node_dir, exist_ok=True)
    nv, nc, body = read_cnf(cnf_path)
    cube_cnf = os.path.join(node_dir, "cube.cnf")
    if not os.path.exists(cube_cnf):
        with open(cube_cnf, "w") as fh:
            fh.write(f"p cnf {nv} {nc + len(cube)}\n")
            fh.write(body)
            for lit in cube:
                fh.write(f"{lit} 0\n")
    sub = os.path.join(node_dir, "sub.icnf")
    if not os.path.exists(sub):
        tmp = sub + ".tmp"
        with open(os.path.join(node_dir, "march.out"), "w") as out:
            subprocess.run(["nice", "-n", "5", MARCH, cube_cnf, "-d", str(depth), "-o", tmp],
                           stdout=out, stderr=subprocess.STDOUT)
        os.replace(tmp, sub)
    cover_out = os.path.join(node_dir, "cover.out")
    if not os.path.exists(cover_out):
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "check_cover.py"),
                            cube_cnf, sub, node_dir], capture_output=True, text=True)
        with open(cover_out, "w") as fh:
            fh.write(r.stdout)
        for f in ("cover.cnf", "cover.lrat"):
            p = os.path.join(node_dir, f)
            if os.path.exists(p) and "cover=VERIFIED" in r.stdout:
                os.unlink(p)
    return cube_cnf, sub


def main():
    cnf, icnf, top = sys.argv[1:4]
    workers = arg("--workers", 9, int)
    timeout = arg("--timeout", 900, int)
    depth = arg("--depth", 6, int)
    levels = arg("--levels", 3, int)

    # frontier: (parent cnf, cubes file, results dir) whose UNKNOWN cubes get split
    frontier = [(cnf, icnf, top)]
    for level in range(1, levels + 1):
        open_nodes = []
        for pcnf, picnf, pdir in frontier:
            cubes = read_cubes(picnf)
            for i, r in sorted(latest(os.path.join(pdir, "results.jsonl")).items()):
                if r["status"] == "SAT":
                    log(f"SAT cube {pdir} {i}: stop")
                    return
                if r["status"] == "UNKNOWN":
                    open_nodes.append((pcnf, cubes[i], os.path.join(pdir, f"c{i}")))
        if not open_nodes:
            log(f"level {level}: nothing open")
            break
        log(f"level {level}: splitting {len(open_nodes)} open cubes (depth {depth})")
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(split, d, p, c, depth): d for p, c, d in open_nodes}
            nodes = []
            for fut in as_completed(futs):
                cube_cnf, sub = fut.result()
                d = futs[fut]
                cov = open(os.path.join(d, "cover.out")).read().strip()
                log(f"  split {d}: {len(read_cubes(sub))} sub-cubes, {cov}")
                if "cover=VERIFIED" not in cov:
                    log(f"COVER NOT VERIFIED in {d}: stop")
                    return
                nodes.append((cube_cnf, sub, d))
        last = level == levels
        limit = 0 if last else timeout
        tasks = []
        for cube_cnf, sub, d in nodes:
            # on a restart, a cube that already ran out of at least this limit stays UNKNOWN
            done = {i for i, r in latest(os.path.join(d, "results.jsonl")).items()
                    if r["status"] in ("UNSAT", "SAT")
                    or (limit and r["status"] == "UNKNOWN" and r["secs"] >= limit)}
            for i, c in enumerate(read_cubes(sub)):
                if i not in done:
                    tasks.append((d, cube_cnf, c, i))
        log(f"level {level}: solving {len(tasks)} sub-cubes"
            f" ({f'limit {limit} s' if limit else 'no limit'})")
        files = {}
        sat = False
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(solve, cube_cnf, c, d, i, limit): d
                    for d, cube_cnf, c, i in tasks}
            for fut in as_completed(futs):
                d = futs[fut]
                rec = fut.result()
                if d not in files:
                    files[d] = open(os.path.join(d, "results.jsonl"), "a")
                files[d].write(json.dumps(rec) + "\n")
                files[d].flush()
                if rec["status"] == "SAT" or rec.get("check") == "FAILED":
                    log(f"!! {d} cube {rec['cube']}: {rec}")
                    sat = sat or rec["status"] == "SAT"
        for fh in files.values():
            fh.close()
        if sat:
            log("SAT found: stop")
            return
        frontier = nodes
        n_open = sum(1 for _, _, d in nodes
                     for r in latest(os.path.join(d, "results.jsonl")).values()
                     if r["status"] == "UNKNOWN")
        log(f"level {level}: done, {n_open} sub-cubes still open")
    log("finished")


if __name__ == "__main__":
    main()
