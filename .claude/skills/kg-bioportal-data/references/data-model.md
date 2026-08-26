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
  reason: ''              # why non-OK: transform_error_<stage> | invalid_source |
                          #   too_large | too_slow | skiplist | not_downloadable |
                          #   no_submission.
                          #   invalid_source: the file BioPortal serves cannot be read
                          #   as an ontology at all; `detail` says whether it is broken
                          #   RDF (with the parse error) or valid RDF that ROBOT will
                          #   not load. Not fixable on this side — and the check is
                          #   made against BioPortal's own file, so a source we
                          #   ourselves corrupted while stripping imports is recorded
                          #   as transform_error_convert instead, saying so.
                          #   <stage> is decompress | convert | relax | kgx — which
                          #   step lost the ontology. Entries from runs before this
                          #   was recorded carry a bare `transform_error`.
  detail: ''              # non-OK entries only, and only when there is something to
                          #   say: the message from the stage that failed, on one
                          #   line, truncated to 500 characters. When the message
                          #   names no cause of its own -- "could not load a valid
                          #   ontology from file: X" is true of every unreadable
                          #   file -- the reason that points at a position in the
                          #   file follows it after a ' | '.
  malformed_literals: 0   # present only when non-zero: literals whose lexical
                          #   form does not match their declared datatype (e.g.
                          #   xsd:dateTime '06/09/2012'). A fact about the source,
                          #   not a transform problem -- the values are kept as
                          #   written and the graph is unaffected.
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
| `provided_by` | source ontology, as an infores | `infores:bioportal.agro` |
| `synonym`, `exact_synonym`, `broad_synonym`, `narrow_synonym`, `related_synonym` | synonyms | (often blank) |

**Edges** — `<ID>_edges.tsv`:

| column | meaning | example |
|--------|---------|---------|
| `id` | edge id, `subject-predicate-object` | `OBO:AGRO_00000002-biolink:subclass_of-OBO:AGRO_00000108` |
| `subject` | source node CURIE | `OBO:AGRO_00000002` |
| `predicate` | Biolink predicate | `biolink:subclass_of` |
| `object` | target node CURIE | `OBO:AGRO_00000108` |
| `category` | Biolink edge category | *(often empty)* |
| `relation` | original relation CURIE | `rdfs:subClassOf` |
| `aggregator_knowledge_source` | where we got it | `infores:bioportal` |
| `primary_knowledge_source` | source ontology, as an infores | `infores:bioportal.agro` |

### Provenance note
The ontology is the primary source of its own assertions and BioPortal is the aggregator we got
them from, so edges carry both `primary_knowledge_source` (`infores:bioportal.<acronym>`) and
`aggregator_knowledge_source` (`infores:bioportal`), and nodes carry `provided_by` with the same
per-ontology infores. The acronym is the part after `infores:bioportal.`, lowercased.

**Releases up to and including `data-2026.08.25-12`** instead carry a single `knowledge_source`
column on edges, and a `provided_by` on nodes, both holding the **relaxed OWL file name**
(`<ID>_relaxed.owl`) — an artifact of the ROBOT→KGX step that exists only inside a runner's temp
directory. If you are reading one of those releases, strip `_relaxed.owl` to recover the acronym.

### Other characteristics
- Node ids are CURIEs; prefixes vary by ontology (`OBO:`, ontology-specific prefixes, etc.).
- `predicate` is Biolink-normalized (e.g. `biolink:subclass_of`); `relation` keeps the original
  (e.g. `rdfs:subClassOf`).
- Edge `id` is `subject-predicate-object`, and is present on every edge. In releases up to
  `data-2026.08.25-12` it was empty on most of them: KGX assigned ids only to whole batches of
  10,000 edges and left the remainder blank, so an ontology with fewer than 10,000 edges had none
  at all. The ids are derived, not opaque, so they are stable across runs but not unique across
  ontologies until you namespace them.
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
