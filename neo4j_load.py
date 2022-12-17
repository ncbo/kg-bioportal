"""Loader script for KG-Bioportal edges and nodes -> Neo4j."""
# Borrowed liberally from Sierra Moxon's CTD ingest:
# https://github.com/sierra-moxon/ctd_ingest


import argparse
from kgx.transformer import Transformer


def usage():
    """Describe usage of the function."""
    print("usage: neo4j_load.py --nodes nodes.tsv --edges edges.tsv")

parser = argparse.ArgumentParser(description="Load edges and nodes into Neo4j")
parser.add_argument("--nodes", help="file with nodes in TSV format")
parser.add_argument("--edges", help="file with edges in TSV format")
parser.add_argument(
    "--uri", help="URI/URL for Neo4j (including port)", default="localhost:7474"
)
parser.add_argument("--username", help="username", default="neo4j")
parser.add_argument("--password", help="password", default="s3cr3t")
args = parser.parse_args()

if args.nodes is None and args.edges is None:
    usage()
    exit()

filename = []
if args.nodes:
    filename.append(args.nodes)
if args.edges:
    filename.append(args.edges)

input_args = {"filename": filename, "format": "tsv"}
output_args = {
    "uri": args.uri,
    "username": args.username,
    "password": args.password,
    "format": "neo4j",
}

# Initialize Transformer
t = Transformer()
print("Made a transformer.")
t.transform(input_args, output_args)
