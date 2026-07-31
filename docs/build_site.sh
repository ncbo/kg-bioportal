#!/bin/bash
# Assemble files for KG-Bioportal site

# Define paths
JEKYLL_CONFIG_HEADER_FILE="_config_header.yml"
JEKYLL_CONFIG_FILE="_config.yml"
# These stats files are produced by the transform workflow (.github/workflows/
# transform.yml -> finalize job) and committed into docs/. The old kg-hub S3
# hosting is retired, so we read the committed copies directly instead of wget.
TOTAL_STATS_FILE="total_stats.yaml"
ONTO_STATUS_FILE="onto_stats.yaml"

# Append ontology status list
echo "Adding all lists to Jekyll config."
cat $JEKYLL_CONFIG_HEADER_FILE $TOTAL_STATS_FILE $ONTO_STATUS_FILE > $JEKYLL_CONFIG_FILE

# Make figures
echo "Producing figures."
python make_viz.py