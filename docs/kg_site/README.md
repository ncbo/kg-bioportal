# Knowledge-graph pages (BioPortal-style)

`build_site.py` generates a static, BioPortal-styled browse-and-summary interface
for the knowledge graphs registered in [KG-Registry](https://kghub.org/kg-registry/).

It reads the registry's JSON-LD dump, keeps only resources whose
`category == "KnowledgeGraph"` (all other resource types stay in KG-Registry),
and writes:

```
graphs/
  index.html                    # browse page — every KG, with filter + domain facets
  resource/<id>/index.html      # one summary page per graph
```

Each page is self-contained (CSS inlined, no external assets) and carries no Jekyll
front matter, so Jekyll copies it through verbatim.

## Run it

```bash
# from docs/ — this is also invoked automatically by build_site.sh
python kg_site/build_site.py --fetch kg_site/kgs.jsonld graphs

# or against a local dump, writing anywhere:
python kg_site/build_site.py path/to/kgs.jsonld output_dir
```

No third-party dependencies (Python standard library only).

## Notes

- **Metrics** (nodes, edges, node categories, predicate types) come from each graph's
  `GraphProduct` records. Only ~21 of 154 graphs report counts today; the rest degrade
  gracefully to "—".
- **Colors** match the live BioPortal theme (`theme-variables.scss.erb`): primary `#234979`,
  hover `#2B5892`, gold accent `#C58612`.
- **Tool links** (Search / Mappings / Recommender / Annotator) point at the live
  BioPortal services. The *Browse* tab is the KG-native listing generated here.
- `kgs.jsonld` and the generated `graphs/` directory are git-ignored build artifacts.
