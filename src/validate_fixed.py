"""Check the CNF model against real line arrangements.

For random arrangements of straight lines with integer coefficients, including concurrent
triples and parallel classes, this script
  1. counts the bounded triangular faces geometrically, by cutting a large box with every line
     in exact rational arithmetic and counting the 3-gons that do not touch the box;
  2. computes the chirotope (signs of 3x3 determinants, line at infinity = (0, 0, 1));
  3. builds the model without symmetry breaking, fixes the chirotope with unit clauses, and asks
     a SAT solver for K = count (must be SAT) and K = count + 1 (must be UNSAT).
The face count does not use the model's face test, so step 3 checks that the model admits every
real arrangement with its true number of triangles and no more.

Usage: python3 validate_fixed.py TRIALS NMIN NMAX [SEED] [--redundant] [--rich M]
(--rich M: keep the arrangement with the most triangles among M samples)
"""

import itertools
import os
import random
import subprocess
import sys
import tempfile
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kobon_cnf import build, write_dimacs  # noqa: E402

SOLVER = os.environ.get("SOLVER", "cadical")


def random_arrangement(n, rng):
    """Lines (a, b, c) for a x + b y + c = 0, with forced concurrencies and parallels."""
    lines = []

    def fresh(cand):
        a, b, c = cand
        if (a, b) == (0, 0):
            return False
        for (p, q, r) in lines:  # reject scalar multiples
            if a * q - b * p == 0 and a * r - c * p == 0 and b * r - c * q == 0:
                return False
        return True

    while len(lines) < n:
        kind = rng.random()
        if kind < 0.4 and lines:
            # through a point where existing lines meet, or through a random point
            pts = []
            for (l1, l2) in itertools.combinations(lines, 2):
                d = l1[0] * l2[1] - l1[1] * l2[0]
                if d != 0:
                    x = Fraction(l1[1] * l2[2] - l1[2] * l2[1], d)
                    y = Fraction(l1[2] * l2[0] - l1[0] * l2[2], d)
                    pts.append((x, y))
            if not pts:
                continue
            x, y = rng.choice(pts)
            a, b = rng.randint(-6, 6), rng.randint(-6, 6)
            c = -(a * x + b * y)
            den = c.denominator
            cand = (a * den, b * den, int(c * den))
        elif kind < 0.55 and lines:
            p, q, _ = rng.choice(lines)
            cand = (p, q, rng.randint(-30, 30))
        else:
            cand = (rng.randint(-6, 6), rng.randint(-6, 6), rng.randint(-30, 30))
        if fresh(cand):
            lines.append(cand)
    if all(a * lines[0][1] - b * lines[0][0] == 0 for a, b, _ in lines):
        # all lines parallel: rank 2, no triangles; the model (rank 3) excludes it
        return random_arrangement(n, rng)
    return lines


def det3(u, v, w):
    return (u[0] * (v[1] * w[2] - v[2] * w[1])
            - u[1] * (v[0] * w[2] - v[2] * w[0])
            + u[2] * (v[0] * w[1] - v[1] * w[0]))


def count_triangles(lines):
    """Bounded triangular faces, by cutting a box with all lines (exact arithmetic)."""
    pts = []
    for (l1, l2) in itertools.combinations(lines, 2):
        d = l1[0] * l2[1] - l1[1] * l2[0]
        if d != 0:
            pts.append((Fraction(l1[1] * l2[2] - l1[2] * l2[1], d),
                        Fraction(l1[2] * l2[0] - l1[0] * l2[2], d)))
    R = Fraction(max([abs(c) for p in pts for c in p] + [1]) * 4 + 10)  # exact, never float
    box = [(-R, -R), (R, -R), (R, R), (-R, R)]
    polys = [box]

    def val(l, p):
        return l[0] * p[0] + l[1] * p[1] + l[2]

    for l in lines:
        nxt = []
        for poly in polys:
            s = [val(l, p) for p in poly]
            if not (any(v > 0 for v in s) and any(v < 0 for v in s)):
                nxt.append(poly)
                continue
            plus, minus = [], []
            k = len(poly)
            for i in range(k):
                p, q = poly[i], poly[(i + 1) % k]
                sp, sq = s[i], s[(i + 1) % k]
                if sp >= 0:
                    plus.append(p)
                if sp <= 0:
                    minus.append(p)
                if (sp > 0 and sq < 0) or (sp < 0 and sq > 0):
                    t = sp / (sp - sq)
                    x = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
                    plus.append(x)
                    minus.append(x)
            nxt += [plus, minus]
        polys = nxt

    def on_box(p):
        return abs(p[0]) == R or abs(p[1]) == R

    return sum(1 for poly in polys if len(poly) == 3 and not any(on_box(p) for p in poly))


def solve(f, extra):
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as fh:
        clauses = f.clauses + [tuple(c) for c in extra]
        fh.write(f"p cnf {f.nv} {len(clauses)}\n")
        for c in clauses:
            fh.write(" ".join(map(str, c)) + " 0\n")
        name = fh.name
    try:
        r = subprocess.run([SOLVER, "-q", name], capture_output=True, text=True)
    finally:
        os.unlink(name)
    return {10: "SAT", 20: "UNSAT"}.get(r.returncode, f"ERR{r.returncode}")


def check(lines, redundant=False):
    n = len(lines)
    vec = [(0, 0, 1)] + list(lines)  # element 0 = line at infinity
    concurrent = sum(1 for t in itertools.combinations(range(1, n + 1), 3)
                     if det3(*(vec[i] for i in t)) == 0)
    parallel = sum(1 for a, b in itertools.combinations(range(1, n + 1), 2)
                   if det3(vec[a], vec[b], vec[0]) == 0)
    true_count = count_triangles(lines)
    # the --simple model is checked on arrangements without concurrent triples
    variants = [False] + ([True] if concurrent == 0 else [])
    results = []
    for simple in variants:
        for K in (true_count, true_count + 1):
            f, T, nz, pos = build(n, K, simple=simple, sym=False, redundant=redundant)
            units = []
            for t, v in nz.items():
                d = det3(*(vec[i] for i in t))
                units.append((v,) if d != 0 else (-v,))
                units.append((pos[t],) if d > 0 else (-pos[t],))
            results.append(solve(f, units))
    return true_count, concurrent, parallel, results


if __name__ == "__main__":
    redundant = "--redundant" in sys.argv
    rich = int(sys.argv[sys.argv.index("--rich") + 1]) if "--rich" in sys.argv else 0
    args = [a for i, a in enumerate(sys.argv[1:], 1)
            if not a.startswith("--") and sys.argv[i - 1] != "--rich"]
    trials, nmin, nmax = int(args[0]), int(args[1]), int(args[2])
    rng = random.Random(int(args[3]) if len(args) > 3 else 1)
    bad = 0
    stats = {"nonsimple": 0, "parallel": 0}
    for i in range(trials):
        n = rng.randint(nmin, nmax)
        lines = random_arrangement(n, rng)
        if rich:  # keep the arrangement with the most triangles among several samples
            cands = [lines] + [random_arrangement(n, rng) for _ in range(rich - 1)]
            lines = max(cands, key=count_triangles)
        cnt, conc, par, res = check(lines, redundant)
        ok = all(r == ("SAT" if k % 2 == 0 else "UNSAT") for k, r in enumerate(res))
        r0, r1 = res[0], res[1]
        if len(res) > 2:
            r1 += f" simple:{res[2]}/{res[3]}"
        stats["nonsimple"] += conc > 0
        stats["parallel"] += par > 0
        if not ok:
            bad += 1
        print(f"{i:3d} n={n} triangles={cnt} concurrent_triples={conc} parallel_pairs={par} "
              f"K=count:{r0} K=count+1:{r1} {'ok' if ok else 'MISMATCH ' + repr(lines)}",
              flush=True)
    print(f"trials={trials} nonsimple={stats['nonsimple']} with_parallels={stats['parallel']} "
          f"mismatches={bad}")
    sys.exit(1 if bad else 0)
