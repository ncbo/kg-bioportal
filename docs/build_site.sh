#!/bin/bash
# Assemble files for KG-Bioportal site

# Define paths
JEKYLL_CONFIG_HEADER_FILE="_config_header.yml"
JEKYLL_CONFIG_FILE="_config.yml"
TOTAL_STATS_URL="https://kg-hub.berkeleybop.io/kg-bioportal/total_stats.yaml"
TOTAL_STATS_FILE="total_stats.yaml"
ONTO_STATUS_URL="https://kg-hub.berkeleybop.io/kg-bioportal/onto_stats.yaml"
ONTO_STATUS_FILE="onto_stats.yaml"

# Retrieve most recent KG-Bioportal general stats
wget -N $TOTAL_STATS_URL

# Retrieve most recent KG-Bioportal ontology status
wget -N $ONTO_STATUS_URL

# Append ontology status list
echo "Adding all lists to Jekyll config."
cat $JEKYLL_CONFIG_HEADER_FILE $TOTAL_STATS_FILE $ONTO_STATUS_FILE > $JEKYLL_CONFIG_FILE

# Make figures
echo "Producing figures."
python make_viz.py