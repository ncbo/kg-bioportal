#!/usr/bin/env python3
"""List KG-Bioportal graphs from the latest release.

Fetches onto_stats.yaml from the latest GitHub release and prints the graphs.
By default shows only those successfully transformed (status OK), with node/edge
counts and download URLs.

Usage:
  python list_graphs.py                  # OK graphs, sorted by name
  python list_graphs.py --all            # include Failed / Skipped
  python list_graphs.py --status Failed  # only a given status
  python list_graphs.py --sort nodes     # sort by node count (desc)
  python list_graphs.py --json           # machine-readable JSON
"""
import argparse
import json
import sys
import urllib.request

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

RELEASE = "https://github.com/ncbo/kg-bioportal/releases/latest/download"

# There is no RELEASE + "/<ID>.tar.gz": releases are incremental and no single one
# holds every artifact, so each entry's own download_url is the only reliable answer.


def load_stats():
    with urllib.request.urlopen(RELEASE + "/onto_stats.yaml", timeout=60) as r:
        return (yaml.safe_load(r.read()) or {}).get("ontologies", [])


def fmt(n):
    return f"{n:,}" if isinstance(n, int) and n else "-"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="include Failed/Skipped")
    ap.add_argument("--status", help="only this status (OK/Failed/Skipped)")
    ap.add_argument("--sort", choices=["name", "nodes", "edges"], default="name")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    onts = load_stats()
    if a.status:
        onts = [o for o in onts if o.get("status") == a.status]
    elif not a.all:
        onts = [o for o in onts if o.get("status") == "OK"]

    keys = {
        "name": lambda o: (o.get("name") or o["id"]).lower(),
        "nodes": lambda o: -(o.get("nodecount") or 0),
        "edges": lambda o: -(o.get("edgecount") or 0),
    }
    onts.sort(key=keys[a.sort])

    if a.json:
        # Each OK entry carries its own download_url (which release it lives in).
        # Entries without one come from an index predating the field; report that
        # honestly rather than inventing a URL that would 404.
        print(json.dumps(onts, indent=2))
        return

    # STATUS/NODES/EDGES describe the base graph (imports stripped). FULL is the
    # full graph (imports merged in): its node/edge counts, "=base" when the
    # ontology has no imports, "-" when none was built or attempted, and an
    # import-only base graph is flagged, since it holds only the header.
    def full(o):
        if o.get("full_status") == "OK":
            return f"{fmt(o.get('full_nodecount'))}/{fmt(o.get('full_edgecount'))}"
        if o.get("full_reason") == "no_imports":
            return "=base"
        return o.get("full_reason") or "-"

    print(f"{'ID':24} {'STATUS':8} {'NODES':>11} {'EDGES':>11}  {'FULL (nodes/edges)':22}  NAME")
    for o in onts:
        status = "IMPORT-ONLY" if o.get("reason") == "import_only" else o.get("status", "")
        print(f"{o['id']:24} {status:8} "
              f"{fmt(o.get('nodecount')):>11} {fmt(o.get('edgecount')):>11}  {full(o):22}  {o.get('name') or ''}")
    unresolved = sum(1 for o in onts
                     if o.get("status") == "OK" and not o.get("download_url"))
    print(f"\n{len(onts)} graphs. Each OK entry's download_url (in onto_stats / --json) points at "
          f"whichever release holds its most recent artifact; "
          f"graph_urls.tsv on the latest release is the same mapping for shell use.")
    if unresolved:
        print(f"{unresolved} OK entries have no recorded download_url.")


if __name__ == "__main__":
    main()
