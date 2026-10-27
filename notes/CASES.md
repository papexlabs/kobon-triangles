# Case split for T >= n(n-2)/3 (used for n = 8, K = 16 and n = 11, K = 33)

Notation: n lines (or pseudolines) in the affine plane, T bounded triangular faces. A vertex v
has multiplicity m_v (lines through it); parallel classes have sizes q. A segment is a bounded
piece of a line between consecutive vertices; every side of a triangular face is one segment.

1. Segments: S = n(n-2) - sum_classes q(q-1) - sum_v m_v(m_v - 2).
   (A line meets n-1-p other lines in n-1-p-sum_{v on it}(m_v-2) distinct points.)
2. A segment is a side of at most two triangles (one per side). If it is a side of two, one
   endpoint has multiplicity >= 3 (two triangles on PQ need two different pairs of lines through
   P and Q, else two lines would meet twice). Let d_v be the number of such doubly used segments
   at v. Then 3T <= S + D <= S + sum_{m_v >= 3} d_v.
3. With 3T >= n(n-2): sum_v (d_v - m_v(m_v-2)) >= sum q(q-1) >= 0.
   d_v <= 2 m_v, so the term g_v = d_v - m_v(m_v-2) is <= 3 for m = 3, <= 0 for m = 4,
   and < 0 for m >= 5.
4. A doubly used segment at v has a triangle with apex v on each side, so both sectors at v next
   to it are triangular faces. With m lines through v there are 2m sectors in a cycle, and d_v is
   the number of consecutive pairs of triangular sectors.
5. Cases:
   - No line meets two others at one point and no parallels: simple (Case A).
   - Only parallels, no multiple point: the sum in 3 is 0 >= sum q(q-1) > 0, impossible.
   - Some multiple point: some g_v >= 0, so either a triple point with d_v >= 3, or a point of
     multiplicity 4 with d_v = 8 (all 8 sectors triangles).
     * Triple point, d_v >= 3: in a 6-cycle of sectors this needs a run of at least 4
       consecutive triangular sectors. A run of 4 contains two opposite sectors (between the same
       two lines, call them 1 and 2) and, next to one of them, a sector between line 2 and the
       third line 3 (relabel 1 and 2 if needed).
     * Quadruple point, all 8 sectors triangles: choose two lines 1, 2 through it with adjacent
       rays and the next line 3; the two sectors between 1 and 2 and one sector between 2 and 3
       are triangles.
   Both give Case B: lines 1, 2, 3 concurrent; triangles T(1,2,x) and T(1,2,y) in the two
   opposite sectors with x != y (three lines bound only one triangle), relabelled x = 4, y = 5;
   and some T(2,3,z).
6. Case A is the --simple model (no concurrent triple among lines 1..n; parallels allowed, they
   are excluded by item 5 anyway). Case B is the --case-b model. If both are unsatisfiable at
   K = n(n-2)/3, no arrangement has n(n-2)/3 triangles.

Orientation normalisation in case B: chi(0,1,2) = +, chi(0,1,e) in {+,0}, chi(0,2,e) = + when
chi(0,1,e) = 0, chi(1,2,4) = + (flip line 1 together with every line e >= 2).

Status: argument written 2026-10-27 by Claude Opus 5.5; needs a human check.
