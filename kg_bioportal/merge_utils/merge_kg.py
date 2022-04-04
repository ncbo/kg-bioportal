from copy import deepcopy
from typing import Dict, List
import yaml
import networkx as nx # type: ignore
from kgx.cli.cli_utils import merge # type: ignore
import os
import copy

ONTO_DATA_PATH = "../BioPortal-to-KGX/transformed/ontologies/"

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
