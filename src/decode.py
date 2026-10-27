"""Decode a satisfying assignment of the model into a chirotope and its bounded triangles.

Variables are numbered by build() deterministically, so rebuilding the model with the same
options recovers the meaning of each variable. Reads CaDiCaL/Kissat output ("v" lines).

Usage: python3 decode.py N K MODEL_FILE [--simple | --case-b] [--lex] [--redundant]
"""

import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kobon_cnf import build  # noqa: E402


def read_model(path):
    vals = set()
    for line in open(path):
        if line.startswith("v "):
            vals.update(int(x) for x in line.split()[1:] if x != "0")
    return vals


def main():
    n, K, model = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    f, T, nz, pos = build(n, K, "--simple" in sys.argv, "--case-b" in sys.argv,
                          redundant="--redundant" in sys.argv, lex="--lex" in sys.argv)
    m = read_model(model)
    chi = {}
    for t in itertools.combinations(range(n + 1), 3):
        chi[t] = 0 if -nz[t] in m else (1 if pos[t] in m else -1)
    sym = {1: "+", -1: "-", 0: "0"}
    print("chirotope (element 0 = line at infinity), triples in lexicographic order:")
    print("".join(sym[chi[t]] for t in sorted(chi)))
    tri = [t for t, v in sorted(T.items()) if v in m]
    print(f"triangles marked: {len(tri)}")
    print(" ".join("".join(map(lambda x: format(x, "x"), t)) for t in tri))
    conc = [t for t in chi if 0 not in t and chi[t] == 0]
    par = [(a, b) for a, b in itertools.combinations(range(1, n + 1), 2) if chi[(0, a, b)] == 0]
    print(f"concurrent triples: {conc}")
    print(f"parallel pairs: {par}")


if __name__ == "__main__":
    main()
