# KG-Bioportal Agent Skills

Skills for AI agents (Claude Code and compatible tools) to work with KG-Bioportal data. Each skill
is a directory with a `SKILL.md` (instructions + trigger description), optional `references/`
(detailed docs the skill points to), and `scripts/` (runnable helpers). They are discovered
automatically when working in this repository.

| Skill | What it does |
|-------|--------------|
| [`kg-bioportal-data`](kg-bioportal-data/SKILL.md) | Find, download, and load the KGX graphs (releases, `onto_stats`, node/edge TSVs). The foundation. |
| [`kg-bioportal-merge`](kg-bioportal-merge/SKILL.md) | Merge a set of graphs with cat-merge (QC report) or KGX merge. |
| [`bioportal-for-kg-building`](bioportal-for-kg-building/SKILL.md) | Use BioPortal's Annotator / Recommender / Mappings / API to build, enrich, and align KGs. |

Typical loop: **Recommender** picks ontologies → **kg-bioportal-data** fetches their KGX graphs →
**kg-bioportal-merge** combines them and reports gaps → **Mappings** resolves dangling/duplicate
nodes → **Annotator** extends the graph from your own text.

The `scripts/` helpers use only the Python standard library except where noted (`pyyaml` for reading
`onto_stats.yaml`; `cat-merge` / `kgx` for merging).
