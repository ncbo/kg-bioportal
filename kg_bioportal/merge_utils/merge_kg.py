import importlib
import logging
from typing import Dict, List
import yaml
import networkx as nx # type: ignore
from kgx.cli.cli_utils import merge # type: ignore


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

    pass


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
