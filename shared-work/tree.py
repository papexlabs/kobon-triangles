"""The units of the shared-work list: leaves of the case B cube-and-conquer tree.

A unit key names one leaf. It is the leaf's node directory relative to the tree with "." between
its parts ("top" for the root of the tree), then ":" and the index of the cube in that node's cube
file. "c201.c63:17" is cube 17 of results/cubes_k11B_lex_d8/c201/c63/sub.icnf, and "top:5" is cube
5 of build/k11B_lex_d8.icnf.

The formula of a leaf is the case B formula, then one unit clause for every literal of every cube
on the path from the root to the leaf's node, then one unit clause for every literal of the leaf's
own cube. It is byte for byte the file that scripts/run_cubes.py and scripts/recheck.py give to the
solver, so its SHA-256 identifies the input of a unit.
"""

import functools
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from run_cubes import read_cnf, read_cubes  # noqa: E402
from summary import latest  # noqa: E402

TOP_CNF = os.path.join(ROOT, "build", "k11_33_caseB.lex.cnf")
# results/certified.sha256 lists the same value
TOP_CNF_SHA256 = "f6c143c271f7bce4ed9d65495e7e045c253b70401c50551b08e20a563a918d2b"
TOP_ICNF = os.path.join(ROOT, "build", "k11B_lex_d8.icnf")
TREE = os.path.join(ROOT, "results", "cubes_k11B_lex_d8")
KEY_RE = re.compile(r"^(top|c\d+(?:\.c\d+)*):(\d+)$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_top_cnf():
    """The case B formula, written again by src/kobon_cnf.py unless the right file is already there."""
    if not (os.path.exists(TOP_CNF) and sha256_file(TOP_CNF) == TOP_CNF_SHA256):
        os.makedirs(os.path.dirname(TOP_CNF), exist_ok=True)
        with open(TOP_CNF, "w") as out:
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "src", "kobon_cnf.py"),
                            "11", "33", "--case-b", "--lex"], stdout=out, check=True)
        if sha256_file(TOP_CNF) != TOP_CNF_SHA256:
            raise SystemExit("The case B formula written here is not the published one "
                             f"(SHA-256 {TOP_CNF_SHA256}). Use a fresh copy of the repository.")
    return read_cnf(TOP_CNF)


@functools.lru_cache(maxsize=None)
def cubes_of(icnf):
    return read_cubes(icnf)


def key_of(node_dir, index):
    rel = os.path.relpath(node_dir, TREE)
    return ("top" if rel == "." else rel.replace(os.sep, ".")) + f":{index}"


def leaf_cubes(key):
    """The cubes on the path from the root to the leaf's node, then the leaf's own cube."""
    m = KEY_RE.match(key)
    if not m:
        raise ValueError(f"not a unit key: {key}")
    icnf, node, path = TOP_ICNF, TREE, []
    if m.group(1) != "top":
        for part in m.group(1).split("."):
            cubes = cubes_of(icnf)
            i = int(part[1:])
            if i >= len(cubes):
                raise ValueError(f"no such node in the tree: {key}")
            path.append(cubes[i])
            node = os.path.join(node, part)
            icnf = os.path.join(node, "sub.icnf")
            if not os.path.exists(icnf):
                raise ValueError(f"no such node in the tree: {key}")
    cubes = cubes_of(icnf)
    i = int(m.group(2))
    if i >= len(cubes):
        raise ValueError(f"no such cube in the tree: {key}")
    return path, cubes[i]


def leaf_formula(top, key):
    """The leaf's formula as bytes."""
    nv, nc, body = top
    path, cube = leaf_cubes(key)
    units = [lit for c in path for lit in c] + list(cube)
    text = f"p cnf {nv} {nc + len(units)}\n" + body + "".join(f"{lit} 0\n" for lit in units)
    return text.encode()


def all_leaves():
    """Every leaf the closure rule of scripts/summary.py uses: (key, recorded seconds)."""
    out = []

    def walk(icnf, node):
        records = latest(node)
        for i in range(len(cubes_of(icnf))):
            r = records.get(i)
            if r and r["status"] == "UNSAT" and r.get("check") == "VERIFIED":
                out.append((key_of(node, i), r["secs"]))
                continue
            sub = os.path.join(node, f"c{i}")
            cover = os.path.join(sub, "cover.out")
            if r and r["status"] == "UNKNOWN" and os.path.exists(cover) \
                    and "cover=VERIFIED" in open(cover).read():
                walk(os.path.join(sub, "sub.icnf"), sub)
            else:
                raise SystemExit(f"open cube in the tree: {node} cube {i}")

    walk(TOP_ICNF, TREE)
    return out


def natural(key):
    """Sort order of keys: by node path, then by cube index."""
    m = KEY_RE.match(key)
    parts = [] if m.group(1) == "top" else [int(p[1:]) for p in m.group(1).split(".")]
    return parts, int(m.group(2))
