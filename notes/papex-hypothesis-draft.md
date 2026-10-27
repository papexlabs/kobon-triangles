# Papex Hypothesis draft (to be prepared in the papexlabs account, reviewed and signed by a person)

**Title:** No arrangement of 11 lines has 33 bounded triangles (Kobon triangle problem, a(11) = 32)

**Claim:** Every arrangement of 11 straight lines in the plane, including arrangements with
parallel lines and with three or more lines through a point, has at most 32 bounded triangular
faces. Together with Honma's 32-triangle arrangement this gives a(11) = 32 in OEIS A006066.

**Significance:** a(11) was removed from OEIS on 9 October 2026 because its proof relied on a
2007 lemma (Clément–Bader, Lemma 1) that fails for non-simple arrangements (Parpalak–Utkin, 2026).
Simple perfect arrangements are already excluded (Savchuk, arXiv:2507.07951). The open part is
the non-simple case; settling it restores a(11) and tests the method for a(12)–a(17).

**Falsification criteria:** An explicit arrangement of 11 lines with 33 bounded triangular faces,
checked with exact arithmetic, refutes the claim. A satisfying assignment of our SAT model is a
pseudoline arrangement with 33 triangles; if it can be straightened, the claim is false.

**Expected outcomes:** (a) the SAT model for 11 pseudolines and 33 triangles is unsatisfiable,
with a DRAT/LRAT proof checked by an independent checker; or (b) a pseudoline arrangement with 33
triangles, which is then straightened or shown non-stretchable.

**Methodology:** Affine pseudoline arrangements as simple rank-3 oriented matroids on
{line at infinity, 1..11} (Folkman–Lawrence). SAT encoding of the chirotope (alternation,
matroid closure, 3-term Grassmann–Plücker relations), bounded-triangle faces via vertex sides
normalised by the line at infinity, a cardinality constraint, and sound symmetry breaking.
Validated on n = 3..7 (reproduces a(n) = 1, 2, 5, 7, 11). Solvers: Kissat 4.0.4, CaDiCaL 3.0.1.
Code: written from the published statements, not from Savchuk's tools.

**AI involvement:** The model, code and runs were produced by Claude Opus 5.5 working for
Papex Labs; a person at Papex Labs reviews and signs each version.

**Field:** Mathematics — combinatorial geometry. **Keywords:** Kobon triangles; line
arrangements; pseudolines; oriented matroids; SAT.
