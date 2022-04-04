#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
from xml.etree.ElementInclude import include

import click
from kg_bioportal import download as kg_download
from kg_bioportal import transform as kg_transform
from kg_bioportal.merge_utils.merge_kg import load_and_merge, update_merge_config
from kg_bioportal.transform import DATA_SOURCES


@click.group()
def cli():
    pass


@cli.command()
@click.option("yaml_file", "-y", required=True, default="download.yaml",
              type=click.Path(exists=True))
@click.option("output_dir", "-o", required=True, default="data/raw")
@click.option("snippet_only", "-x", is_flag=True, default=False,
              help='Download only the first 5 kB of each (uncompressed) source, for testing and file checks [false]')
@click.option("ignore_cache", "-i", is_flag=True, default=False,
              help='ignore cache and download files even if they exist [false]')
def download(*args, **kwargs) -> None:
    """Downloads data files from list of URLs (default: download.yaml) into data
    directory (default: data/raw).

    Args:
        yaml_file: Specify the YAML file containing a list of datasets to download.
        output_dir: A string pointing to the directory to download data to.
        snippet_only: Downloads only the first 5 kB of the source, for testing and file checks.  
        ignore_cache: If specified, will ignore existing files and download again.

    Returns:
        None.

    """

    kg_download(*args, **kwargs)

    return None


@cli.command()
@click.option("input_dir", "-i", default="data/raw", type=click.Path(exists=True))
@click.option("output_dir", "-o", default="data/transformed")
@click.option("sources", "-s", default=None, multiple=True,
              type=click.Choice(DATA_SOURCES.keys()))
def transform(*args, **kwargs) -> None:
    """Calls scripts in kg_bioportal/transform/[source name]/ to transform each source
    into nodes and edges.

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.
        sources: A list of sources to transform.

    Returns:
        None.

    """

    # call transform script for each source
    kg_transform(*args, **kwargs)

    return None


@cli.command()
@click.option('yaml', '-y', default="merge.yaml", type=click.Path(exists=True))
@click.option('processes', '-p', default=1, type=int)
@click.option("--merge_all",
                is_flag=True,
                help="""Update the merge config file to include *all* ontologies.""")
@click.option("--include_only",
                callback=lambda _,__,x: x.split(',') if x else [],
                help="""One or more ontologies to merge, and only these,
                     comma-delimited and named by their short BioPortal ID, e.g., SEPIO.""")
@click.option("--exclude",
                callback=lambda _,__,x: x.split(',') if x else [],
                help="""One or more ontologies to exclude from merging,
                     comma-delimited and named by their short BioPortal ID, e.g., SEPIO.
                     Will select all other ontologies for merging.""")
def merge(yaml: str, processes: int, merge_all=False, include_only=[], exclude=[]) -> None:
    """Use KGX to load subgraphs to create a merged graph.

    Args:
        yaml: A string pointing to a KGX compatible config YAML.
        processes: Number of processes to use.
        merge_all: Update merge config to include *all* ontologies.
        include_only: Update merge config to include the specified ontologies.
        exclude: Update merge config to include all ontologies *except* those specified.

    Returns:
        None.

    """

    if merge_all or len(include_only) > 0 or len(exclude) > 0:
        update_merge_config(yaml, merge_all, include_only, exclude)

    load_and_merge(yaml, processes)

if __name__ == "__main__":
    cli()
