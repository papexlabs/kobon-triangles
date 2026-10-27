"""CNF model for Kobon triangles over all affine pseudoline arrangements (simple or not).

Model (independent of Savchuk's table encoding). An affine arrangement of n pseudolines is a
projective arrangement of n + 1 pseudolines in which element 0 is the line at infinity. By the
Folkman–Lawrence theorem these are exactly the simple rank-3 oriented matroids on {0, ..., n},
given here by a chirotope chi on triples with values in {+, -, 0}:
  - chi is alternating (one sign per unordered triple, sign of a permutation by parity);
  - every pair of elements is independent (distinct pseudolines);
  - the zero triples form a simple rank-3 matroid: if abc and abd are dependent, so are acd, bcd;
  - the 3-term Grassmann–Plücker relations hold: for every a and x1..x4 the products
      chi(a,x1,x2)chi(a,x3,x4), -chi(a,x1,x3)chi(a,x2,x4), chi(a,x1,x4)chi(a,x2,x3)
    are all zero or include both signs (Björner et al., Oriented Matroids, Thm 3.6.2).
Parallel lines are pairs a, b with chi(a,b,0) = 0; concurrent lines a, b, c have chi(a,b,c) = 0.

Bounded triangles. The vertex a∩b of lines a, b (not parallel) lies on side
    s_ab(d) = chi(a,b,d) * chi(a,b,0)
of line d (normalised by the line at infinity). Lines a, b, c bound a triangular face when they
are pairwise non-parallel, not concurrent, and no other line d has vertex sides of both signs
(such a d would cut the open triangle). A variable T(abc) implies these conditions; the model asks
for at least K true T variables. The converse implication is not needed: any arrangement with K
triangles satisfies the model, so UNSAT means no arrangement has K bounded triangles.

Symmetry breaking (sound): T(1,2,3) holds (relabelling); reorientation is fixed by
chi(0,1,e) in {+,0} for e >= 2, chi(0,1,2) = +, chi(0,2,e) = + when chi(0,1,e) = 0 (e >= 3),
and chi(1,2,3) = +.

Usage: python3 kobon_cnf.py N K [--simple] > out.cnf
"""

import itertools
import sys


class CNF:
    def __init__(self):
        self.nv = 0
        self.clauses = []

    def var(self):
        self.nv += 1
        return self.nv

    def add(self, *lits):
        self.clauses.append(lits)


def build(n, K, simple=False, case_b=False):
    f = CNF()
    E = range(n + 1)
    nz, pos = {}, {}
    for t in itertools.combinations(E, 3):
        nz[t] = f.var()
        pos[t] = f.var()
        f.add(nz[t], -pos[t])  # zero triples carry pos = false
        if simple and 0 not in t:
            f.add(nz[t])

    # plus/minus literals for an ordered triple
    plus, minus = {}, {}
    for t in itertools.combinations(E, 3):
        p, m = f.var(), f.var()
        f.add(-p, nz[t]); f.add(-p, pos[t]); f.add(p, -nz[t], -pos[t])
        f.add(-m, nz[t]); f.add(-m, -pos[t]); f.add(m, -nz[t], pos[t])
        plus[t], minus[t] = p, m

    def sorted_sign(a, b, c):
        lst = [a, b, c]
        inv = sum(1 for i in range(3) for j in range(i + 1, 3) if lst[i] > lst[j])
        return tuple(sorted(lst)), (1 if inv % 2 == 0 else -1)

    def P(a, b, c):  # chi(a,b,c) = +
        t, s = sorted_sign(a, b, c)
        return plus[t] if s > 0 else minus[t]

    def M(a, b, c):  # chi(a,b,c) = -
        t, s = sorted_sign(a, b, c)
        return minus[t] if s > 0 else plus[t]

    def NZ(a, b, c):
        return nz[sorted_sign(a, b, c)[0]]

    # distinct pseudolines: every pair is in some nonzero triple
    for a, b in itertools.combinations(E, 2):
        f.add(*[NZ(a, b, c) for c in E if c not in (a, b)])

    # simple rank-3 matroid: abc, abd dependent -> acd, bcd dependent
    for a, b, c, d in itertools.permutations(E, 4):
        if a < b and c < d:
            f.add(NZ(a, b, c), NZ(a, b, d), -NZ(a, c, d))
            f.add(NZ(a, b, c), NZ(a, b, d), -NZ(b, c, d))

    # 3-term Grassmann–Plücker relations
    def prod(sa, a3, sb, b3, neg):
        """Aux literals (tp, tm) with tp <-> product = +, tm <-> product = - ."""
        Pa, Ma = P(*a3), M(*a3)
        Pb, Mb = P(*b3), M(*b3)
        tp, tm = f.var(), f.var()
        same = [(Pa, Pb), (Ma, Mb)]
        diff = [(Pa, Mb), (Ma, Pb)]
        pos_pairs, neg_pairs = (diff, same) if neg else (same, diff)
        for x, y in pos_pairs:
            f.add(-x, -y, tp)
        # tp -> one of the positive pairs
        x1, y1 = pos_pairs[0]
        x2, y2 = pos_pairs[1]
        f.add(-tp, x1, x2); f.add(-tp, x1, y2); f.add(-tp, y1, x2); f.add(-tp, y1, y2)
        for x, y in neg_pairs:
            f.add(-x, -y, tm)
        x1, y1 = neg_pairs[0]
        x2, y2 = neg_pairs[1]
        f.add(-tm, x1, x2); f.add(-tm, x1, y2); f.add(-tm, y1, x2); f.add(-tm, y1, y2)
        return tp, tm

    for a in E:
        others = [x for x in E if x != a]
        for x1, x2, x3, x4 in itertools.combinations(others, 4):
            t1 = prod(None, (a, x1, x2), None, (a, x3, x4), False)
            t2 = prod(None, (a, x1, x3), None, (a, x2, x4), True)
            t3 = prod(None, (a, x1, x4), None, (a, x2, x3), False)
            plus_terms = [t[0] for t in (t1, t2, t3)]
            minus_terms = [t[1] for t in (t1, t2, t3)]
            for tp in plus_terms:
                f.add(-tp, *minus_terms)
            for tm in minus_terms:
                f.add(-tm, *plus_terms)

    # vertex sides: S+(a,b,d) forced when chi(a,b,d) chi(a,b,0) = +, S- when = -
    lines = range(1, n + 1)
    Sp, Sm = {}, {}
    for a, b in itertools.combinations(lines, 2):
        for d in lines:
            if d in (a, b):
                continue
            sp, sm = f.var(), f.var()
            f.add(-P(a, b, d), -P(a, b, 0), sp)
            f.add(-M(a, b, d), -M(a, b, 0), sp)
            f.add(-P(a, b, d), -M(a, b, 0), sm)
            f.add(-M(a, b, d), -P(a, b, 0), sm)
            Sp[(a, b, d)], Sm[(a, b, d)] = sp, sm

    T = {}
    for a, b, c in itertools.combinations(lines, 3):
        t = f.var()
        T[(a, b, c)] = t
        f.add(-t, NZ(a, b, c))
        for x, y in ((a, b), (a, c), (b, c)):
            f.add(-t, NZ(x, y, 0))
        verts = [(a, b), (a, c), (b, c)]
        for d in lines:
            if d in (a, b, c):
                continue
            for u in verts:
                for v in verts:
                    if u != v:
                        f.add(-t, -Sp[(u[0], u[1], d)], -Sm[(v[0], v[1], d)])

    # at least K triangles: sequential counter on the T variables
    xs = [T[k] for k in sorted(T)]
    m = len(xs)
    # s[i][j] <-> at least j of the first i variables are true (j = 1..K); only "->" needed:
    # we require s[m][K] and s[i][j] -> s[i-1][j] or (x_i and s[i-1][j-1])
    s = [[None] * (K + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        for j in range(1, K + 1):
            if j <= i:
                s[i][j] = f.var()
    for i in range(1, m + 1):
        for j in range(1, K + 1):
            if s[i][j] is None:
                continue
            prev_same = s[i - 1][j] if j <= i - 1 else None
            prev_less = s[i - 1][j - 1] if j - 1 >= 1 else True
            # s[i][j] -> prev_same or x_i
            f.add(-s[i][j], *( [prev_same] if prev_same else [] ), xs[i - 1])
            # s[i][j] -> prev_same or prev_less
            if prev_less is not True:
                f.add(-s[i][j], *( [prev_same] if prev_same else [] ), prev_less)
    if K <= m:
        f.add(s[m][K])
    else:
        f.add()  # impossible

    # symmetry breaking
    if case_b:
        # Case B (see notes/CASES.md): lines 1, 2, 3 meet at one point, the two sectors of that
        # point between lines 1 and 2 are triangles with outer lines 4 and 5, and some sector
        # between lines 2 and 3 is a triangle.
        f.add(-NZ(1, 2, 3))
        f.add(T[(1, 2, 4)])
        f.add(T[(1, 2, 5)])
        f.add(*[T[tuple(sorted((2, 3, z)))] for z in range(4, n + 1)])
        f.add(P(0, 1, 2))
        f.add(P(1, 2, 4))
        for e in range(3, n + 1):
            f.add(-M(0, 1, e))
            f.add(NZ(0, 1, e), P(0, 2, e))
    elif n >= 3:
        f.add(T[(1, 2, 3)])
        f.add(P(0, 1, 2))
        f.add(P(1, 2, 3))
        for e in range(3, n + 1):
            f.add(-M(0, 1, e))
            f.add(NZ(0, 1, e), P(0, 2, e))
    return f, T, nz, pos


def write_dimacs(f, out):
    out.write(f"p cnf {f.nv} {len(f.clauses)}\n")
    for c in f.clauses:
        out.write(" ".join(map(str, c)) + " 0\n")


if __name__ == "__main__":
    n, K = int(sys.argv[1]), int(sys.argv[2])
    simple = "--simple" in sys.argv
    case_b = "--case-b" in sys.argv
    f, T, nz, pos = build(n, K, simple, case_b)
    write_dimacs(f, sys.stdout)
    # variable map for decoding
    with open(sys.argv[sys.argv.index("--map") + 1] if "--map" in sys.argv else "/dev/null", "w") as mf:
        for t, v in nz.items():
            mf.write(f"nz {' '.join(map(str, t))} {v}\n")
        for t, v in pos.items():
            mf.write(f"pos {' '.join(map(str, t))} {v}\n")
        for t, v in T.items():
            mf.write(f"T {' '.join(map(str, t))} {v}\n")
