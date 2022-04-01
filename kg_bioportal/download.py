#!/usr/bin/env python
# -*- coding: utf-8 -*-


from kghub_downloader.download_utils import download_from_yaml # type: ignore


def download(yaml_file: str, output_dir: str, snippet_only: bool, ignore_cache: bool = False) -> None:
    """Downloads data files from list of URLs (default: download.yaml) into data directory (default: data/).

    Args:
        yaml_file: A string pointing to the yaml file utilized to facilitate the downloading of data.
        output_dir: A string pointing to the location to download data to.
        snippet_only: Downloads only the first 5 kB of the source, for testing and file checks. 
        ignore_cache: Ignore cache and download files even if they exist [false]

    Returns:
        None.
    """

    download_from_yaml(yaml_file=yaml_file, output_dir=output_dir,
                        snippet_only=snippet_only,
                        ignore_cache=ignore_cache)

    return None
