# BioPortal API cheatsheet (data.bioontology.org)

Base URL: `https://data.bioontology.org`. Web UI: `https://bioportal.bioontology.org`.

## Auth
Every call needs an API key (free; from your BioPortal account page). Either header or query param:
```bash
curl -H "Authorization: apikey token=$NCBO_API_KEY" "https://data.bioontology.org/ontologies"
curl "https://data.bioontology.org/ontologies?apikey=$NCBO_API_KEY"
```
Responses are JSON. Collections paginate via a `links.nextPage` URL and a `page`/`pageCount` object.
Most resources embed `@id`, `@type`, and a `links` block to related endpoints.

## Endpoints by KG task

### Annotator — text → ontology classes
```
GET /annotator?text=<TEXT>&ontologies=GO,CHEBI&longest_only=true&expand_mappings=true
```
Returns a list of annotations; each has `annotatedClass` (`@id` = class URI, plus `links.ontology`)
and `annotations[]` with `text`, `from`, `to`, `matchType`. Use `ontologies=` to scope; POST for
long text.

### Recommender — corpus → ranked ontologies
```
GET /recommender?input=<TEXT or comma keywords>&input_type=1   # 1=text, 2=keyword list
```
Returns ranked entries with `ontologies[]` and coverage/specialization scores.

### Mappings — cross-ontology equivalences
```
GET /ontologies/{ACR}/mappings?page=1                  # all mappings for an ontology
GET /mappings?class=<URI-encoded class URI>&ontologies=A,B
```
Each mapping has `classes[]` (the two mapped class `@id`s + their ontologies) and `source`
(`SAME_URI`, `LOOM`, `CUI`, `REST`/manual, …).

### Search
```
GET /search?q=<TERM>&ontologies=GO&require_exact_match=false&pagesize=50
```
Returns matching classes with `prefLabel`, `ontology`, `@id`.

### Classes & hierarchy (nodes + structural edges)
```
GET /ontologies/{ACR}/classes?page=1                                  # all classes (paged)
GET /ontologies/{ACR}/classes/{URI-encoded class id}                  # one class
GET /ontologies/{ACR}/classes/{id}/children | /parents | /ancestors | /descendants
GET /ontologies/{ACR}/properties                                      # object/annotation properties
```
A class carries `prefLabel`, `synonym[]`, `definition[]`, and `links` to `children`, `parents`,
`ancestors`, `tree`. `{id}` must be the **URL-encoded full class URI**
(e.g. `http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0008150`).

### Ontology metadata, size, and source
```
GET /ontologies                                # list all ontologies (acronym, name, links)
GET /ontologies/{ACR}                           # one ontology's metadata
GET /ontologies/{ACR}/latest_submission         # version, submissionId, released, hasOntologyLanguage
GET /ontologies/{ACR}/metrics                   # numberOfClasses, numberOfIndividuals, numberOfProperties, maxDepth …
GET /ontologies/{ACR}/download                  # the source ontology file (Content-Disposition names it)
GET /analytics                                  # all ontology acronyms (used to enumerate)
```
These four (`latest_submission`, `metrics`, `download`, `analytics`) are exactly what
`src/kg_bioportal/downloader.py` uses to enumerate and pull ontologies for the KGX transform. Check
`metrics.numberOfClasses` before ingesting to gauge size.

## Practical notes
- **Rate limits:** batch requests, cache responses, and page politely (`pagesize` up to a few
  hundred). The downloader wraps calls with retry/backoff on 429/504 — mirror that for bulk work.
- **URIs vs acronyms:** ontologies are addressed by acronym (`GO`); classes by their full URI
  (URL-encoded) within an ontology.
- **From API to KG:** for one ontology, `classes` + `children`/`parents` already give you a
  node+edge set. For the whole ontology as a graph, prefer the pre-built KGX artifact from
  KG-Bioportal (kg-bioportal-data skill) rather than crawling the API.
- Docs: https://data.bioontology.org/documentation
