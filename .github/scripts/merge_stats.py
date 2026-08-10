#!/usr/bin/env python3
"""Merge per-shard onto_stats.yaml fragments into repo-wide stats.

Usage: merge_stats.py <fragments_dir> <output_dir> [transform_date] [base_onto_stats] [release_tag]

Reads every onto_stats.yaml under <fragments_dir> (one per transform shard),
optionally seeds from an existing index (<base_onto_stats>, the previous latest
release's onto_stats — carries every ontology's download_url), overlays this
run's results, sets each of this run's OK entries' download_url to <release_tag>,
adds the statically skiplisted giants as Skipped/skiplist rows, and writes the
merged onto_stats.yaml + total_stats.yaml into <output_dir>.

The merged index is authoritative across releases: each OK entry's download_url
points at whichever release holds that ontology's most recent artifact.

Depends only on PyYAML. The skiplist is loaded directly from the package's
config.py by path, so this script needs no heavy dependencies installed.
"""
import glob
import importlib.util
import os
import sys

import yaml


def load_config(repo_root):
    """Import src/kg_bioportal/config.py without installing the package.

    Keeps the skiplist and the license-restricted reason string in one place
    rather than duplicating them here.
    """
    config_path = os.path.join(repo_root, "src", "kg_bioportal", "config.py")
    spec = importlib.util.spec_from_file_location("kgbp_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    config = load_config(repo_root)

    def asset_url(tag, onto_id):
        return f"https://github.com/ncbo/kg-bioportal/releases/download/{tag}/{onto_id}.tar.gz"

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
            if entry.get("status") == "OK" and release_tag:
                entry["download_url"] = asset_url(release_tag, entry["id"])
            else:
                entry.pop("download_url", None)  # no artifact for non-OK
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

    ok = sum(1 for o in ontologies if o.get("status") == "OK")
    skipped = sum(1 for o in ontologies if o.get("status") == "Skipped")
    # License-restricted entries stay status Failed (no artifact exists) but are
    # counted separately and excluded from failedcount — see transformer.py.
    licensed = sum(
        1 for o in ontologies if o.get("reason") == config.LICENSE_RESTRICTED_REASON
    )
    failed = sum(1 for o in ontologies if o.get("status") == "Failed") - licensed
    with open(os.path.join(output_dir, "total_stats.yaml"), "w") as f:
        f.write(f"totalcount: {ok}\n")
        f.write(f"skippedcount: {skipped}\n")
        f.write(f"failedcount: {failed}\n")
        f.write(f"licensedcount: {licensed}\n")
        f.write(f"totalnodecount: {sum(o.get('nodecount', 0) for o in ontologies)}\n")
        f.write(f"totaledgecount: {sum(o.get('edgecount', 0) for o in ontologies)}\n")
        if transform_date:
            f.write(f"transform_date: {transform_date}\n")

    print(f"OK={ok} Skipped={skipped} Failed={failed} Licensed={licensed} -> {output_dir}/")


if __name__ == "__main__":
    main()
