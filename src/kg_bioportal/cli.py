"""CLI for KG-Bioportal."""

import logging

import click

from kg_bioportal.downloader import Downloader, ONTOLOGY_LIST_NAME
from kg_bioportal.transformer import Transformer
from kg_bioportal.merger import Merger

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

    # If no input args provided, use the full list of ontologies
    # But if the full list isn't available, throw an error and remind
    # the user to download it first
    if not ontologies and not ontology_file:
        try:
            with open(f"{output_dir}/{ONTOLOGY_LIST_NAME}", "r") as f:
                f.readline()  # Skip the header
                for line in f:
                    onto_list.append(line.strip().split("\t")[0])
        except FileNotFoundError:
            logging.error(
                f"Ontology list file not found. Please run the 'get_ontology_list' command first."
            )
            return None

    # Parse the ontologies argument
    if ontologies:
        for ontology in ontologies.split():
            onto_list.append(ontology)

    # Parse the ontology_file argument
    if ontology_file:
        with open(ontology_file, "r") as f:
            f.readline()  # Skip the header
            for line in f:
                onto_list.append(line.strip().split("\t")[0])

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
@click.option(
    "--compress",
    "-c",
    is_flag=True,
    default=True,
    help="If true, compresses the output nodes and edges to tar.gz. Defaults to True.",
)
def transform(input_dir, output_dir, compress) -> None:
    """Transforms all ontologies in the input directory to KGX nodes and edges.

    Yields two log files: total_stats.yaml and onto_stats.yaml.
    The first contains the total counts of Bioportal ontologies and transforms.
    The second contains the counts of nodes and edges for each ontology.

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.
        compress: If true, compresses the output nodes and edges to tar.gz. Defaults to True.

    Returns:
        None.

    """

    tx = Transformer(input_dir=input_dir, output_dir=output_dir)

    tx.transform_all(compress=compress)

    return None


@main.command()
@click.option(
    "--input_dir", "-i", default="data/transformed", type=click.Path(exists=True)
)
@click.option("--output_dir", "-o", default="data/merged")
@click.option(
    "--compress",
    "-c",
    is_flag=True,
    default=True,
    help="If true, compresses the output nodes and edges to tar.gz. Defaults to True.",
)
def merge(input_dir, output_dir, compress) -> None:
    """Merges all edges and nodes in the input directory to a single KGX graph.

    Yields one log files: merged_graph_stats.yaml.

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.
        compress: If true, compresses the output nodes and edges to tar.gz. Defaults to True.

    Returns:
        None.

    """

    mx = Merger(input_dir=input_dir, output_dir=output_dir)

    mx.merge_all(compress=compress)

    return None


if __name__ == "__main__":
    main()
