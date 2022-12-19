#!/bin/bash
# Set up the merged Bioportal graph for Neo4j.
# Requires KGX to be installed and accessible.

GRAPH_PATH="./data/merged/"
TX_CONFIG_PATH="neo4j-transform.yaml"
CONTAINER_NAME="kgx-neo4j"

# Run
echo "Set up the Neo4j Docker container..."
if [ ! "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    # If container isn't running, run that container
    # This will download if needed
    docker run -d --rm --name $CONTAINER_NAME \
            -p 7474:7474 -p 7687:7687 \
            --env=NEO4J_AUTH=none \
            neo4j:4.3
else
    echo "Container is already running."
    docker ps -f name=$CONTAINER_NAME
fi

echo "Setting up KG-Bioportal for Neo4j..."
kgx transform --transform-config $TX_CONFIG_PATH

echo "Loading nodes and edges into Neo4j..."
python neo4j_load.py --nodes $GRAPH_PATH/merged-kg_nodes.tsv --edges $GRAPH_PATH/merged-kg_edges.tsv --uri bolt://localhost:7687