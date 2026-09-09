#!/usr/bin/env python3
"""Merge per-shard onto_stats.yaml fragments into repo-wide stats.

Usage: merge_stats.py <fragments_dir> <output_dir> [transform_date] [base_onto_stats] [release_tag]

Reads every onto_stats.yaml under <fragments_dir> (one per transform shard),
optionally seeds from an existing index (<base_onto_stats>, the previous latest
release's onto_stats — carries every ontology's download_url), overlays this
run's results, sets each of this run's OK entries' download_url (and each OK
full graph's full_download_url) to <release_tag>, adds the statically
skiplisted giants as Skipped/skiplist rows, and writes the merged
onto_stats.yaml + total_stats.yaml + graph_urls.tsv into <output_dir>.

The merged index is authoritative across releases: each OK entry's download_url
points at whichever release holds that ontology's most recent artifact. There is
no release that holds them all — GitHub caps a release at 1000 assets and there
are more transformed ontologies than that — so resolving through the index is
the only way to find an artifact. graph_urls.tsv is that same mapping in a form
a shell can read without a YAML parser: one row per OK ontology, its base
graph's URL in the second column and its full graph's (if one was built) in the
third.

Depends only on PyYAML. The skiplist, the reason vocabulary and the totals
are loaded from the package source tree by path (config.py and stats.py import
nothing heavy), so this script needs no other dependencies installed.
"""
import glob
import os
import sys

import yaml


def load_package(repo_root):
    """Import the package's light modules without installing it.

    Keeps the skiplist, the reason strings and the totals in one place rather
    than duplicating them here. ``kg_bioportal.config`` and ``kg_bioportal.stats``
    import nothing beyond the standard library; the heavy modules are never
    touched.
    """
    sys.path.insert(0, os.path.join(repo_root, "src"))
    from kg_bioportal import config, stats  # noqa: E402

    return config, stats


def main():
    fragments_dir = sys.argv[1] if len(sys.argv) > 1 else "fragments"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "docs"
    # Site-wide transform date (shared by all artifacts in this build), passed by
    # the workflow. Optional so the script stays runnable locally.
    transform_date = sys.argv[3] if len(sys.argv) > 3 else ""
    # Optional existing onto_stats.yaml to seed from, so a targeted re-run of a
    # subset of ontologies updates those entries without discarding the rest.
    base_path = sys.argv[4] if len(sys.argv) > 4 else ""
    # This run's release tag. Every OK ontology transformed in this run gets a
    # download_url pointing at this release; seeded (unchanged) entries keep the
    # download_url they already have (which release they actually live in).
    release_tag = sys.argv[5] if len(sys.argv) > 5 else ""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config, stats = load_package(repo_root)

    def asset_url(tag, onto_id, suffix=""):
        return f"https://github.com/ncbo/kg-bioportal/releases/download/{tag}/{onto_id}{suffix}.tar.gz"

    os.makedirs(output_dir, exist_ok=True)

    by_id = {}

    # Seed from the existing stats first (incremental / targeted re-runs).
    if base_path and os.path.exists(base_path):
        with open(base_path) as f:
            base = yaml.safe_load(f) or {}
        for entry in base.get("ontologies", []):
            by_id[entry["id"]] = entry
        print(f"Seeded {len(by_id)} entries from existing {base_path}.")

    # Overlay this run's shard fragments (they win over the seeded entries).
    fragment_files = sorted(glob.glob(os.path.join(fragments_dir, "**", "onto_stats.yaml"), recursive=True))
    fresh = 0
    for path in fragment_files:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("ontologies", []):
            # This run's OK graphs live in this run's release; record where.
            # The base and full graphs are separate assets, resolved separately:
            # a full graph can fail while the base graph beside it is fine.
            if entry.get("status") == "OK" and release_tag:
                entry["download_url"] = asset_url(release_tag, entry["id"])
            else:
                entry.pop("download_url", None)  # no artifact for non-OK
            if entry.get("full_status") == "OK" and release_tag:
                entry["full_download_url"] = asset_url(
                    release_tag, entry["id"], config.FULL_SUFFIX
                )
            else:
                entry.pop("full_download_url", None)
            by_id[entry["id"]] = entry
            fresh += 1
    print(f"Merged {len(fragment_files)} fragments ({fresh} entries) -> {len(by_id)} ontologies total.")

    # Ensure the skiplisted giants are represented (they are removed before
    # sharding, so no shard reports them).
    for acr in sorted(config.KNOWN_GIANTS):
        by_id.setdefault(
            acr,
            {
                "id": acr,
                "status": "Skipped",
                "reason": "skiplist",
                "name": "",
                "version": "",
                "nodecount": 0,
                "edgecount": 0,
                "submission_id": "NA",
                "source_bytes": 0,
            },
        )

    ontologies = [by_id[k] for k in sorted(by_id)]

    with open(os.path.join(output_dir, "onto_stats.yaml"), "w") as f:
        yaml.dump({"ontologies": ontologies}, f, sort_keys=False)

    # Shell-readable resolver: acronym -> the release that actually holds its
    # artifact. Published on every release so `latest/download/graph_urls.tsv`
    # is a stable entry point even though `latest/download/<ACRONYM>.tar.gz`
    # cannot be (no single release can hold every artifact). The third column
    # is the full graph's URL, empty where none was built; readers that only
    # ever took the second column still get the base graph.
    resolvable = [o for o in ontologies if o.get("status") == "OK" and o.get("download_url")]
    with open(os.path.join(output_dir, "graph_urls.tsv"), "w") as f:
        f.write("id\tdownload_url\tfull_download_url\n")
        for o in resolvable:
            f.write(f"{o['id']}\t{o['download_url']}\t{o.get('full_download_url', '')}\n")
    missing = [
        o["id"] for o in ontologies
        if o.get("status") == "OK" and not o.get("download_url")
    ]
    if missing:
        print(f"WARNING: {len(missing)} OK ontologies have no download_url: {missing[:10]}")
    missing_full = [
        o["id"] for o in ontologies
        if o.get("full_status") == "OK" and not o.get("full_download_url")
    ]
    if missing_full:
        print(f"WARNING: {len(missing_full)} OK full graphs have no full_download_url: {missing_full[:10]}")

    # One definition of the totals, shared with the per-shard stats the
    # transformer writes — see kg_bioportal/stats.py.
    totals = stats.summarize(ontologies)
    with open(os.path.join(output_dir, "total_stats.yaml"), "w") as f:
        for key, value in totals.items():
            f.write(f"{key}: {value}\n")
        if transform_date:
            f.write(f"transform_date: {transform_date}\n")

    print(
        f"OK={totals['totalcount']} Skipped={totals['skippedcount']} "
        f"Failed={totals['failedcount']} Licensed={totals['licensedcount']} "
        f"ImportOnly={totals['importonlycount']} Full={totals['fullcount']} "
        f"resolvable={len(resolvable)} -> {output_dir}/"
    )


if __name__ == "__main__":
    main()
