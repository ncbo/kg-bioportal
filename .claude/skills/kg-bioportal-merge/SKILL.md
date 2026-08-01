---
name: kg-bioportal-merge
description: >
  Merge a set of KG-Bioportal knowledge graphs (BioPortal ontologies as KGX) into one
  combined graph, using cat-merge (recommended, with a QC report) or KGX merge. Use this
  skill whenever the user wants to combine / merge / integrate multiple ontology graphs,
  build a unified KG from several BioPortal ontologies, deduplicate nodes across ontologies,
  or find dangling cross-ontology edges. Builds on the kg-bioportal-data skill for fetching
  the source graphs.
---

# Merging KG-Bioportal graphs

Each KG-Bioportal graph is a single ontology in KGX. Because ontologies cross-reference each
other (an edge in one whose target lives in another), merging a chosen set produces a richer,
connected graph — and the merge's **QC report** tells you where the seams are.

## When this skill applies

- "Merge AGRO, PO and ENVO into one graph"
- "Combine these ontologies and tell me what's dangling / duplicated"
- "Build a single KG from the plant-related ontologies"
- "Deduplicate nodes shared across these ontologies"

## Background — two merge tools

- **[cat-merge](https://github.com/monarch-initiative/cat-merge)** (recommended): the Monarch
  merge tool. Concatenates the node/edge sets, **deduplicates nodes by id**, and writes a **QC
  report** that flags duplicate nodes, duplicate edges, and **dangling edges** (edges whose
  `subject` or `object` node is not present in the merged set). Dangling edges are the key signal:
  they usually point at a term in an ontology you didn't include.
- **[KGX](https://github.com/biolink/kgx) merge**: KGX's own merge, driven by a YAML config
  (see the repo's `/merge.yaml` for the shape). Produces a merged TSV and graph stats via
  `kgx.graph_operations.summarize_graph`. Use when you want KGX-native output/stats or a
  declarative source list rather than a QC report.

Both consume the same input: `<ID>_nodes.tsv` + `<ID>_edges.tsv` files (from the
kg-bioportal-data skill). See `references/cat-merge-vs-kgx.md` for details, the QC-report fields,
and an annotated `merge.yaml` template.

## Workflow

### 1. Choose the ontologies
By acronym. To discover options, use the **kg-bioportal-data** skill
(`list_graphs.py`) — only `status: OK` graphs can be merged.

### 2. Merge with cat-merge (recommended)
`scripts/merge_kgs.py` fetches the graphs from the release and runs cat-merge in one step:
```bash
pip install cat-merge
python scripts/merge_kgs.py AGRO PO ENVO --name plant-merge
#   -> merge_output/plant-merge.tar.gz  and  merge_output/qc_report.yaml
```
`--all-ok` merges every OK graph (large and slow — hundreds of graphs, millions of edges).

If you already have the TSVs locally (e.g. via `fetch_graph.py --flat -o merge_input`), call
cat-merge directly. Its `merge()` takes explicit node/edge file **lists** (not an input dir):
```python
import glob
from cat_merge.merge import merge
nodes = sorted(glob.glob("merge_input/*_nodes.tsv"))
edges = sorted(glob.glob("merge_input/*_edges.tsv"))
merge(name="plant-merge", nodes=nodes, edges=edges, output_dir="merge_output")
```

### 3. Read the QC report
Open `merge_output/qc_report.yaml`. Focus on:
- **dangling edges** — a reference to a node not in the set. Grouped by source, this tells you
  *which ontology to add next* (e.g. lots of edges pointing at `CHEBI:*` → add CHEBI). Fetch it and
  re-merge.
- **duplicate nodes** — the same CURIE contributed by more than one ontology. Usually expected
  (shared upper-level terms); confirms the ontologies actually connect.
- **duplicate edges** — identical subject/predicate/object from multiple sources; typically fine.

### 4. (Alternative) KGX merge
When you want KGX-native output: generate a `merge.yaml` (one `source` block per graph, following
`/merge.yaml`) and run:
```bash
pip install kgx
kgx merge --merge-config merge.yaml
```
See `references/cat-merge-vs-kgx.md` for a ready-to-edit template.

## Notes
- Provenance columns hold the source file name (`<ID>_relaxed.owl`); if you want clean per-source
  provenance in the merged graph, normalize `provided_by` / `knowledge_source` to the acronym or
  `infores:bioportal` before merging (see the kg-bioportal-data data-model reference).
- The dormant `merge` / `catmerge` commands in `src/kg_bioportal/cli.py` are the CLI equivalents of
  this workflow; this skill calls the tools directly rather than depending on that (unrevived) code.
- Merging the full corpus is heavy; prefer a purposeful subset unless you truly need everything.
