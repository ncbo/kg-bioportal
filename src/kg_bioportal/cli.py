"""CLI for KG-Bioportal."""

import logging

import click

from kg_bioportal.downloader import Downloader
from kg_bioportal.transformer import Transformer

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
@click.option("--output_dir", "-o", required=True, default="data/raw")
@click.option(
    "--api_key",
    "-k",
    required=False,
    type=str,
    help="API key for BioPortal",
)
def get_ontology_list(output_dir, api_key) -> None:
    """Downloads the list of all BioPortal ontologies and saves to a file in the data directory (default: data/raw).

    Args:

        output_dir: A string pointing to the directory to download data to.
        Defaults to data/raw.

        api_key: BioPortal / NCBO API key.

    Returns:
        None.

    """

    dl = Downloader(output_dir=output_dir, api_key=api_key)

    dl.get_ontology_list()

    return None


@main.command()
@click.option(
    "--ontologies",
    "-d",
    required=False,
    type=str,
)
@click.option(
    "--ontology_file",
    "-f",
    required=False,
    type=click.Path(exists=True),
)
@click.option("--output_dir", "-o", required=True, default="data/raw")
@click.option(
    "--snippet_only",
    "-x",
    is_flag=True,
    default=False,
    help="Download only the first 5 kB of each (uncompressed) source, for testing and file checks [false]",
)
@click.option(
    "--ignore_cache",
    "-i",
    is_flag=True,
    default=False,
    help="ignore cache and download files even if they exist [false]",
)
@click.option(
    "--api_key",
    "-k",
    required=False,
    type=str,
    help="API key for BioPortal",
)
def download(
    ontologies, ontology_file, output_dir, snippet_only, ignore_cache, api_key
) -> None:
    """Downloads specified ontologies into data directory (default: data/raw).

    Args:

        ontologies: Specify the ontologies to download by name. This should be a space-delimited list
        surrounded by quotes. Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        ontology_file: Specify the file containing a list of ontologies to download,
        one per line. Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        output_dir: A string pointing to the directory to download data to.
        Defaults to data/raw.

        snippet_only: (Not yet implemented) Downloads only the first 5 kB of the source, for testing and file checks.

        ignore_cache: (Not yet implemented) If specified, will ignore existing files and download again.

        api_key: BioPortal / NCBO API key.

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

    dl = Downloader(
        output_dir=output_dir,
        snippet_only=snippet_only,
        ignore_cache=ignore_cache,
        api_key=api_key,
    )

    dl.download(onto_list)

    return None


@main.command()
@click.option("--input_dir", "-i", default="data/raw", type=click.Path(exists=True))
@click.option("--output_dir", "-o", default="data/transformed")
def transform(input_dir, output_dir) -> None:
    """Transforms all ontologies in the input directory to KGX nodes and edges.

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.

    Returns:
        None.

    """

    tx = Transformer(input_dir=input_dir, output_dir=output_dir)

    tx.transform_all()

    return None

# Below functions are WIP.

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
