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

RELEASE = "https://github.com/ncbo/kg-bioportal/releases/latest/download"

# Releases are incremental and no single one holds every artifact (GitHub caps a
# release at 1000 assets), so RELEASE + "/<ID>.tar.gz" 404s for nearly every
# ontology. Always resolve through the index.


def load_index():
    """Map acronym -> download_url, from the latest release.

    graph_urls.tsv is the resolver and needs no third-party parser; onto_stats.yaml
    is the same mapping with everything else attached, used only as a fallback for
    releases published before the TSV existed.
    """
    try:
        with urllib.request.urlopen(RELEASE + "/graph_urls.tsv", timeout=60) as r:
            rows = r.read().decode("utf-8").splitlines()
        index = {}
        for line in rows[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) == 2 and parts[1]:
                index[parts[0]] = parts[1]
        if index:
            return index
    except Exception:
        pass
    try:
        import yaml
        with urllib.request.urlopen(RELEASE + "/onto_stats.yaml", timeout=60) as r:
            onts = (yaml.safe_load(r.read()) or {}).get("ontologies", [])
    except Exception:
        return {}
    return {o["id"]: o.get("download_url") for o in onts
            if o.get("status") == "OK" and o.get("download_url")}


def _safe_extract(tar, dest):
    # Content is our own trusted release asset; use the 'data' filter where available.
    try:
        tar.extractall(dest, filter="data")
    except TypeError:
        tar.extractall(dest)


def fetch(acr, outdir, flat, index):
    url = index.get(acr)
    if not url:
        print(f"{acr}: not in the index — no KGX artifact is published for it "
              f"(it may have failed, been skipped, or not exist).", file=sys.stderr)
        return False
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
    index = load_index()
    ok = sum(fetch(x.upper(), a.output_dir, a.flat, index) for x in a.acronyms)
    print(f"{ok}/{len(a.acronyms)} graphs fetched into {a.output_dir}/")
    if ok < len(a.acronyms):
        sys.exit(1)


if __name__ == "__main__":
    main()
