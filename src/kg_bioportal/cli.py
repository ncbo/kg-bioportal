"""CLI for KG-Bioportal."""

import json
import logging
import os

import click

from kg_bioportal.config import (
    DEFAULT_NUM_SHARDS,
    MAX_SOURCE_MB,
    PER_ONTOLOGY_TIMEOUT_MIN,
    is_skiplisted,
)
from kg_bioportal.downloader import Downloader, ONTOLOGY_LIST_NAME
from kg_bioportal.transformer import Transformer

__all__ = [
    "main",
]


def _read_acronyms(ontology_file: str) -> list:
    """Read ontology acronyms (first column) from a TSV list, skipping the header."""
    acronyms = []
    with open(ontology_file, "r") as f:
        f.readline()  # Skip the header
        for line in f:
            line = line.strip()
            if line:
                acronyms.append(line.split("\t")[0])
    return acronyms


def _read_ontology_submissions(ontology_file: str) -> dict:
    """Read {acronym: submission_id} from the ontology list TSV.

    Columns are: id, name, current_version, submission_id.
    """
    subs = {}
    with open(ontology_file, "r") as f:
        f.readline()  # Skip the header
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            cols = line.split("\t")
            acr = cols[0].strip()
            sub = cols[3].strip() if len(cols) > 3 else ""
            subs[acr] = sub
    return subs


def _load_index_submissions(index_path: str) -> dict:
    """Read {acronym: submission_id} from an onto_stats.yaml index.

    Only entries with a concrete submission_id are returned (skiplisted / no-
    submission entries use 'NA' and are excluded), so a later run always treats
    those as needing a transform.
    """
    import yaml

    if not index_path or not os.path.exists(index_path):
        return {}
    with open(index_path) as f:
        data = yaml.safe_load(f) or {}
    out = {}
    for entry in data.get("ontologies", []):
        sub = str(entry.get("submission_id") or "").strip()
        if sub and sub != "NA":
            out[entry["id"]] = sub
    return out


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
@click.option(
    "--max_source_mb",
    default=MAX_SOURCE_MB,
    show_default=True,
    type=float,
    help="Skip any ontology whose source file exceeds this many MB.",
)
@click.option(
    "--use_skiplist/--no_skiplist",
    default=True,
    show_default=True,
    help="Skip ontologies on the static known-giants skiplist.",
)
def download(
    ontologies,
    ontology_file,
    output_dir,
    snippet_only,
    ignore_cache,
    api_key,
    max_source_mb,
    use_skiplist,
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
        max_source_mb=max_source_mb,
        use_skiplist=use_skiplist,
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
@click.option(
    "--timeout_min",
    default=PER_ONTOLOGY_TIMEOUT_MIN,
    show_default=True,
    type=float,
    help="Per-ontology wall-clock cap in minutes; slower transforms are skipped.",
)
@click.option(
    "--max_source_mb",
    default=MAX_SOURCE_MB,
    show_default=True,
    type=float,
    help="Skip an ontology whose decompressed source exceeds this many MB. "
    "The download-time gate can only weigh the compressed file.",
)
def transform(input_dir, output_dir, compress, timeout_min, max_source_mb) -> None:
    """Transforms all ontologies in the input directory to KGX nodes and edges.

    Yields two log files: total_stats.yaml and onto_stats.yaml.
    The first contains the total counts of Bioportal ontologies and transforms.
    The second contains the counts of nodes and edges for each ontology.

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.

    Returns:
        None.

    """

    tx = Transformer(
        input_dir=input_dir,
        output_dir=output_dir,
        timeout_min=timeout_min,
        max_source_mb=max_source_mb,
    )

    tx.transform_all(compress=compress)

    return None


@main.command()
@click.option(
    "--ontology_file",
    "-f",
    required=False,
    type=click.Path(exists=True),
    help="TSV list of ontologies (e.g. data/raw/ontologylist.tsv).",
)
@click.option(
    "--ontologies",
    "-d",
    required=False,
    type=str,
    help="Space-delimited acronyms to shard instead of reading a file (for testing).",
)
@click.option(
    "--num_shards",
    "-n",
    default=DEFAULT_NUM_SHARDS,
    show_default=True,
    type=int,
    help="Number of shards to split the ontology list into.",
)
@click.option(
    "--use_skiplist/--no_skiplist",
    default=True,
    show_default=True,
    help="Drop ontologies on the static known-giants skiplist before sharding.",
)
@click.option(
    "--index",
    "index_path",
    required=False,
    type=click.Path(),
    help="Path to the current onto_stats.yaml index. If given (with --ontology_file), "
    "only ontologies whose BioPortal submission_id differs from the index are sharded "
    "(version-skip); unchanged ones carry forward via the finalize seed.",
)
def shard_list(ontology_file, ontologies, num_shards, use_skiplist, index_path) -> None:
    """Splits the ontology list into N shards and prints them as JSON.

    Emits a JSON array of strings, each a space-separated group of acronyms,
    suitable for a GitHub Actions matrix. Prints ONLY the JSON to stdout so it
    can be captured as a job output.
    """
    current_subs = {}
    if ontologies:
        acronyms = ontologies.split()  # explicit list: never version-skipped
    elif ontology_file:
        current_subs = _read_ontology_submissions(ontology_file)
        acronyms = list(current_subs)
    else:
        raise click.UsageError("Provide --ontologies or --ontology_file.")

    # Version-skip: only (re)transform ontologies that are new or whose BioPortal
    # submission changed vs the current index. Applies only to the full list.
    if index_path and current_subs:
        index_subs = _load_index_submissions(index_path)
        if index_subs:
            before = len(acronyms)
            acronyms = [
                a for a in acronyms
                if index_subs.get(a) != current_subs.get(a)
            ]
            click.echo(
                f"version-skip: {before - len(acronyms)} unchanged skipped, "
                f"{len(acronyms)} to transform.",
                err=True,
            )

    if use_skiplist:
        acronyms = [a for a in acronyms if not is_skiplisted(a)]

    # Round-robin so heavy ontologies spread across shards rather than clumping.
    n = max(1, min(num_shards, len(acronyms)))
    buckets = [[] for _ in range(n)]
    for i, acr in enumerate(acronyms):
        buckets[i % n].append(acr)

    shards = [" ".join(b) for b in buckets if b]
    click.echo(json.dumps(shards))

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
