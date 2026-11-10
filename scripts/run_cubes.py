"""Solve the cubes of a cube-and-conquer split, one CaDiCaL process per cube.

Each cube is the CNF plus the cube's literals as unit clauses. Results go to OUTDIR/results.jsonl
(one line per cube: index, status, seconds); cubes already in that file are skipped, so the
run can be stopped and restarted. With --proof --check, CaDiCaL writes a text LRAT proof into a
named pipe that lrat-check reads at the same time, so proofs never reach the disk; the result
line records VERIFIED or FAILED. With --proof alone the proof is kept.

The checker is checker/lrat-check, built from checker/lrat-check.c (drat-trim's lrat-check with
the empty-clause fix, see checker/README.md); the environment variable LRAT_CHECK names another
binary. The runs of 27 October to 2 November 2026 used the unpatched tools/drat-trim/lrat-check.

Usage: python3 run_cubes.py CNF ICNF OUTDIR [--workers W] [--sample N] [--seed S]
                            [--timeout SECONDS] [--proof] [--check]
"""

import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
LRAT_CHECK = os.environ.get("LRAT_CHECK") or os.path.join(HERE, "..", "checker", "lrat-check")


def lrat_verdict(returncode, output):
    """VERIFIED only if lrat-check exited 0, printed the line 'c VERIFIED' and printed neither
    'FAILED' nor 'NOT VERIFIED'."""
    ok = (returncode == 0
          and any(line.strip() == "c VERIFIED" for line in output.splitlines())
          and "FAILED" not in output
          and "NOT VERIFIED" not in output)
    return "VERIFIED" if ok else "FAILED"


def read_cnf(path):
    with open(path) as fh:
        header = fh.readline().split()
        assert header[:2] == ["p", "cnf"], header
        body = fh.read()
    return int(header[2]), int(header[3]), body


def read_cubes(path):
    cubes = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("a "):
                lits = [int(x) for x in line.split()[1:]]
                assert lits[-1] == 0
                cubes.append(lits[:-1])
    return cubes


def solve_cube(nv, nc, body, cube, outdir, i, timeout=0, proof=False, check=False):
    """Solve CNF + cube; returns the result record (see the module docstring)."""
    path = os.path.join(outdir, f"cube{i}.cnf")
    with open(path, "w") as fh:
        fh.write(f"p cnf {nv} {nc + len(cube)}\n")
        fh.write(body)
        for lit in cube:
            fh.write(f"{lit} 0\n")
    cmd = ["nice", "-n", "10", "cadical", "-q"]
    if timeout:
        cmd += ["-t", str(timeout)]
    prf = os.path.join(outdir, f"cube{i}.lrat")
    chk = None
    if proof and check:
        # stream the proof through a named pipe into lrat-check: nothing is written to disk
        prf = os.path.join(outdir, f"cube{i}.fifo")
        if os.path.exists(prf):
            os.unlink(prf)
        os.mkfifo(prf)
        chk = subprocess.Popen([LRAT_CHECK, path, prf], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    if proof:
        cmd += ["--lrat=true", "--binary=false", path, prf]
    else:
        cmd += [path]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    secs = round(time.time() - t0, 1)
    status = {10: "SAT", 20: "UNSAT"}.get(r.returncode, "UNKNOWN")
    rec = {"cube": i, "status": status, "secs": secs, "len": len(cube)}
    if status == "SAT":
        with open(os.path.join(outdir, f"cube{i}.model"), "w") as fh:
            fh.write(r.stdout)
    if chk is not None:
        out, _ = chk.communicate()
        os.unlink(prf)
        if status == "UNSAT":
            rec["check"] = lrat_verdict(chk.returncode, out)
    os.unlink(path)
    return rec


def arg(name, default, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    cnf, icnf, outdir = sys.argv[1:4]
    workers = arg("--workers", 4, int)
    sample = arg("--sample", 0, int)
    seed = arg("--seed", 1, int)
    timeout = arg("--timeout", 0, int)
    proof = "--proof" in sys.argv
    check = "--check" in sys.argv
    os.makedirs(outdir, exist_ok=True)
    nv, nc, body = read_cnf(cnf)
    cubes = read_cubes(icnf)
    order = list(range(len(cubes)))
    if sample:
        order = sorted(random.Random(seed).sample(order, min(sample, len(order))))
    done_path = os.path.join(outdir, "results.jsonl")
    done = set()
    if os.path.exists(done_path):
        with open(done_path) as fh:
            for line in fh:
                r = json.loads(line)
                if r["status"] in ("UNSAT", "SAT"):
                    done.add(r["cube"])
    todo = [i for i in order if i not in done]
    print(f"cubes={len(cubes)} selected={len(order)} todo={len(todo)}", flush=True)

    def run(i):
        return solve_cube(nv, nc, body, cubes[i], outdir, i, timeout, proof, check)

    with open(done_path, "a") as out, ThreadPoolExecutor(workers) as ex:
        for fut in as_completed([ex.submit(run, i) for i in todo]):
            rec = fut.result()
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(json.dumps(rec), flush=True)
            if rec["status"] == "SAT":
                print("SAT cube found", flush=True)


if __name__ == "__main__":
    main()
