# cat-merge vs KGX merge, and how to read the results

## Which to use

| | cat-merge | KGX merge |
|---|---|---|
| Input | node/edge TSVs in a directory | node/edge TSVs listed in a YAML config |
| Dedup | dedupes nodes by id | merges by id |
| Output | `<name>.tar.gz` (merged KGX) | merged TSV (+ other formats) |
| QC | **QC report**: duplicate nodes/edges, **dangling edges** | graph stats (counts, facets) |
| Best for | understanding connectivity / gaps between ontologies | KGX-native output + summary stats |
| Install | `pip install cat-merge` | `pip install kgx` |

Rule of thumb: **cat-merge first** — the QC report tells you whether the ontologies you picked
actually connect, and which ontology to add next. Use KGX merge when you specifically want KGX
output formats or `generate_graph_stats` facets.

## cat-merge

`merge()` signature (verified):
`merge(name='merged-kg', source=None, nodes=None, edges=None, mappings=None,
output_dir='merged-output', qc_report=True)`. Pass explicit **file lists** — glob them yourself:

```python
import glob
from cat_merge.merge import merge
nodes = sorted(glob.glob("merge_input/*_nodes.tsv"))
edges = sorted(glob.glob("merge_input/*_edges.tsv"))
merge(name="my-merge", nodes=nodes, edges=edges, output_dir="merge_output")
```
- Writes `merge_output/my-merge.tar.gz` (merged nodes+edges), a `qc/` dir, and a **QC report**
  `merge_output/qc_report.yaml`.
- `mappings=[...]` lets you supply mapping TSVs so cat-merge collapses equivalent nodes during the
  merge (see the bioportal-for-kg-building skill for getting BioPortal mappings).

### Reading `qc_report.yaml`
Top-level keys: `nodes`, `edges` (summary counts), `duplicate_nodes`, `duplicate_edges`,
`dangling_edges`.
- **`dangling_edges`** — edges whose `subject` or `object` node id isn't present among the merged
  nodes. The single most useful signal. Group the missing ids by prefix to see which ontology to
  pull in next (e.g. many missing `CHEBI:*` → add the CHEBI graph and re-merge). Some dangling
  edges are unavoidable (references to terms that live in ontologies you don't need).
- **`duplicate_nodes`** — the same node id from more than one source. Expected when ontologies
  share upper-level terms; it's evidence the graphs overlap/connect.
- **`duplicate_edges`** — identical subject/predicate/object seen in more than one source. Usually
  harmless.

## KGX merge — annotated `merge.yaml` template

One `source` block per graph. Fill in the node/edge TSV paths (e.g. from
`fetch_graph.py -o merge_input`, files land at `merge_input/<ID>/<ID>_nodes.tsv`). Based on the
repo's `/merge.yaml`.

```yaml
---
configuration:
  output_directory: merge_output
  checkpoint: false

merged_graph:
  name: my-merge
  source:
    agro:
      name: "AGRO"
      input:
        format: tsv
        filename:
          - merge_input/AGRO/AGRO_nodes.tsv
          - merge_input/AGRO/AGRO_edges.tsv
    po:
      name: "PO"
      input:
        format: tsv
        filename:
          - merge_input/PO/PO_nodes.tsv
          - merge_input/PO/PO_edges.tsv
  # optional: emit summary stats over the merged graph
  operations:
    - name: kgx.graph_operations.summarize_graph.generate_graph_stats
      args:
        graph_name: my-merge
        filename: merged_graph_stats.yaml
        node_facet_properties:
          - provided_by
        edge_facet_properties:
          - provided_by
          - knowledge_source
  destination:
    merged-kg-tsv:
      format: tsv
      compression: tar.gz
      filename: my-merge
```

Run:
```bash
kgx merge --merge-config merge.yaml
```

## Provenance caveat
KG-Bioportal `provided_by` (nodes) and `knowledge_source` (edges) currently hold the source file
name `<ID>_relaxed.owl`. If you want facets/provenance keyed by ontology acronym or
`infores:bioportal`, rewrite that column in the TSVs before merging (a one-line pandas `.replace`
per file), or post-process the merged output.
