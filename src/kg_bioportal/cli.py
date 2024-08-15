"""CLI for KG-Bioportal."""

import logging

import click

from kg_bioportal.downloader import Downloader

__all__ = [
    "main",
]


@click.group()
@click.option("-v", "--verbose", count=True)
@click.option("-q", "--quiet")
def main(verbose: int, quiet: bool):
    """CLI for KG-Bioportal.

    :param verbose: Verbosity while running.
    :param quiet: Boolean to be quiet or verbose.
    """
    logger = logging.getLogger()
    if verbose >= 2:
        logger.setLevel(level=logging.DEBUG)
    elif verbose == 1:
        logger.setLevel(level=logging.INFO)
    else:
        logger.setLevel(level=logging.WARNING)
    if quiet:
        logger.setLevel(level=logging.ERROR)
    logger.info(f"Logger {logger.name} set to level {logger.level}")


@main.command()
@click.option(
    "ontologies",
    "-d",
    required=False,
    type=str,
)
@click.option(
    "ontology_file",
    "-f",
    required=False,
    type=click.Path(exists=True),
)
@click.option("output_dir", "-o", required=True, default="data/raw")
@click.option(
    "snippet_only",
    "-x",
    is_flag=True,
    default=False,
    help="Download only the first 5 kB of each (uncompressed) source, for testing and file checks [false]",
)
@click.option(
    "ignore_cache",
    "-i",
    is_flag=True,
    default=False,
    help="ignore cache and download files even if they exist [false]",
)
def download(ontologies, ontology_file, output_dir, snippet_only, ignore_cache) -> None:
    """Downloads specified ontologies into data directory (default: data/raw).

    Args:

        ontologies: Specify the ontologies to download by name. This should be a space-delimited list
        surrounded by quotes. Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        ontology_file: Specify the file containing a list of ontologies to download,
        one per line. Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        output_dir: A string pointing to the directory to download data to.
        Defaults to data/raw.

        snippet_only: Downloads only the first 5 kB of the source, for testing and file checks.

        ignore_cache: If specified, will ignore existing files and download again.

    Returns:
        None.

    """

    onto_list = []

    # Parse the ontologies argument
    if ontologies:
        for ontology in ontologies.split():
            onto_list.append(ontology)

    # Parse the ontology_file argument
    if ontology_file:
        with open(ontology_file, "r") as f:
            for line in f:
                onto_list.append(line.strip())

    logging.info(f"{len(onto_list)} ontologies to retrieve.")

    dl = Downloader(output_dir, snippet_only, ignore_cache)

    dl.download(onto_list)

    return None


# Below functions are WIP.

# @cli.command()
# @click.option("input_dir", "-i", default="data/raw", type=click.Path(exists=True))
# @click.option("output_dir", "-o", default="data/transformed")
# @click.option(
#     "sources", "-s", default=None, multiple=True, type=click.Choice(DATA_SOURCES.keys())
# )
# def transform(*args, **kwargs) -> None:
#     """Calls scripts in kg_bioportal/transform/[source name]/ to transform each source
#     into nodes and edges.

#     Args:
#         input_dir: A string pointing to the directory to import data from.
#         output_dir: A string pointing to the directory to output data to.
#         sources: A list of sources to transform.

#     Returns:
#         None.

#     """

#     # call transform script for each source
#     kg_transform(*args, **kwargs)

#     return None


# @cli.command()
# @click.option("yaml", "-y", default="merge.yaml", type=click.Path(exists=True))
# @click.option("processes", "-p", default=1, type=int)
# @click.option(
#     "--merge_all",
#     is_flag=True,
#     help="""Update the merge config file to include *all* ontologies.""",
# )
# @click.option(
#     "--include_only",
#     callback=lambda _, __, x: x.split(",") if x else [],
#     help="""One or more ontologies to merge, and only these,
#                      comma-delimited and named by their short BioPortal ID, e.g., SEPIO.""",
# )
# @click.option(
#     "--exclude",
#     callback=lambda _, __, x: x.split(",") if x else [],
#     help="""One or more ontologies to exclude from merging,
#                      comma-delimited and named by their short BioPortal ID, e.g., SEPIO.
#                      Will select all other ontologies for merging.""",
# )
# def merge(
#     yaml: str, processes: int, merge_all=False, include_only=[], exclude=[]
# ) -> None:
#     """Use KGX to load subgraphs to create a merged graph.

#     Args:
#         yaml: A string pointing to a KGX compatible config YAML.
#         processes: Number of processes to use.
#         merge_all: Update merge config to include *all* ontologies.
#         include_only: Update merge config to include the specified ontologies.
#         exclude: Update merge config to include all ontologies *except* those specified.

#     Returns:
#         None.

#     """

#     if merge_all or len(include_only) > 0 or len(exclude) > 0:
#         update_merge_config(yaml, merge_all, include_only, exclude)

#     load_and_merge(yaml, processes)

#     make_graph_stats(
#         method="kgx",
#         input_file="merged_graph_stats.yaml",
#         output_file="graph_stats.yaml",
#     )


# @cli.command()
# @click.option("--merge_all", is_flag=True, help="""Include *all* ontologies.""")
# @click.option(
#     "--include_only",
#     callback=lambda _, __, x: x.split(",") if x else [],
#     help="""One or more ontologies to merge, and only these,
#                      comma-delimited and named by their short BioPortal ID, e.g., SEPIO.""",
# )
# @click.option(
#     "--exclude",
#     callback=lambda _, __, x: x.split(",") if x else [],
#     help="""One or more ontologies to exclude from merging,
#                      comma-delimited and named by their short BioPortal ID, e.g., SEPIO.
#                      Will select all other ontologies for merging.""",
# )
# def catmerge(merge_all=False, include_only=[], exclude=[]) -> None:
#     """Use cat-merge to create a merged graph.

#     Args:
#         merge_all: Include *all* ontologies.
#         include_only: Include only the specified ontologies.
#         exclude: Include all ontologies *except* those specified.

#     Returns:
#         None.

#     """

#     merge_with_cat_merge(merge_all, include_only, exclude)

#     make_graph_stats(
#         method="catmerge",
#         input_file="data/merged/qc_report.yaml",
#         output_file="graph_stats.yaml",
#     )


if __name__ == "__main__":
    main()
