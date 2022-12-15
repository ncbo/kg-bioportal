"""Download function for KG-Bioportal."""


from kghub_downloader.download_utils import download_from_yaml  # type: ignore


def download(
    yaml_file: str, output_dir: str, snippet_only: bool, ignore_cache: bool = False
) -> None:
    """Download data files from list of URLs into data directory (default: data/).

    Args:
        yaml_file: A string pointing to the yaml file for downloading of data.
        output_dir: A string pointing to the location to download data to.
        snippet_only: Downloads the first 5 kB of the source for testing and file checks.
        ignore_cache: Ignore cache and download files even if they exist [false]

    Returns:
        None.
    """
    download_from_yaml(
        yaml_file=yaml_file,
        output_dir=output_dir,
        snippet_only=snippet_only,
        ignore_cache=ignore_cache,
    )

    return None
