#!/bin/bash
# Assemble files for KG-Bioportal site

# Define paths
JEKYLL_CONFIG_HEADER_FILE="_config_header.yml"
JEKYLL_CONFIG_FILE="_config.yml"
ONTO_STATUS_FILE="onto_status.yaml"

# Append ontology status list
echo "Adding all lists to Jekyll config."
cat $JEKYLL_CONFIG_HEADER_FILE $ONTO_STATUS_FILE > $JEKYLL_CONFIG_FILE