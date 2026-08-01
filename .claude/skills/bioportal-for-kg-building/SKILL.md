---
name: bioportal-for-kg-building
description: >
  Use BioPortal (bioportal.bioontology.org / data.bioontology.org API) to build, enrich,
  or align knowledge graphs. Use this skill when the user asks how to turn text into ontology
  terms (Annotator), pick which ontologies to use for a corpus (Recommender), find cross-ontology
  term mappings to align or merge KGs (Mappings), fetch ontology classes / hierarchies / properties
  via the API, or understand how BioPortal ontologies become KG-Bioportal KGX graphs. Covers the
  KG-builder's view of BioPortal's services.
---

# BioPortal for knowledge-graph building

[BioPortal](https://bioportal.bioontology.org/) hosts 1,000+ biomedical ontologies with a REST API
at `https://data.bioontology.org`. Beyond being the *source* KG-Bioportal transforms into KGX, its
services map neatly onto knowledge-graph construction tasks. This skill is the KG-builder's guide to
them. Endpoint details, params, and auth are in `references/bioportal-api.md`.

## When this skill applies

- "How do I turn this text/abstract into ontology terms (nodes/edges)?"
- "Which ontologies should I use for a corpus about X?"
- "Find mappings between these two ontologies so I can align/merge my KGs"
- "Fetch the class hierarchy / children / properties of a BioPortal term"
- "How does BioPortal relate to the KGX graphs in KG-Bioportal?"

## Setup
Almost every endpoint needs an **API key** (free): create an account at bioportal.bioontology.org,
find the key on your account page, and send it as `Authorization: apikey token=<KEY>` (or
`?apikey=<KEY>`). The same key drives the pattern already used in `src/kg_bioportal/downloader.py`.

## Services, mapped to KG tasks

### Annotator — text → ontology-class URIs (build nodes & edges from text)
`POST/GET /annotator?text=...` returns the ontology classes mentioned in a span of text, with the
matched term, ontology, and character offsets. **KG use:** entity recognition — turn documents,
abstracts, or field values into candidate nodes (the matched classes) and candidate edges
(class ↔ document, or co-mention edges between classes). Restrict with `ontologies=`, expand with
`expand_mappings=true`.

### Recommender — corpus → which ontologies to ingest
`GET /recommender?input=...` ranks ontologies by how well they cover a text or keyword set.
**KG use:** decide *which* BioPortal ontologies to pull into your KG for a given domain before you
transform/merge them (then fetch those graphs via the kg-bioportal-data skill).

### Mappings — cross-ontology term equivalences (align & merge KGs)
`GET /ontologies/{acronym}/mappings` and `GET /mappings?...` return mappings (e.g. `SAME_URI`,
`LOOM`, `CUI`, manual) between classes across ontologies. **KG use:** align nodes that mean the same
thing across source graphs, and **resolve dangling edges** from the kg-bioportal-merge QC report
(a dangling `CHEBI:x` might map to a term already in your graph). Mappings are how you collapse
duplicate entities when integrating multiple ontology graphs.

### Search & class/hierarchy — fetch structured node/edge data
- `GET /search?q=...` — find classes across (or within) ontologies.
- `GET /ontologies/{acronym}/classes/{URI-encoded class id}` — a class, its `prefLabel`, synonyms,
  definitions, parents/children links.
- `.../classes/{id}/children`, `/parents`, `/ancestors`, `/descendants` — the hierarchy, i.e.
  subclass edges for your KG.
- `GET /ontologies/{acronym}/properties` — object/annotation properties (candidate edge types).

**KG use:** build nodes (classes + labels + synonyms) and structural edges (subclass/part-of) for a
specific ontology or subtree without a full transform.

### Ontology download & submissions — the source graphs
- `GET /ontologies/{acronym}/latest_submission` — version, submission id, release date.
- `GET /ontologies/{acronym}/download` — the source ontology file.
- `GET /ontologies/{acronym}/metrics` — class/individual/property counts (size before you commit).

**KG use:** this is exactly what KG-Bioportal's pipeline consumes to produce the KGX graphs. If a
graph you want is Failed/Skipped in KG-Bioportal, you can still pull its source here and transform it
yourself (ROBOT → KGX).

## How this connects to KG-Bioportal
The KGX graphs in KG-Bioportal **are** these BioPortal ontologies, already transformed. Typical loop:
**Recommender** (pick ontologies) → **kg-bioportal-data** (fetch their KGX graphs) →
**kg-bioportal-merge** (combine, get QC) → **Mappings** (resolve dangling/duplicate nodes) →
**Annotator** (extend the graph with terms found in your own text).

## Notes
- Be mindful of rate limits; batch and cache. The API returns JSON with `links` for pagination
  (`nextPage`) and related resources.
- `references/bioportal-api.md` has concrete URLs, parameters, auth, and example responses.
