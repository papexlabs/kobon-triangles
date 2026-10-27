"""Check that the cubes of a split leave nothing out.

march_cu omits the leaves it refutes itself, so the cubes need not cover every assignment. The
check is that CNF + (not c_i for every cube i) is unsatisfiable, proved with an LRAT proof that
lrat-check verifies. Together with an UNSAT result for CNF + c_i for every i this shows that the
CNF is unsatisfiable.

Usage: python3 check_cover.py CNF ICNF OUTDIR
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LRAT_CHECK = os.path.join(HERE, "..", "tools", "drat-trim", "lrat-check")


def main():
    cnf, icnf, outdir = sys.argv[1:4]
    os.makedirs(outdir, exist_ok=True)
    with open(cnf) as fh:
        header = fh.readline().split()
        nv, nc0 = int(header[2]), int(header[3])
        body = fh.read()
    clauses = []
    with open(icnf) as fh:
        for line in fh:
            if line.startswith("a "):
                lits = [int(x) for x in line.split()[1:-1]]
                clauses.append([-x for x in lits])
    path = os.path.join(outdir, "cover.cnf")
    prf = os.path.join(outdir, "cover.lrat")
    with open(path, "w") as fh:
        fh.write(f"p cnf {nv} {nc0 + len(clauses)}\n")
        fh.write(body)
        for c in clauses:
            fh.write(" ".join(map(str, c)) + " 0\n")
    r = subprocess.run(["cadical", "-q", "--lrat=true", "--binary=false", path, prf],
                       capture_output=True, text=True)
    if r.returncode != 20:
        print(f"cubes={len(clauses)} NOT A COVER (cadical exit {r.returncode})")
        sys.exit(1)
    c = subprocess.run([LRAT_CHECK, path, prf], capture_output=True, text=True)
    ok = "c VERIFIED" in c.stdout
    print(f"cubes={len(clauses)} cover={'VERIFIED' if ok else 'CHECK FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
