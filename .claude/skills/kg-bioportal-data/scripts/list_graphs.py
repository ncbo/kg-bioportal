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
ASSET = RELEASE + "/{id}.tar.gz"


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
        for o in onts:
            o["download_url"] = ASSET.format(id=o["id"]) if o.get("status") == "OK" else None
        print(json.dumps(onts, indent=2))
        return

    print(f"{'ID':24} {'STATUS':8} {'NODES':>11} {'EDGES':>11}  NAME")
    for o in onts:
        print(f"{o['id']:24} {o.get('status', ''):8} "
              f"{fmt(o.get('nodecount')):>11} {fmt(o.get('edgecount')):>11}  {o.get('name') or ''}")
    print(f"\n{len(onts)} graphs. Download an OK graph from: {ASSET.format(id='<ID>')}")


if __name__ == "__main__":
    main()
