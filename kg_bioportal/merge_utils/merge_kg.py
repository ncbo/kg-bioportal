import copy
import os
from copy import deepcopy
import tarfile
from typing import Dict, List

import networkx as nx  # type: ignore
import pandas as pd  # type: ignore
import yaml
from cat_merge.merge import merge as cat_merge_merge  # type: ignore
from kgx.cli.cli_utils import merge  # type: ignore

ONTO_DATA_PATH = "../transformed/ontologies/"
OUTPUT_PATH = "data/merged"

def parse_load_config(yaml_file: str) -> Dict:
    """Parse load config YAML.

    Args:
        yaml_file: A string pointing to a KGX compatible config YAML.

    Returns:
        Dict: The config as a dictionary.

    """
    with open(yaml_file) as YML:
        config = yaml.load(YML, Loader=yaml.FullLoader)
    return config

def update_merge_config(yaml_file: str, merge_all: bool, include_only: list, exclude: list) -> None:
    """Update the merge config YAML with
    values from runtime params.

    Args:
        yaml_file: A string pointing to a KGX compatible config YAML.
        merge_all: Update merge config to include *all* ontologies.
        include_only: Update merge config to include the specified ontologies.
        exclude: Update merge config to include all ontologies *except* those specified.

    Returns:
        None

    """

    # Need to know ontology names and filepaths.
    # Keys in onto_paths are short names, values are lists of filepaths.
    onto_paths = {}
    if len(include_only) > 0:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname)) and dirname in include_only]
    elif len(exclude) > 0:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname)) and dirname not in exclude]
    else:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname))]
    for dirname in onto_dirs:
        this_path = os.path.join(ONTO_DATA_PATH,dirname)
        onto_paths[dirname] = [os.path.join(this_path, filename) for filename in \
            os.listdir(this_path) if os.path.isfile(os.path.join(this_path, filename)) and filename.endswith(".tsv")]

    # Default behavior is to merge all for now, but this could do something different later
    if merge_all:
        pass

    i = 0
    with open(yaml_file) as YML:
        config = yaml.load(YML, Loader=yaml.FullLoader)
        updated_config = copy.deepcopy(config)
        updated_config['merged_graph']['source'] = {}
        for onto in onto_paths:
            updated_config['merged_graph']['source'][f's{i}'] = {'name':onto,'input':{'format':'tsv','filename':onto_paths[onto]}}
            i = i+1

    with open(yaml_file, 'w') as updated_yaml_file:
        updated_yaml_file.write(yaml.dump(updated_config, default_flow_style=False, sort_keys=False))

def load_and_merge(yaml_file: str, processes: int = 1) -> nx.MultiDiGraph:
    """Load and merge sources defined in the config YAML.

    Args:
        yaml_file: A string pointing to a KGX compatible config YAML.
        processes: Number of processes to use.

    Returns:
        networkx.MultiDiGraph: The merged graph.

    """
    merged_graph = merge(yaml_file, processes=processes)
    return merged_graph

def merge_with_cat_merge(merge_all: bool, include_only: list, exclude: list) -> None:
    """Load and merge sources with cat-merge.
    Cat-merge does not merge values based on their ids,
    it just concatenates and drops exact duplicates.
    A subsequent step here performs further merging
    on identical IDs and concatenates other values,
    delimiting with pipe symbols.

    Args:
        merge_all: if True, merge all ontology node and edges.
        include_only: list of paths to ontology node/edgefiles to include
        exclude: list of paths to ontology node/edgefiles to exclude

    Returns:
        None

    """
    
    nodepaths = []
    edgepaths = []

    # Prepare a blank header edgefile so we can ensure we have the correct
    # column headings
    blank_header_path = "blank_header.tsv"
    if not os.path.exists(blank_header_path):
        with open(blank_header_path, "w") as outfile:
            outstring = "id\tobject\tsubject\tpredicate\tcategory\n"
            outfile.write(outstring)
    edgepaths.append(blank_header_path)

    # Need to know ontology names and filepaths
    # Keys in onto_paths are short names, values are lists of filepaths.
    onto_paths = {}
    if len(include_only) > 0:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname)) and dirname in include_only]
    elif len(exclude) > 0:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname)) and dirname not in exclude]
    else:
        onto_dirs = [dirname for dirname in os.listdir(ONTO_DATA_PATH) if \
            os.path.isdir(os.path.join(ONTO_DATA_PATH, dirname))]
    for dirname in onto_dirs:
        this_path = os.path.join(ONTO_DATA_PATH,dirname)
        onto_paths[dirname] = [os.path.join(this_path, filename) for filename in \
            os.listdir(this_path) if os.path.isfile(os.path.join(this_path, filename)) and filename.endswith(".tsv")]

    # Separate out node vs. edgelist
    # Do a check to verify that none of the files are empty, or the merge will fail
    # also verify the header in each contains an 'id' field
    # (it's invalid without it)
    ignore_paths = []
    for onto_name in onto_paths:
        print(f"Validating {onto_name}...")
        for path in onto_paths[onto_name]:
            if path.endswith("_nodes.tsv"):
                this_edgepath = (path.rpartition('_'))[0] + '_edges.tsv'
                try:
                    nodedf = pd.read_csv(path, sep='\t', index_col='id')
                except (KeyError, TypeError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
                    ignore_paths.append(this_edgepath)
                    print(f"Ignoring {path} due to pandas parsing error. Will also ignore {this_edgepath}. Error: {e}")
                    continue
                num_lines = len(nodedf.index)
                if num_lines > 1 and path not in ignore_paths:
                    nodepaths.append(path)
                else:
                    ignore_paths.append(this_edgepath)
                    print(f"Ignoring {path} as it contains no nodes or node ids. Will also ignore {this_edgepath}.")
            elif path.endswith("_edges.tsv"):
                this_nodepath = (path.rpartition('_'))[0] + '_nodes.tsv'
                try:
                    edgedf = pd.read_csv(path, sep='\t', index_col='id')
                except (KeyError, TypeError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
                    ignore_paths.append(this_nodepath)
                    print(f"Ignoring {path} due to pandas parsing error. Will also ignore {this_nodepath}. Error: {e}")
                    continue
                num_lines = len(edgedf.index)
                if num_lines > 1 and path not in ignore_paths:
                    edgepaths.append(path)
                else:
                    ignore_paths.append(this_nodepath)
                    print(f"Ignoring {path} as it contains no edges or edge ids. Will also ignore {this_nodepath}.")

    # Default behavior is to merge all for now, but this could do something different later
    if merge_all:
        pass

    # Perform the cat merge
    cat_merge_merge(
        name='merged-kg',
        nodes=nodepaths,
        edges=edgepaths,
        output_dir=OUTPUT_PATH,
        qc_report=True
    )

    # Find duplicate nodes and rows.
    # For duplicate rows, remove all but the first instance.
    # For duplicate nodes (those with identical CURIEs),
    # merge all fields with a delimiter.

    nodefile_name = "merged-kg_nodes.tsv"
    nodefile_path = os.path.join(OUTPUT_PATH,nodefile_name)
    edgefile_name = "merged-kg_nodes.tsv"
    edgefile_path = os.path.join(OUTPUT_PATH,edgefile_name)
    temp_nodefile_name = "merged-kg_nodes.tsv.temp"
    temp_nodefile_path = os.path.join(OUTPUT_PATH,temp_nodefile_name)
    merge_graph_path = os.path.join(OUTPUT_PATH,'merged-kg.tar.gz')
    graph_file_paths = []
    
    with tarfile.open(merge_graph_path) as intar:
        graph_files = intar.getnames()
        print(graph_files)
        for graph_file in graph_files:
            intar.extract(graph_file, path=os.path.dirname(merge_graph_path))
            graph_file_paths.append(os.path.join(os.path.dirname(merge_graph_path), graph_file))
    os.remove(merge_graph_path)

    # Remove duplicate rows and merge duplicate nodes
    print("Reading merged graph to process duplicates...")
    nodes_df = pd.read_csv(nodefile_path, sep='\t', index_col='id')
    print(f"Node count before removing complete duplicates: {len(nodes_df.index)}")
    nodes_df.drop_duplicates(keep='first', inplace=True)
    print(f"Node count after removing complete duplicates: {len(nodes_df.index)}")
    uniq_df = nodes_df.groupby('id').agg(lambda x: '|'.join(set(x)))
    print(f"Node count after merging duplicate nodes: {len(uniq_df.index)}")
    uniq_df.to_csv(temp_nodefile_path, sep='\t')

    os.replace(temp_nodefile_path, nodefile_path)

    # Compress it again
    with tarfile.open(merge_graph_path, "w:gz") as outtar:
         for graph_file in graph_file_paths:
             outtar.add(graph_file, arcname=os.path.basename(graph_file))
             os.remove(graph_file)

    print("Complete.")