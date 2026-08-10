# KG-Bioportal data model reference

## Where the data lives — the index is authoritative

A GitHub release holds at most 1000 assets, so the corpus is spread across **multiple releases**:
each transform run publishes a release holding only the graphs it (re)transformed. **Don't assume a
fixed per-graph URL** — resolve each graph through the index.

| What | URL |
|------|-----|
| Index (all graphs) | `https://github.com/ncbo/kg-bioportal/releases/latest/download/onto_stats.yaml` |
| Totals | `.../releases/latest/download/total_stats.yaml` |
| A graph | the `download_url` recorded for it in the index (see below) |

The **latest release always carries the full `onto_stats.yaml` index** covering every ontology, and
each `status: OK` entry has a **`download_url`** pointing at whichever release actually holds its most
recent artifact, e.g. `.../releases/download/data-2026.08.01-42/GO.tar.gz`. To get a graph: read the
index, look up its `download_url`, download that. `<ID>` is the BioPortal acronym in **uppercase**;
each tarball contains `<ID>_nodes.tsv` and `<ID>_edges.tsv`.

The latest release also carries **`graph_urls.tsv`** — the same `<ID>` → artifact-URL mapping as a
two-column TSV with one header line. Prefer it when you don't need the rest of the index or don't
want a YAML parser:

```bash
BASE=https://github.com/ncbo/kg-bioportal/releases/latest/download
URL=$(curl -sL "$BASE/graph_urls.tsv" | awk -F'\t' '$1=="AGRO"{print $2}')
curl -LO "$URL"
```

Release tags are unique per run (`data-YYYY.MM.DD-<run>`). Only `status: OK` ontologies have an
artifact.

> `.../releases/latest/download/<ID>.tar.gz` does **not** work and never reliably did. `latest` is
> just the most recent run's release, holding only that run's artifacts, and no single release can
> hold them all (GitHub caps a release at 1000 assets; there are more transformed ontologies than
> that). Always resolve through `graph_urls.tsv` or the index's `download_url`.

## `onto_stats.yaml`

```yaml
ontologies:
- id: AGRO                # BioPortal acronym (also the asset name <ID>.tar.gz)
  name: AGRonomy Ontology # human name from BioPortal
  version: '2023-08-14'   # BioPortal submission version string ('NA' if none)
  status: OK              # OK | Failed | Skipped
  reason: ''              # why non-OK: transform_error | too_large | too_slow |
                          #   skiplist | not_downloadable | no_submission
  nodecount: 5102         # 0 unless status OK
  edgecount: 8691
  submission_id: '6'      # BioPortal submission id
  source_bytes: 7501012   # size of the source ontology file
  download_url: https://github.com/ncbo/kg-bioportal/releases/download/data-2026.08.01-42/AGRO.tar.gz
                          # OK entries only; the release+asset holding this graph's newest artifact
```

`total_stats.yaml`:
```yaml
totalcount: 987       # OK
skippedcount: 43
failedcount: 262
totalnodecount: 3988318
totaledgecount: 7354869
transform_date: 2026-07-31
```

## KGX TSV columns (as produced by KG-Bioportal)

**Nodes** — `<ID>_nodes.tsv`:

| column | meaning | example |
|--------|---------|---------|
| `id` | node CURIE | `OBO:AGRO_00000002` |
| `category` | Biolink category | `biolink:NamedThing` |
| `name` | label | `tillage process` |
| `description` | definition | `A planned process in which soil is …` |
| `provided_by` | source (see note) | `AGRO_relaxed.owl` |
| `synonym`, `exact_synonym`, `broad_synonym`, `narrow_synonym`, `related_synonym` | synonyms | (often blank) |

**Edges** — `<ID>_edges.tsv`:

| column | meaning | example |
|--------|---------|---------|
| `id` | edge id | *(usually empty)* |
| `subject` | source node CURIE | `OBO:AGRO_00000002` |
| `predicate` | Biolink predicate | `biolink:subclass_of` |
| `object` | target node CURIE | `OBO:AGRO_00000108` |
| `category` | Biolink edge category | *(often empty)* |
| `relation` | original relation CURIE | `rdfs:subClassOf` |
| `knowledge_source` | source (see note) | `AGRO_relaxed.owl` |

### Provenance note (important)
Both `provided_by` (nodes) and `knowledge_source` (edges) currently contain the **relaxed OWL file
name** (`<ID>_relaxed.owl`), an artifact of the ROBOT→KGX step, rather than the acronym or an
`infores:` CURIE. It still uniquely identifies the source ontology (strip `_relaxed.owl`). If you
need clean per-source provenance in a merged graph, rewrite this column to the acronym or
`infores:bioportal` before/after merging.

### Other characteristics
- Node ids are CURIEs; prefixes vary by ontology (`OBO:`, ontology-specific prefixes, etc.).
- `predicate` is Biolink-normalized (e.g. `biolink:subclass_of`); `relation` keeps the original
  (e.g. `rdfs:subClassOf`).
- Edge `id` is frequently empty — cat-merge and KGX handle this, but if you need stable edge ids,
  synthesize them (e.g. `subject|predicate|object`).
- These are single-ontology graphs; cross-ontology references appear as edges whose `object` (or
  `subject`) is a CURIE not present as a node in this graph — i.e. **dangling** until you merge in
  the referenced ontology. This is the main signal the merge QC report surfaces.

## Loading recipes

```python
import pandas as pd
nodes = pd.read_csv("GO/GO_nodes.tsv", sep="\t", dtype=str, keep_default_na=False)
edges = pd.read_csv("GO/GO_edges.tsv", sep="\t", dtype=str, keep_default_na=False)
```

```sql
-- DuckDB, good for large edge tables
SELECT predicate, count(*) FROM read_csv_auto('GO_edges.tsv', delim='\t', header=true)
GROUP BY predicate ORDER BY 2 DESC;
```

```python
# networkx
import networkx as nx, pandas as pd
e = pd.read_csv("GO_edges.tsv", sep="\t", dtype=str, keep_default_na=False)
G = nx.from_pandas_edgelist(e, "subject", "object", edge_attr=["predicate"], create_using=nx.MultiDiGraph)
```

```python
# kgx — convert to other formats (RDF, JSON-L, Neo4j)
from kgx.transformer import Transformer
t = Transformer()
t.transform({"filename": ["GO_nodes.tsv", "GO_edges.tsv"], "format": "tsv"})
t.save({"filename": "GO.json", "format": "json"})
```
