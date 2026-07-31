# KG-Bioportal

[BioPortal](https://bioportal.bioontology.org/), as a set of knowledge graphs.

KG-Bioportal downloads BioPortal ontologies and transforms each into
[KGX](https://github.com/biolink/kgx) nodes/edges (TSV), so they can be used as
graphs. The transforms run on GitHub Actions and the results are published as
assets on this repository's [Releases](../../releases).

## Getting the graphs

Each transformed ontology is a `<ACRONYM>.tar.gz` release asset containing
`<ACRONYM>_nodes.tsv` and `<ACRONYM>_edges.tsv`. The latest build is always
reachable at a stable URL:

```
https://github.com/ncbo/kg-bioportal/releases/latest/download/<ACRONYM>.tar.gz
```

For example, AGRO: `.../releases/latest/download/AGRO.tar.gz`.

Per-ontology status and node/edge counts live in `onto_stats.yaml`
(and totals in `total_stats.yaml`), attached to the release and committed under
`docs/`.

## What gets skipped, and why

GitHub-hosted runners are bounded (~16 GB RAM, 6 h per job), so the largest and
slowest ontologies can't be transformed there. They are skipped and recorded in
the stats with a reason, rather than failing the build:

- **`skiplist`** — a known giant, skipped up front with no download attempt
  (e.g. NCBITAXON, SNOMEDCT, RXNORM, GAZ, PR, NCIT, …). See `KNOWN_GIANTS` in
  [`src/kg_bioportal/config.py`](src/kg_bioportal/config.py).
- **`too_large`** — the downloaded source exceeded the size gate
  (`--max_source_mb`, default 50 MB).
- **`too_slow`** — the transform exceeded the per-ontology wall-clock cap
  (`--timeout_min`, default 30 min).

These thresholds are tunable via config, CLI flags, or the environment
(`KGBP_MAX_SOURCE_MB`, `KGBP_TIMEOUT_MIN`).

## How the build runs

`.github/workflows/transform.yml` runs monthly (and on demand via
**Run workflow**). It:

1. **prepare** — fetches the ontology list, drops the skiplist, splits the rest
   into shards, and creates the release.
2. **transform** — a parallel matrix (one job per shard) downloads and transforms
   its ontologies and uploads the `<ACRONYM>.tar.gz` assets to the release.
3. **finalize** — merges the per-shard stats and attaches/commits
   `onto_stats.yaml` + `total_stats.yaml`.

The workflow needs a repository secret **`NCBO_API_KEY`** (a BioPortal / NCBO
API key). Use the **ontologies** input (e.g. `AGRO SEPIO PO`) to test a handful
without running the full set.

## Running locally

```bash
pip install .
export NCBO_API_KEY=...   # from https://bioportal.bioontology.org/account

# Download a few ontologies (honors the size gate + skiplist)
kgbioportal download -d "AGRO SEPIO" -o data/raw -k "$NCBO_API_KEY" --max_source_mb 50

# Transform them to KGX (honors the per-ontology time cap)
kgbioportal transform -i data/raw -o data/transformed --timeout_min 30
```

Transforming requires Java (for [ROBOT](http://robot.obolibrary.org/), downloaded
automatically on first run).

## Data Sources

Source data is derived from the BioPortal API
(<https://data.bioontology.org/documentation>).
