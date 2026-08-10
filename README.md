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
  (`--max_source_mb`, default 100 MB).
- **`too_slow`** — the transform exceeded the per-ontology wall-clock cap
  (`--timeout_min`, default 30 min).

These thresholds are tunable via config, CLI flags, or the environment
(`KGBP_MAX_SOURCE_MB`, `KGBP_TIMEOUT_MIN`).

## What BioPortal won't give us, and why

Some ontologies never reach the transform because BioPortal doesn't serve a
source file. The download endpoint's status code says which case it is, and
each gets its own reason:

- **`license_restricted`** (HTTP 401/403) — the ontology is only available
  under a license we don't hold, typically UMLS. **Not a failure**: there is
  nothing to fix and nothing to retry.
- **`no_download_file`** (HTTP 404) — BioPortal has a record and a submission,
  but no source file is attached to it.
- **`download_http_error`** (any other non-2xx) — an unexpected response; the
  code is recorded so it can be told apart from the above.
- **`not_downloadable`** (2xx, no `Content-Disposition`) — BioPortal answered,
  but not with a file. The genuinely ambiguous remainder.
- **`no_submission`** — the ontology record exists but has no submission.
- **`metadata_http_error`** — the ontology's metadata couldn't be retrieved.

The response code is kept in the `http_status` field of both
`download_report.tsv` and the affected `onto_stats.yaml` entries.

`total_stats.yaml` counts license-restricted ontologies on their own
`licensedcount` line, and **excludes them from `failedcount`** — they are
unavailable by design, so counting them as failures overstates how much of the
pipeline is broken. Their `onto_stats.yaml` entries still read `status: Failed`,
since no KGX artifact exists for them either way.

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
