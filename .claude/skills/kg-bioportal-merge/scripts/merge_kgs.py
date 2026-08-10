#!/usr/bin/env python3
"""Merge a set of KG-Bioportal KGX graphs with cat-merge.

Downloads each <ID>.tar.gz from the latest release, extracts the node/edge TSVs
into one input dir, then runs cat-merge to produce a single merged KGX graph plus
a QC report (duplicate nodes/edges, dangling edges).

Requires: pip install cat-merge   (and pyyaml for --all-ok)

Usage:
  python merge_kgs.py AGRO SEPIO PO --name plant-merge
  python merge_kgs.py --all-ok --name kg-bioportal-full     # every OK graph (large, slow)
  python merge_kgs.py GO UBERON --input-dir in --output-dir out
"""
import argparse
import glob
import os
import socket
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

socket.setdefaulttimeout(180)  # don't hang forever on a stalled connection

RELEASE = "https://github.com/ncbo/kg-bioportal/releases/latest/download"

# There is no RELEASE + "/<ID>.tar.gz": releases are incremental and no single one
# holds every artifact (GitHub caps a release at 1000 assets), so that URL 404s for
# nearly every ontology. Always resolve through the index.


def load_index():
    """Map acronym -> download_url from the latest release's onto_stats index.

    Graphs are hosted incrementally across releases; each OK entry records which
    release holds its artifact.
    """
    import yaml
    with urllib.request.urlopen(RELEASE + "/onto_stats.yaml", timeout=60) as r:
        onts = (yaml.safe_load(r.read()) or {}).get("ontologies", [])
    return {o["id"]: o["download_url"] for o in onts
            if o.get("status") == "OK" and o.get("download_url")}


def fetch_tsvs(acr, indir, index):
    url = index.get(acr)
    if not url:
        print(f"  skip {acr}: not in the index — no KGX artifact is published for it")
        return False
    tmp = os.path.join(tempfile.gettempdir(), f"{acr}.tar.gz")
    try:
        urllib.request.urlretrieve(url, tmp)
    except urllib.error.HTTPError as e:
        print(f"  skip {acr}: no asset (HTTP {e.code}) — only OK graphs are downloadable")
        return False
    with tarfile.open(tmp, "r:gz") as t:
        try:
            t.extractall(indir, filter="data")
        except TypeError:
            t.extractall(indir)
    os.remove(tmp)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("acronyms", nargs="*", help="BioPortal acronyms to merge")
    ap.add_argument("--all-ok", action="store_true", help="merge every OK graph (large)")
    ap.add_argument("--name", default="kg-bioportal-merge", help="name for the merged graph")
    ap.add_argument("--input-dir", default="merge_input")
    ap.add_argument("--output-dir", default="merge_output")
    a = ap.parse_args()

    index = load_index()
    ids = sorted(index) if a.all_ok else [x.upper() for x in a.acronyms]
    if not ids:
        sys.exit("Provide one or more acronyms, or --all-ok.")

    try:
        from cat_merge.merge import merge
    except ImportError:
        sys.exit("cat-merge is required: pip install cat-merge")

    os.makedirs(a.input_dir, exist_ok=True)
    got = [x for x in ids if fetch_tsvs(x, a.input_dir, index)]
    print(f"Fetched {len(got)}/{len(ids)} graphs into {a.input_dir}/")
    if not got:
        sys.exit("Nothing to merge.")

    # cat-merge takes explicit node/edge file lists; dedupes nodes and writes
    # <name>.tar.gz + a QC report to output_dir.
    nodes = sorted(glob.glob(os.path.join(a.input_dir, "*_nodes.tsv")))
    edges = sorted(glob.glob(os.path.join(a.input_dir, "*_edges.tsv")))
    merge(name=a.name, nodes=nodes, edges=edges, output_dir=a.output_dir)

    print(f"\nMerged graph + QC report written to {a.output_dir}/:")
    for f in sorted(os.listdir(a.output_dir)):
        print("  ", f)
    print("\nRead qc_report.yaml for duplicate nodes/edges and dangling edges "
          "(edges whose subject/object node isn't in the merged set).")


if __name__ == "__main__":
    main()
