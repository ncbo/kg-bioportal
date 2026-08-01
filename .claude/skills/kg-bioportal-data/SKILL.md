---
name: kg-bioportal-data
description: >
  Find, download, and load KG-Bioportal knowledge graphs — BioPortal ontologies
  transformed to KGX (node/edge TSVs), published as GitHub Release assets. Use this
  skill whenever the user wants to list which ontology graphs are available, download
  a specific ontology's KGX graph, load KG-Bioportal nodes/edges into pandas / DuckDB /
  networkx / kgx, or understand the KG-Bioportal data model (releases, onto_stats,
  node/edge columns, provenance). Also the foundation for merging graphs (see the
  kg-bioportal-merge skill).
---

# Working with KG-Bioportal graph data

KG-Bioportal transforms BioPortal ontologies into [KGX](https://github.com/biolink/kgx)
graphs (nodes + edges as Biolink-typed TSVs) and publishes them as **GitHub Release
assets**. This skill covers finding, fetching, and loading those graphs.

## When this skill applies

- "What KG-Bioportal graphs are available?" / "list the ontologies with the most nodes"
- "Download the GO (or AGRO, CHEBI, …) graph"
- "Load the KG-Bioportal edges into pandas / a dataframe / DuckDB / networkx"
- Any task that needs the KG-Bioportal node/edge data as a starting point.

## Background — the data model

Everything lives on the latest release of `ncbo/kg-bioportal`, reachable at stable URLs:

- **Per-graph artifact:** `https://github.com/ncbo/kg-bioportal/releases/latest/download/<ID>.tar.gz`
  — contains `<ID>_nodes.tsv` and `<ID>_edges.tsv`. `<ID>` is the BioPortal acronym (uppercase),
  e.g. `GO`, `AGRO`, `UBERON`. Only successfully-transformed (status `OK`) ontologies have an asset.
- **Inventory:** `.../releases/latest/download/onto_stats.yaml` — one entry per ontology with
  `id, name, version, status (OK/Failed/Skipped), reason, nodecount, edgecount, submission_id`.
- **Totals:** `.../releases/latest/download/total_stats.yaml` — `totalcount, skippedcount,
  failedcount, totalnodecount, totaledgecount, transform_date`.

Provenance: nodes have a `provided_by` column and edges a `knowledge_source` column; both currently
hold the source file name (`<ID>_relaxed.owl`), which identifies the source ontology. A couple of
quirks to know: edge `id` is usually empty and edge `category` is often blank. See
`references/data-model.md` for the exact columns and example rows.

## Workflow

### 1. See what's available
```bash
python scripts/list_graphs.py                 # OK graphs, by name
python scripts/list_graphs.py --sort nodes    # biggest first
python scripts/list_graphs.py --all           # include Failed/Skipped (with reasons)
python scripts/list_graphs.py --json          # machine-readable, incl. download_url
```
This reads `onto_stats.yaml` from the release. To browse visually instead, the same data is at
https://ncbo.github.io/kg-bioportal/graphs/ .

### 2. Download one or more graphs
```bash
python scripts/fetch_graph.py GO AGRO             # -> ./GO/GO_nodes.tsv, ./AGRO/AGRO_nodes.tsv …
python scripts/fetch_graph.py GO -o data/graphs   # into a directory
```
Or by hand: `curl -L .../releases/latest/download/GO.tar.gz | tar xz`.

### 3. Load the data
KGX TSVs are plain tab-separated files — load them however suits the task:
```python
import pandas as pd
nodes = pd.read_csv("GO/GO_nodes.tsv", sep="\t", dtype=str)
edges = pd.read_csv("GO/GO_edges.tsv", sep="\t", dtype=str)
# nodes: id, category, name, provided_by, …   edges: subject, predicate, object, relation, knowledge_source
```
Other good options: **DuckDB** (`SELECT ... FROM read_csv_auto('GO_edges.tsv', delim='\t')`) for
SQL over big edge tables; **networkx** for graph algorithms; **kgx** itself
(`kgx.transformer`) to convert to RDF / JSON-L / Neo4j. See `references/data-model.md`.

### 4. To combine multiple graphs
Fetch the ones you want, then use the **kg-bioportal-merge** skill — it wraps cat-merge / KGX
merge and produces a QC report over the combined graph.

## Notes
- A graph you expected may be missing because its transform Failed or was Skipped (too large / too
  slow). `list_graphs.py --all` shows the status and reason; its BioPortal source is still available
  at `https://bioportal.bioontology.org/ontologies/<ID>`.
- Counts and `transform_date` reflect the latest transform run recorded in `total_stats.yaml`.
