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

Symmetry breaking (sound; paper, Lemma 7). Relabelling: case A fixes T(1,2,3); case B labels
the configuration of the case split (chi(1,2,3) = 0, T(1,2,4), T(1,2,5), some T(2,3,z)).
Reorientation: chi(0,1,2) = +, chi(0,1,e) in {+,0} for e >= 3, chi(0,2,e) = + when
chi(0,1,e) = 0, and chi(1,2,3) = + (case A) or chi(1,2,4) = + (case B). With --lex, the lines
without a role (4..n in case A, 6..n in case B) satisfy chi <=_lex chi o (i i+1).

Usage: python3 kobon_cnf.py N K [--simple | --case-b] [--redundant] [--lex] > out.cnf
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


def build(n, K, simple=False, case_b=False, sym=True, redundant=False, lex=False):
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
    if K <= 0:
        pass
    elif K <= m:
        f.add(s[m][K])
    else:
        f.add()  # impossible

    if redundant:
        add_redundant(f, n, K, simple, T, NZ)

    # symmetry breaking
    if not sym:
        pass
    elif case_b:
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
    if sym and lex:
        # Lines with no special role can be relabelled freely: 4..n in case A, 6..n in case B.
        # For each transposition (i, i+1) of such lines require chi <=_lex chi o (i i+1) over
        # all triples in sorted order, with - < 0 < +. Every relabelling keeps the other
        # constraints, so the lexicographically smallest relabelling of a solution is a solution.
        first = 6 if case_b else 4
        triples = list(itertools.combinations(E, 3))
        for i in range(first, n):
            sw = {i: i + 1, i + 1: i}
            eq = None  # None = true
            for t in triples:
                if i not in t and i + 1 not in t:
                    continue
                x = (P(*t), M(*t), NZ(*t))
                st = tuple(sw.get(v, v) for v in t)
                y = (P(*st), M(*st), NZ(*st))  # chi o sigma at t
                pre = [-eq] if eq else []
                f.add(*pre, -x[0], y[0])  # x = + -> y = +
                f.add(*pre, -y[1], x[1])  # y = - -> x = -
                nxt = f.var()
                f.add(*pre, -x[0], -y[0], nxt)
                f.add(*pre, -x[1], -y[1], nxt)
                f.add(*pre, x[2], y[2], nxt)
                eq = nxt
    return f, T, nz, pos


def totalizer(f, lits, cap):
    """Unary count of lits, capped: out[j-1] <-> at least j of lits are true (j = 1..cap)."""
    if len(lits) == 1:
        return [lits[0]]
    mid = len(lits) // 2
    a = totalizer(f, lits[:mid], cap)
    b = totalizer(f, lits[mid:], cap)
    out = [f.var() for _ in range(min(len(a) + len(b), cap))]
    for i in range(len(a) + 1):
        for j in range(len(b) + 1):
            if i + j >= 1:  # a_i and b_j -> out_{min(i+j, cap)}
                lits_up = ([-a[i - 1]] if i else []) + ([-b[j - 1]] if j else [])
                f.add(*lits_up, out[min(i + j, len(out)) - 1])
            k = i + j + 1
            if k <= len(out):  # out_k -> a_{i+1} or b_{j+1}
                lits_dn = ([a[i]] if i < len(a) else []) + ([b[j]] if j < len(b) else [])
                f.add(-out[k - 1], *lits_dn)
    return out


def add_redundant(f, n, K, simple, T, NZ):
    """Constraints implied by the counting argument (notes/CASES.md); sound for every
    arrangement of pseudolines, so they remove no solution.

    R1 (per line a). Let t_a be the number of triangles with a side on a and p_a the number of
    lines parallel to a. A triangle uses one segment of a as a side; a segment is a side of at most
    one triangle on each side of a, and of two only if an endpoint has multiplicity >= 3. Line a
    has n - 2 - p_a - sum_{v on a}(m_v - 2) segments, so
        t_a <= n - 2 - p_a + sum_{v on a, m_v >= 3} (delta_{v,a} - (m_v - 2)),
    where delta_{v,a} <= 2 counts the segments of a at v that are sides of two triangles. A term
    with m_v >= 4 is <= 0 and is dropped. At a point v = a∩b∩c of multiplicity exactly 3 (e_abc),
    a segment of a at v is a side of two triangles only if both sectors next to it are
    triangles, one between a and b and one between a and c, with corner v. With N_ab the number
    of triangles T(a, b, x), delta_{v,a} <= u1 + u2 where u1 -> N_ab, N_ac >= 1 and
    u2 -> N_ab, N_ac >= 2. So t_a + p_a + E_a <= n - 2 + U_a, with E_a the exact triple points on
    a and U_a the sum of the u's on a; at most (n - 1) // 2 triple points lie on a.
    R1 global. Summing over lines, 3K <= 3T = sum_a t_a, so P + E <= U + n(n - 2) - 3K with
    P = 2 #(parallel pairs), E = 3 #(exact triple points), U = sum of all u's (capped counts).
    R2 (per pair a, b). A triangle T(a, b, c) has its corner a∩b in a sector of a∩b bounded by
    a and b, and two such triangles cannot share a sector. There are 4 such sectors if a∩b is a
    simple vertex and 2 if a third line passes through it.
    In the --simple model there are no triple points and the per-line bound is t_a <= n - 2.
    """
    lines = list(range(1, n + 1))

    def Tl(a, b, c):
        return T[tuple(sorted((a, b, c)))]

    def par(a, b):
        return -NZ(a, b, 0)

    tmax = (n - 1) // 2

    if simple:
        for a in lines:
            others = [x for x in lines if x != a]
            tri = [Tl(a, b, c) for b, c in itertools.combinations(others, 2)]
            out = totalizer(f, tri + [par(a, x) for x in others], n - 1)
            if len(out) >= n - 1:
                f.add(-out[n - 2])  # t_a + p_a <= n - 2
            lower = 3 * K - (n - 1) * (n - 2)
            if lower > len(out):
                f.add()  # more than n - 2 triangles on a: impossible
            elif lower >= 1:
                f.add(out[lower - 1])  # the other lines carry at most (n - 1)(n - 2) sides
    else:
        # e_abc <- a, b, c meet at a finite point and no fourth line passes through it
        # (three parallel lines are concurrent at infinity; NZ(a, b, 0) excludes them)
        e = {}
        for a, b, c in itertools.combinations(lines, 3):
            v = f.var()
            f.add(NZ(a, b, c), -NZ(a, b, 0),
                  *[-NZ(a, b, d) for d in lines if d not in (a, b, c)], v)
            e[(a, b, c)] = v

        def atleast(w, a, b, k):  # w -> at least k of T(a, b, x)
            xs = [x for x in lines if x not in (a, b)]
            if k == 1:
                f.add(-w, *[Tl(a, b, x) for x in xs])
            else:
                for x in xs:
                    f.add(-w, *[Tl(a, b, y) for y in xs if y != x])

        all_u, cost = [], []
        for a in lines:
            others = [x for x in lines if x != a]
            pairs = list(itertools.combinations(others, 2))
            us = []
            for b, c in pairs:
                eabc = e[tuple(sorted((a, b, c)))]
                u1, u2 = f.var(), f.var()
                f.add(-u1, eabc)
                f.add(-u2, u1)
                atleast(u1, a, b, 1); atleast(u1, a, c, 1)
                atleast(u2, a, b, 2); atleast(u2, a, c, 2)
                us += [u1, u2]
            lhs = ([Tl(a, b, c) for b, c in pairs] + [par(a, x) for x in others]
                   + [e[tuple(sorted((a, b, c)))] for b, c in pairs])
            out = totalizer(f, lhs, n - 1 + 2 * tmax)
            ben = totalizer(f, us, 2 * tmax)
            if len(out) >= n - 1 + 2 * tmax:
                f.add(-out[n - 2 + 2 * tmax])
            for j in range(1, 2 * tmax + 1):
                if n - 2 + j <= len(out):
                    f.add(-out[n - 2 + j - 1], ben[j - 1])  # lhs >= n-2+j -> U_a >= j
            all_u += us
            cost += [par(a, x) for x in others]
        for t in e.values():
            cost += [t, t, t]
        cap = 3 * n
        slack = n * (n - 2) - 3 * K
        costs = totalizer(f, cost, cap)
        bens = totalizer(f, all_u, cap)
        if slack < 0:
            if -slack > len(bens):
                f.add()
            else:
                f.add(bens[-slack - 1])
        for j in range(1, len(costs) + 1):
            need = j - slack
            if 1 <= need <= len(bens):
                f.add(-costs[j - 1], bens[need - 1])  # P + E >= j -> U >= j - slack

    # R2
    for a, b in itertools.combinations(lines, 2):
        cs = [c for c in lines if c not in (a, b)]
        mp = f.var()  # a third line passes through a∩b (only this direction is needed)
        for x in cs:
            f.add(NZ(a, b, x), mp)
        for sub in itertools.combinations(cs, 5):
            f.add(*[-Tl(a, b, c) for c in sub])
        for sub in itertools.combinations(cs, 3):
            f.add(-mp, *[-Tl(a, b, c) for c in sub])

def write_dimacs(f, out):
    out.write(f"p cnf {f.nv} {len(f.clauses)}\n")
    for c in f.clauses:
        out.write(" ".join(map(str, c)) + " 0\n")


if __name__ == "__main__":
    n, K = int(sys.argv[1]), int(sys.argv[2])
    simple = "--simple" in sys.argv
    case_b = "--case-b" in sys.argv
    redundant = "--redundant" in sys.argv
    lex = "--lex" in sys.argv
    f, T, nz, pos = build(n, K, simple, case_b, redundant=redundant, lex=lex)
    write_dimacs(f, sys.stdout)
    # variable map for decoding
    with open(sys.argv[sys.argv.index("--map") + 1] if "--map" in sys.argv else "/dev/null", "w") as mf:
        for t, v in nz.items():
            mf.write(f"nz {' '.join(map(str, t))} {v}\n")
        for t, v in pos.items():
            mf.write(f"pos {' '.join(map(str, t))} {v}\n")
        for t, v in T.items():
            mf.write(f"T {' '.join(map(str, t))} {v}\n")
