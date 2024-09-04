"""Downloader for KG-Bioportal."""

import logging
import os
import requests

ONTOLOGY_LIST_NAME = "ontologylist.tsv"


class Downloader:

    # TODO: implement ignore_cache and snippet_only

    # Directory to save the downloaded files
    output_dir: str = "data/raw"

    # If True, downloads only the first 5 kB of each (uncompressed) source,
    # for testing and file checks
    snippet_only: bool = False

    # If True, ignore cache and download files even if they exist
    ignore_cache: bool = False

    # API key for BioPortal
    api_key: str = ""

    def __init__(
        self,
        output_dir: str = "data/raw",
        snippet_only: bool = False,
        ignore_cache: bool = False,
        api_key: str = "",
    ) -> None:
        """Initializes the Downloader class.

        Args:
            output_dir: A string pointing to the location to download data to.
            snippet_only: Downloads only the first 5 kB of the source, for testing and file checks.
            ignore_cache: Ignore cache and download files even if they exist
            api_key: API key for BioPortal

        Returns:
            None.
        """
        self.output_dir = output_dir
        self.snippet_only = snippet_only
        self.ignore_cache = ignore_cache
        self.api_key = api_key

        # If the output directory does not exist, create it
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        if not api_key:
            raise ValueError("API key is required for downloading from BioPortal.")

        return None

    # TODO: save NCBO ID and version for each ontology, then pass to transformer
    def download(self, onto_list: list = []) -> None:
        """Downloads data files from list of ontologies into data directory.

        Args:

            onto_list: A list of ontologies to download by name.
            Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        Returns:
            None.
        """
        headers = {"Authorization": f"apikey token={self.api_key}"}

        for ontology in onto_list:
            logging.info(f"Downloading {ontology}...")

            metadata_url = f"https://data.bioontology.org/ontologies/{ontology}"
            latest_sub_url = (
                f"https://data.bioontology.org/ontologies/{ontology}/latest_submission"
            )
            download_url = (
                f"https://data.bioontology.org/ontologies/{ontology}/download"
            )

            metadata = requests.get(metadata_url, headers=headers).json()
            logging.info(f"Name: {metadata['name']}")
            latest_sub_metadata = requests.get(latest_sub_url, headers=headers).json()
            logging.info(
                f"Latest submission: {latest_sub_metadata['version']} - released {latest_sub_metadata['released']}"
            )

            download_onto = requests.get(
                download_url, headers=headers, allow_redirects=True
            )
            onto_filename = (
                download_onto.headers["Content-Disposition"]
                .split("filename=")[1]
                .replace('"', "")
            )
            with open(f"{self.output_dir}/{onto_filename}", "wb") as outfile:
                outfile.write(download_onto.content)

        return None

    def get_ontology_list(self) -> None:
        """Get the list of ontologies from BioPortal.

        This includes the descriptive name and most recent version.

        Args:
            None.

        Returns:
            None.
        """

        headers = {"Authorization": f"apikey token={self.api_key}"}

        logging.info("Getting set of all ontologies...")

        analytics_url = "https://data.bioontology.org/analytics"

        ontologies = requests.get(
            analytics_url, headers=headers, allow_redirects=True
        ).json()

        logging.info("Retrieving metadata for each...")
        with open(f"{self.output_dir}/{ONTOLOGY_LIST_NAME}", "w") as outfile:
            outfile.write(f"id\tname\tcurrent_version\tsubmission_id\n")
            for acronym in ontologies:
                metadata_url = f"https://data.bioontology.org/ontologies/{acronym}"
                metadata = requests.get(metadata_url, headers=headers).json()
                latest_submission_url = f"https://data.bioontology.org/ontologies/{acronym}/latest_submission"
                latest_submission = requests.get(
                    latest_submission_url, headers=headers
                ).json()

                name = metadata["name"]
                current_version = latest_submission["version"]
                submission_id = latest_submission["submissionId"]
                outfile.write(
                    f"{acronym}\t{name}\t{current_version}\t{submission_id}\n"
                )

        logging.info(f"Wrote to {self.output_dir}/{ONTOLOGY_LIST_NAME}")
