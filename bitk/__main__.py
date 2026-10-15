"""Compare two CSV extracts of the same figures from the command line.

    python -m bitk left.csv right.csv --keys month,country --measures net_sales,orders [--tolerance 0.005]

Writes the differences to stdout (or ``--out file.csv``) and exits with code 1 when any key differs, so it can
gate a scheduled refresh or a migration.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from .reconcile import compare


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bitk", description=__doc__.splitlines()[0])
    ap.add_argument("left")
    ap.add_argument("right")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--measures", required=True)
    ap.add_argument("--tolerance", type=float, default=0.0)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    keys, measures = a.keys.split(","), a.measures.split(",")
    left, right = (pd.read_csv(p, dtype={k: str for k in keys}) for p in (a.left, a.right))
    cmp = compare(left, right, keys, measures, a.tolerance, names=("left", "right"))
    bad = cmp[~cmp["matches"]]
    if a.out:
        cmp.to_csv(a.out, index=False)
    print(f"{len(cmp)} keys compared, {len(bad)} with differences")
    if len(bad):
        print(bad.head(20).to_string(index=False))
    return 1 if len(bad) else 0


if __name__ == "__main__":
    sys.exit(main())
