#!/bin/bash
# Set up the merged Bioportal graph for Neo4j.
# Requires KGX to be installed and accessible.

GRAPH_PATH="./data/merged/"
TX_CONFIG_PATH="neo4j-transform.yaml"

# Run
echo "Transforming KG-Bioportal to Neo4j..."
kgx transform --transform-config $TX_CONFIG_PATH