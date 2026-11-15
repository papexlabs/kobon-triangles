"""Write the manifest of a shared-work list: a random sample of case B leaves.

One JSON object per line: the unit key (shared-work/tree.py), the kind, the seconds the leaf took
in the original run (rounded up) and the SHA-256 of the leaf's formula. Leaves that were already
solved again with the patched checker (results/recheck-fixed/caseB.sample100.log) are left out.
The same arguments always give the same file; the SHA-256 of the file is the list's fingerprint.

Usage, from the repository root:
  python3 -I shared-work/make_manifest.py OUT [--units N] [--max-secs X] [--seed S]
"""

import hashlib
import json
import math
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tree  # noqa: E402

RECHECKED = os.path.join(tree.ROOT, "results", "recheck-fixed", "caseB.sample100.log")


def arg(name, default, cast):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def rechecked():
    keys = set()
    for line in open(RECHECKED):
        m = re.match(r"ok +(results/cubes_k11B_lex_d8\S*) cube (\d+): UNSAT VERIFIED", line)
        if m:
            keys.add(tree.key_of(os.path.join(tree.ROOT, m.group(1)), int(m.group(2))))
    return keys


def main():
    out = sys.argv[1]
    units = arg("--units", 2000, int)
    max_secs = arg("--max-secs", 20.0, float)
    seed = arg("--seed", 20261115, int)

    leaves = tree.all_leaves()
    done = rechecked()
    pool = sorted((k for k, s in leaves if s <= max_secs and k not in done), key=tree.natural)
    secs = dict(leaves)
    pick = sorted(random.Random(seed).sample(pool, units), key=tree.natural)
    top = tree.ensure_top_cnf()
    with open(out, "wb") as fh:
        for key in pick:
            line = {"key": key, "kind": "leaf", "expectedSeconds": max(1, math.ceil(secs[key])),
                    "inputSha256": "0x" + hashlib.sha256(tree.leaf_formula(top, key)).hexdigest()}
            fh.write((json.dumps(line, separators=(",", ":")) + "\n").encode())
    total = sum(max(1, math.ceil(secs[k])) for k in pick)
    print(f"tree: {len(leaves)} leaves; {len(done)} already re-checked; "
          f"{len(pool)} with recorded time at most {max_secs:g} s and not re-checked")
    print(f"manifest: {len(pick)} units, seed {seed}, expected {total} s in all ({total / 3600:.1f} h)")
    print(f"{out}: {os.path.getsize(out)} bytes, sha256 0x{tree.sha256_file(out)}")


if __name__ == "__main__":
    main()
