# KG-Bioportal

[BioPortal](https://bioportal.bioontology.org/), as a set of knowledge graphs.

KG-Bioportal downloads BioPortal ontologies and transforms each into
[KGX](https://github.com/biolink/kgx) nodes/edges (TSV), so they can be used as
graphs. The transforms run on GitHub Actions and the results are published as
assets on this repository's [Releases](../../releases).

## Getting the graphs

Each transformed ontology is a `<ACRONYM>.tar.gz` release asset containing
`<ACRONYM>_nodes.tsv` and `<ACRONYM>_edges.tsv`.

Releases are **incremental**: a run publishes only the ontologies it transformed,
so an artifact lives in whichever release most recently rebuilt it, and there is
no release that holds them all — GitHub caps a release at 1000 assets, and there
are more transformed ontologies than that. So look the artifact up rather than
guessing its URL. Three files are published on **every** release for this, which
makes `releases/latest/download/<that file>` a stable entry point:

| File | What it is |
|---|---|
| `graph_urls.tsv` | `<ACRONYM>` → artifact URL. Two columns, one header line. |
| `onto_stats.yaml` | Full per-ontology index: status, reason, node/edge counts, `download_url`. |
| `total_stats.yaml` | Site-wide totals. |

To fetch one ontology:

```bash
BASE=https://github.com/ncbo/kg-bioportal/releases/latest/download
URL=$(curl -sL "$BASE/graph_urls.tsv" | awk -F'\t' '$1=="AGRO"{print $2}')
curl -LO "$URL"
```

To fetch all of them:

```bash
curl -sL "$BASE/graph_urls.tsv" | tail -n +2 | cut -f2 | xargs -n1 -P4 curl -sLO
```

From Python, read `download_url` off the entry you want in `onto_stats.yaml`.

> **Note:** `releases/latest/download/<ACRONYM>.tar.gz` does *not* work, despite
> looking like it should. `latest` is just the most recent run's release, which
> holds only that run's handful of artifacts.

## What gets skipped, and why

GitHub-hosted runners are bounded (~16 GB RAM, 6 h per job), so the largest and
slowest ontologies can't be transformed there. They are skipped and recorded in
the stats with a reason, rather than failing the build:

- **`skiplist`** — a known giant, skipped up front with no download attempt
  (e.g. NCBITAXON, SNOMEDCT, RXNORM, GAZ, PR, NCIT, …). See `KNOWN_GIANTS` in
  [`src/kg_bioportal/config.py`](src/kg_bioportal/config.py). Size is not the
  only way to be a giant: CCO is 244 MB, inside the gate, but ships as OBO and
  expands to 15.7M triples, which is what takes the runner down.
- **`too_large`** — the source exceeded the size gate (`--max_source_mb`,
  default 250 MB). Checked twice: on the file as downloaded, and again after
  decompression, since a gzipped source understates its real size by an order
  of magnitude (ROR is 14 MB gzipped and 135 MB unpacked).
- **`too_slow`** — the transform exceeded the per-ontology wall-clock cap
  (`--timeout_min`, default 30 min).

These thresholds are tunable via config, CLI flags, or the environment
(`KGBP_MAX_SOURCE_MB`, `KGBP_TIMEOUT_MIN`).

The 250 MB gate is measured rather than assumed. Every ontology the index held
between 100 and 250 MB was transformed on a standard runner on 2026-08-25 — 20
of them, from HRA at 100 MB to GO-PLUS at 227 MB, each taking 2m32s to 7m49s —
adding roughly 3.1M nodes and 6.6M edges. Raising it further has not been
tested; the next band up starts at FMA (254 MB) and reaches BERO (878 MB).

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
kgbioportal download -d "AGRO SEPIO" -o data/raw -k "$NCBO_API_KEY" --max_source_mb 250

# Transform them to KGX (honors the per-ontology time cap)
kgbioportal transform -i data/raw -o data/transformed --timeout_min 30
```

Transforming requires Java (for [ROBOT](http://robot.obolibrary.org/), downloaded
automatically on first run).

## Data Sources

Source data is derived from the BioPortal API
(<https://data.bioontology.org/documentation>).
