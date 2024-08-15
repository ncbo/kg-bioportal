"""Downloader for KG-Bioportal."""

import logging

class Downloader:

    # Directory to save the downloaded files
    output_dir: str = "data/raw"
    
    # If True, downloads only the first 5 kB of each (uncompressed) source,
    # for testing and file checks
    snippet_only: bool = False
    
    # If True, ignore cache and download files even if they exist
    ignore_cache: bool = False

    def download(self, onto_list: list = []) -> None:
        """Downloads data files from list of ontologies into data directory.

        Args:
            output_dir: A string pointing to the location to download data to.
            snippet_only: Downloads only the first 5 kB of the source, for testing and file checks. 
            ignore_cache: Ignore cache and download files even if they exist

        Returns:
            None.
        """

        print("TEST")

        return None