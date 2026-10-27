# Kobon triangles, 11 lines: open attempt (Papex Labs)

Started 2026-10-27.

## Question

What is the largest number of bounded triangular faces in an arrangement of 11 straight lines?
Honma's construction gives 32; Tamura's counting bound gives 33. On 9 October 2026 Pavlo Savchuk
removed a(11)–a(17) from OEIS A006066: his SAT search excluded 33 only for *simple perfect*
arrangements, and the reduction to that case rested on Lemmas 1–2 of Clément–Bader (2007), whose
Lemma 1, Step 3 has a counterexample found by Parpalak and Utkin (2026): a triangle with its
three medians, where the centroid is the vertex of six pairs of triangles sharing a side.

## Why non-simple arrangements matter

In a simple arrangement a segment borders at most one triangle (two triangles on a segment PQ
would need two different pairs of lines through P and Q meeting twice). With three or more lines
through a point this fails: a segment can border a triangle on each side. So the counting bound
⌊n(n−2)/3⌋ is proved for simple arrangements, and the non-simple case for n = 11 is unchecked.

## Method (independent of Savchuk's table encoding)

- Affine pseudoline arrangements = simple rank-3 oriented matroids on {∞, 1..n} (Folkman–Lawrence).
- SAT model over the chirotope (signs +, −, 0 on triples): alternating, distinct elements, simple
  rank-3 matroid closure, 3-term Grassmann–Plücker relations.
- Triangle (a,b,c) is a bounded face iff the lines are pairwise non-parallel, not concurrent, and no
  other line puts the three vertices on both sides (vertex sides normalised by the line at infinity).
- Cardinality: at least K triangles. UNSAT for K = 33, n = 11 would prove a(11) = 32 for all
  pseudoline (hence straight-line) arrangements; a DRAT/LRAT proof makes it checkable.
- Validation: the model reproduces a(3..7) = 1, 2, 5, 7, 11 (SAT at a(n), UNSAT at a(n)+1),
  including non-simple arrangements.

## Next

1. Timing: n = 8 general; n = 11 simple (should be UNSAT, Savchuk's result).
2. If n = 11 general is too hard: add sound redundant constraints from the counting argument
   (multiple points of multiplicity 3–4 only; every double-bordered segment has an endpoint of
   multiplicity >= 3; parallel classes cost q(q−1) segments) and stronger symmetry breaking.
3. UNSAT with a checked proof (cadical --lrat + lrat-check, or drat-trim), or an explicit
   arrangement with 33 triangles that is then straightened and checked exactly.
