# The LRAT checker used from version 2

`lrat-check.c` is `lrat-check.c` of [drat-trim](https://github.com/marijnheule/drat-trim) at
commit `2e3b2dc` with the change in `empty-clause.patch`. `LICENSE` is drat-trim's licence (MIT).

**Why.** The unpatched `lrat-check` accepts a final empty-clause step whose hints do not end in a
conflict. For example, it prints `c VERIFIED` for the proof `3 0 0` of the satisfiable formula
`p cnf 2 2 / 1 2 0 / -1 2 0`. This is drat-trim issue
[#42](https://github.com/marijnheule/drat-trim/issues/42); pull request
[#43](https://github.com/marijnheule/drat-trim/pull/43) proposes a fix. The patch here rejects an
empty clause unless its hints end in a conflict, and treats a hint to a clause index outside the
clause table as a hint to a deleted clause. It was written for
[papexlabs/r7-tournament-ramsey](https://github.com/papexlabs/r7-tournament-ramsey) (commit
`645ee78` there, with tests).

**What this means for the runs of version 1** (27 October to 2 November 2026). They used the
unpatched checker. It checked every lemma of every proof; only the last step, the empty clause,
was not checked and rested on CaDiCaL's answer "unsatisfiable". `results/recheck-fixed/` holds
what has been checked again with the patched checker; the paper's Section 6 lists it.

**Build.**

```sh
cc -std=c99 -DLONGTYPE -O2 -o checker/lrat-check checker/lrat-check.c
```

The scripts use `checker/lrat-check` (or the binary named by the environment variable
`LRAT_CHECK`) and count a proof as verified only if the checker exits with code 0, prints the
line `c VERIFIED` and prints neither `FAILED` nor `NOT VERIFIED`.
