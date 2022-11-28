#!/bin/bash
# Assemble files for KG-Bioportal site

# Define paths
JEKYLL_CONFIG_HEADER_FILE="_config_header.yml"
JEKYLL_CONFIG_FILE="_config.yml"
GRAPH_STATS_URL="https://kg-hub.berkeleybop.io/kg-bioportal/graph_stats.yaml"
GRAPH_STATS_FILE="graph_stats.yaml"
ONTO_STATUS_URL="https://kg-hub.berkeleybop.io/kg-bioportal/onto_status.yaml"
ONTO_STATUS_FILE="onto_status.yaml"

# Retrieve most recent KG-Bioportal general stats
wget -N $GRAPH_STATS_URL

# Retrieve most recent KG-Bioportal ontology status
wget -N $ONTO_STATUS_URL

# Append ontology status list
echo "Adding all lists to Jekyll config."
cat $JEKYLL_CONFIG_HEADER_FILE $GRAPH_STATS_FILE $ONTO_STATUS_FILE > $JEKYLL_CONFIG_FILE

# Make figures
echo "Producing figures."
python make_viz.py