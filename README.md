# KG-Bioportal

[BioPortal](https://bioportal.bioontology.org/), as a set of knowledge graphs.

KG-Bioportal downloads BioPortal ontologies and transforms each into
[KGX](https://github.com/biolink/kgx) nodes/edges (TSV), so they can be used as
graphs. The transforms run on GitHub Actions and the results are published as
assets on this repository's [Releases](../../releases).

## Getting the graphs

Each transformed ontology is published as up to two release assets, after the
OBO Foundry's distinction between an ontology's *base* and *full* releases:

| Asset | What it is | Contains |
|---|---|---|
| `<ACRONYM>.tar.gz` | **Base graph**: the ontology alone, its `owl:imports` stripped before ROBOT sees it. Always built. | `<ACRONYM>_nodes.tsv`, `<ACRONYM>_edges.tsv` |
| `<ACRONYM>_full.tar.gz` | **Full graph**: the ontology with its import closure merged in by `robot merge`. Built when the ontology declares imports and ROBOT can fetch them all. | `<ACRONYM>_full_nodes.tsv`, `<ACRONYM>_full_edges.tsv` |

Base graphs merge cleanly with each other (nothing is counted twice; references
to imported terms are dangling edges until the imported ontology is merged in).
Full graphs stand alone, at the cost of repeating whatever they import. See
[Base and full graphs](#base-and-full-graphs) for what the index says about
each and how a full graph can go missing.

Releases are **incremental**: a run publishes only the ontologies it transformed,
so an artifact lives in whichever release most recently rebuilt it, and there is
no release that holds them all — GitHub caps a release at 1000 assets, and there
are more transformed ontologies than that. So look the artifact up rather than
guessing its URL. Three files are published on **every** release for this, which
makes `releases/latest/download/<that file>` a stable entry point:

| File | What it is |
|---|---|
| `graph_urls.tsv` | `<ACRONYM>` → base graph URL → full graph URL (blank where none). Three columns, one header line. |
| `onto_stats.yaml` | Full per-ontology index: status, reason, node/edge counts, `download_url`, and the same again as `full_*` for the full graph. |
| `total_stats.yaml` | Site-wide totals. |

To fetch one ontology:

```bash
BASE=https://github.com/ncbo/kg-bioportal/releases/latest/download
URL=$(curl -sL "$BASE/graph_urls.tsv" | awk -F'\t' '$1=="AGRO"{print $2}')
curl -LO "$URL"
```

To fetch its full graph instead (the third column; empty if none was built):

```bash
URL=$(curl -sL "$BASE/graph_urls.tsv" | awk -F'\t' '$1=="AGRO"{print $3}')
```

To fetch all base graphs:

```bash
curl -sL "$BASE/graph_urls.tsv" | tail -n +2 | cut -f2 | xargs -n1 -P4 curl -sLO
```

From Python, read `download_url` (base) or `full_download_url` (full) off the
entry you want in `onto_stats.yaml`.

> **Note:** `releases/latest/download/<ACRONYM>.tar.gz` does *not* work, despite
> looking like it should. `latest` is just the most recent run's release, which
> holds only that run's handful of artifacts.

## Base and full graphs

The index describes the two graphs separately. `status`, `reason`, `detail`,
`nodecount`, `edgecount`, the category tallies and `download_url` are the base
graph, as they always were; the full graph gets the same fields under a
`full_` prefix (`full_status`, `full_reason`, `full_detail`, `full_nodecount`,
`full_edgecount`, `full_node_categories`, `full_edge_categories`,
`full_download_url`), plus `imports`, the number of import declarations in the
source, `import_iris`, their targets, and `ontology_iri`, the IRI the ontology
gives itself. The site uses the last two to list each ontology's imports by
name and link the ones that are themselves ontologies here:

```yaml
- id: OBOE
  status: OK
  reason: import_only        # the base graph is only the ontology header
  nodecount: 1
  edgecount: 0
  imports: 3
  import_iris:
  - http://ecoinformatics.org/oboe/oboe.1.2/oboe-core.owl
  - http://ecoinformatics.org/oboe/oboe.1.2/oboe-characteristics.owl
  - http://ecoinformatics.org/oboe/oboe.1.2/oboe-standards.owl
  ontology_iri: http://ecoinformatics.org/oboe/oboe.1.2/oboe.owl
  full_status: OK
  full_reason: ''
  full_nodecount: 509
  full_edgecount: 764
  download_url: https://github.com/ncbo/kg-bioportal/releases/download/<tag>/OBOE.tar.gz
  full_download_url: https://github.com/ncbo/kg-bioportal/releases/download/<tag>/OBOE_full.tar.gz
```

Two things the base graph alone could not tell you, and which the site's
Summary page and each ontology's page now spell out:

- **`reason: import_only`** on an OK base graph. The ontology has no classes of
  its own; everything it describes is pulled in through `owl:imports` (SWEET
  is 224 component files behind one header). Its base graph holds only the
  header: no edges and a handful of nodes (the ontology IRI, a license). The
  artifact is published because it is a faithful base graph, and it is flagged
  because it is useless on its own. The full graph is the one to use. These
  are counted on their own `importonlycount` line in `total_stats.yaml` and
  stay inside `totalcount`, since the artifact exists.
- **A missing full graph**, by `full_reason`:
  - **`no_imports`** (`full_status: Skipped`): the ontology declares no
    imports, so its base graph already is its full graph. Nothing separate is
    built. This is the common case.
  - **`unresolvable_imports`** (`Failed`): an import (or an import's import)
    could not be fetched; the transform log names it. `robot merge` needs the
    whole closure, so one dead URL loses the full graph. The base graph is
    unaffected. This is the failure #121 stripped imports to avoid, moved to
    where it belongs.
  - **`transform_error_<stage>`** (`Failed`): the merged ontology failed at
    `merge` (ROBOT, for a reason other than an import), `relax` or `kgx`;
    `full_detail` carries the message, as `detail` does for the base graph.
  - **`too_slow`** / **`too_large`** (`Skipped`): the merged ontology tripped
    the same gates as below. Each graph gets its own `--timeout_min`, and the
    size gate is applied again to what `robot merge` wrote, since the closure
    can be far larger than what BioPortal served.
  - **No `full_*` fields at all**: no full graph was attempted. Either the
    base graph is not OK (a full graph is only tried on top of a working base),
    or the entry was carried forward from a run before full graphs existed and
    will get one when its BioPortal submission next changes.

`total_stats.yaml` carries `fullcount`, `fullskippedcount` and
`fullfailedcount`. Node and edge totals sum base graphs only; full graphs
repeat whatever they import. `kgbioportal transform --no_full` builds base
graphs only.

## Biolink categories, and how they are decided

KGX writes `biolink:NamedThing` on every node, because an OWL file says
nothing about Biolink. The transform then assigns a more specific class to as
many nodes as the graph's own evidence supports, by four routes, in order:

| Route | What it does | Recorded as |
|---|---|---|
| Seeds | A table in `src/kg_bioportal/categories.py` of terms whose Biolink class is not in doubt (GO's `biological_process`, MONDO's `disease`, BFO's `material entity`). | `seeded` |
| Inheritance | Every class beneath a seed, by `subclass_of` or `skos:broader`, takes its category. The nearest seed wins; a domain seed beats an upper-ontology one at the same distance. | `inherited` |
| Mappings | An `exact_match` edge asserts the same referent, so a category crosses it to a node that has none. | `mapped` |
| Reviewed roots | Roots whose meaning is a fact about one ontology (an ICD chapter, an HGNC locus group) were placed by reading them and their subclasses in the published graph, **with the assistance of an AI agent**, and recorded in `src/kg_bioportal/reviewed_roots.yaml`. | `reviewed` |

A few ontologies that are one kind of thing end to end (GNO, LION, ROR,
FAST-TITLE, EMAP) take that one category as a whole (`defaulted`). Nothing
else is guessed: a node with no evidence stays `NamedThing`.

Every entry in `reviewed_roots.yaml` records the graph release that was read,
the reviewer, the date, the subclass labels that were the evidence, the reach
measured, and a `confirmed_by` field that stays blank until a maintainer has
checked it. Roots that were read and refused are listed with the reason, so
the same root is not re-read later. The bar a root has to clear is
`REVIEW_BAR` in `categories.py`: the labels have to show one Biolink class to
be true of everything beneath, children of mixed kinds mean refusal, and the
top of anything is never seeded for being the top.

To lay out a graph's roots for review:

```bash
kgbioportal roots AGRO.tar.gz --ontology AGRO --output AGRO_roots.yaml
```

The index carries the tally of routes per ontology as `category_sources`
(and `full_category_sources`), and, wherever a reviewed root did any work,
`category_review` with the reviewer, date, graph and confirmation. The site
shows both under *How they were assigned* on the ontology's Nodes tab, with
the disclosure that an AI agent assisted, and the About page describes the
four routes.

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
- **`too_slow`** — the transform exceeded the per-graph wall-clock cap
  (`--timeout_min`, default 30 min). The base and full graph of one ontology
  each get the full cap.

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

Two more come from the connection rather than the response:

- **`download_error`** — the source could not be fetched whole. A byte stream
  that breaks partway is fetched again, up to three times with a pause between
  tries; if it keeps breaking, this is recorded and the shard moves on to the
  next ontology. Before #180 the exception ended the shard and every ontology
  behind it went unrecorded.
- **`metadata_http_error`** also covers a connection that drops on the
  metadata calls, not only a non-200 response.

Both carry the error text in `detail`, as transform failures do. Every request
to BioPortal has a timeout, so a stalled connection costs minutes, not the
rest of the job.

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
   its ontologies and uploads the `<ACRONYM>.tar.gz` and `<ACRONYM>_full.tar.gz`
   assets to the release.
3. **finalize** — merges the per-shard stats and attaches/commits
   `onto_stats.yaml` + `total_stats.yaml`.

The workflow needs a repository secret **`NCBO_API_KEY`** (a BioPortal / NCBO
API key). Use the **ontologies** input (e.g. `AGRO SEPIO PO`) to test a handful
without running the full set, and **full_graphs** to switch full graphs off for
a run.

## Running locally

```bash
pip install .
export NCBO_API_KEY=...   # from https://bioportal.bioontology.org/account

# Download a few ontologies (honors the size gate + skiplist)
kgbioportal download -d "AGRO SEPIO" -o data/raw -k "$NCBO_API_KEY" --max_source_mb 250

# Transform them to KGX (honors the per-graph time cap); --no_full for base graphs only
kgbioportal transform -i data/raw -o data/transformed --timeout_min 30
```

Transforming requires Java (for [ROBOT](http://robot.obolibrary.org/), downloaded
automatically on first run).

## Data Sources

Source data is derived from the BioPortal API
(<https://data.bioontology.org/documentation>).
