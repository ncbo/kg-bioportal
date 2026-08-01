#!/usr/bin/env python3
"""Download and extract KG-Bioportal KGX graphs from the latest release.

Each <ID>.tar.gz contains <ID>_nodes.tsv and <ID>_edges.tsv (KGX TSV).

Usage:
  python fetch_graph.py AGRO SEPIO            # -> ./AGRO/AGRO_nodes.tsv, etc.
  python fetch_graph.py AGRO -o data/graphs   # into a directory
  python fetch_graph.py AGRO --flat -o inbox  # extract straight into the output dir
"""
import argparse
import os
import socket
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

socket.setdefaulttimeout(180)  # don't hang forever on a stalled connection

ASSET = "https://github.com/ncbo/kg-bioportal/releases/latest/download/{id}.tar.gz"


def _safe_extract(tar, dest):
    # Content is our own trusted release asset; use the 'data' filter where available.
    try:
        tar.extractall(dest, filter="data")
    except TypeError:
        tar.extractall(dest)


def fetch(acr, outdir, flat):
    url = ASSET.format(id=acr)
    dest = outdir if flat else os.path.join(outdir, acr)
    os.makedirs(dest, exist_ok=True)
    tmp = os.path.join(tempfile.gettempdir(), f"{acr}.tar.gz")
    try:
        urllib.request.urlretrieve(url, tmp)
    except urllib.error.HTTPError as e:
        print(f"  {acr}: download failed (HTTP {e.code}). "
              f"Only successfully-transformed (OK) graphs have an asset. {url}")
        return False
    with tarfile.open(tmp, "r:gz") as t:
        _safe_extract(t, dest)
    os.remove(tmp)
    got = sorted(f for f in os.listdir(dest) if f.startswith(acr))
    print(f"  {acr}: {', '.join(got)} -> {dest}/")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("acronyms", nargs="+")
    ap.add_argument("-o", "--output-dir", default=".")
    ap.add_argument("--flat", action="store_true", help="extract into output dir without per-graph subdirs")
    a = ap.parse_args()
    ok = sum(fetch(x.upper(), a.output_dir, a.flat) for x in a.acronyms)
    print(f"{ok}/{len(a.acronyms)} graphs fetched into {a.output_dir}/")
    if ok < len(a.acronyms):
        sys.exit(1)


if __name__ == "__main__":
    main()
