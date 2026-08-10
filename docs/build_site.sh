#!/bin/bash
# Assemble files for KG-Bioportal site

# Define paths
JEKYLL_CONFIG_HEADER_FILE="_config_header.yml"
JEKYLL_CONFIG_FILE="_config.yml"
# Stats are produced by the transform workflow (.github/workflows/transform.yml)
# and published as assets on the latest GitHub Release. The old kg-hub S3 hosting
# is retired; fetch the current copies from the release (-O forces overwrite).
RELEASE_BASE="https://github.com/ncbo/kg-bioportal/releases/latest/download"
TOTAL_STATS_FILE="total_stats.yaml"
ONTO_STATUS_FILE="onto_stats.yaml"

# Retrieve the most recent transform stats from the latest release.
wget -O "$TOTAL_STATS_FILE" "$RELEASE_BASE/$TOTAL_STATS_FILE"
wget -O "$ONTO_STATUS_FILE" "$RELEASE_BASE/$ONTO_STATUS_FILE"

# Append ontology status list
echo "Adding all lists to Jekyll config."
cat $JEKYLL_CONFIG_HEADER_FILE $TOTAL_STATS_FILE $ONTO_STATUS_FILE > $JEKYLL_CONFIG_FILE

# Build KG-Registry-driven knowledge-graph pages (BioPortal-style interface).
# Pulls the KG-Registry JSON-LD, keeps only KnowledgeGraph resources, and writes
# a browse index, a site-wide Summary page (statistics + figures), and one summary
# page per graph into docs/graphs/.
echo "Building the unified graph browser (KG-Registry KGs + transformed ontologies)."
python kg_site/build_site.py --fetch kg_site/kgs.jsonld graphs --onto-stats onto_stats.yaml