"""Downloader for KG-Bioportal."""

import csv
import logging
import os

import requests
from requests.adapters import HTTPAdapter, Retry

from kg_bioportal.config import MAX_SOURCE_MB, is_skiplisted

ONTOLOGY_LIST_NAME = "ontologylist.tsv"

# Per-ontology download outcomes are written here so later stages (transform,
# finalize) can account for ontologies that were never downloaded.
DOWNLOAD_REPORT_NAME = "download_report.tsv"

# Streaming chunk size (bytes).
_CHUNK = 1024 * 1024


class Downloader:

    def __init__(
        self,
        output_dir: str = "data/raw",
        snippet_only: bool = False,
        ignore_cache: bool = False,
        api_key: str = "",
        max_source_mb: float = MAX_SOURCE_MB,
        use_skiplist: bool = True,
    ) -> None:
        """Initializes the Downloader class.

        Args:
            output_dir: A string pointing to the location to download data to.
            snippet_only: Downloads only the first 5 kB of the source, for testing and file checks.
            ignore_cache: Ignore cache and download files even if they exist.
            api_key: API key for BioPortal.
            max_source_mb: Skip any ontology whose source file exceeds this many MB.
            use_skiplist: If True, skip ontologies on the static known-giants skiplist.

        Returns:
            None.
        """
        self.output_dir = output_dir
        self.snippet_only = snippet_only
        self.ignore_cache = ignore_cache
        self.api_key = api_key
        self.max_source_mb = max_source_mb
        self.max_source_bytes = int(max_source_mb * 1024 * 1024)
        self.use_skiplist = use_skiplist

        # Per-ontology results: list of dicts with keys
        # id, submission_id, source_bytes, path, status, reason.
        # status is one of: downloaded, skipped, error.
        self.results: list = []

        self.requests_session = requests.Session()
        self.retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 504])
        self.requests_session.mount("https://", HTTPAdapter(max_retries=self.retries))

        # If the output directory does not exist, create it
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        if not api_key:
            raise ValueError("API key is required for downloading from BioPortal.")

        return None

    def _record(self, acronym, submission_id, source_bytes, path, status, reason):
        """Append a per-ontology outcome to the results list."""
        self.results.append(
            {
                "id": acronym,
                "submission_id": submission_id,
                "source_bytes": source_bytes,
                "path": path,
                "status": status,
                "reason": reason,
            }
        )

    def download(self, onto_list: list = []) -> list:
        """Downloads data files from list of ontologies into data directory.

        Ontologies on the static skiplist, or whose source file exceeds
        ``max_source_mb``, are skipped and recorded (not downloaded).

        Args:
            onto_list: A list of ontologies to download by name.
                Names should be those used in BioPortal, e.g., PO, SEPIO, etc.

        Returns:
            The list of per-ontology result dicts (also written to
            ``download_report.tsv`` in the output directory).
        """
        headers = {"Authorization": f"apikey token={self.api_key}"}

        for ontology in onto_list:
            # Fast path: skip known giants without any network calls.
            if self.use_skiplist and is_skiplisted(ontology):
                logging.info(f"Skipping {ontology} (on known-giants skiplist).")
                self._record(ontology, "NA", 0, "", "skipped", "skiplist")
                continue

            logging.info(f"Downloading {ontology}...")

            metadata_url = f"https://data.bioontology.org/ontologies/{ontology}"
            latest_submission_url = (
                f"https://data.bioontology.org/ontologies/{ontology}/latest_submission"
            )
            download_url = (
                f"https://data.bioontology.org/ontologies/{ontology}/download"
            )

            metadata_resp = self.requests_session.get(metadata_url, headers=headers)
            if metadata_resp.status_code != 200:
                logging.error(
                    f"Failed to fetch metadata for {ontology}: HTTP {metadata_resp.status_code}"
                )
                self._record(ontology, "NA", 0, "", "error", "metadata_http_error")
                continue
            metadata = metadata_resp.json()
            logging.info(f"Name: {metadata['name']}")
            latest_submission = self.requests_session.get(
                latest_submission_url, headers=headers
            ).json()
            if len(latest_submission) > 0:
                submission_id = latest_submission["submissionId"]
            else:
                logging.warning(f"No submission found for {ontology}.")
                self._record(ontology, "NA", 0, "", "error", "no_submission")
                continue
            logging.info(
                f"Latest submission: {latest_submission['version']} - submission ID {submission_id} - released {latest_submission['released']}"
            )

            # Stream the download so we can enforce the size gate before pulling
            # the whole (potentially huge) file into memory or onto disk.
            try:
                download_onto = self.requests_session.get(
                    download_url, headers=headers, allow_redirects=True, stream=True
                )
            except requests.RequestException as e:
                logging.warning(f"Could not download {ontology}: {e}")
                self._record(ontology, submission_id, 0, "", "error", "download_error")
                continue

            try:
                onto_filename = (
                    download_onto.headers["Content-Disposition"]
                    .split("filename=")[1]
                    .replace('"', "")
                )
            except KeyError:
                logging.warning(
                    f"Could not download {ontology}. Check if the ontology is downloadable."
                )
                download_onto.close()
                self._record(ontology, submission_id, 0, "", "error", "not_downloadable")
                continue

            # Size gate 1: trust Content-Length if present.
            content_length = download_onto.headers.get("Content-Length")
            if content_length is not None and int(content_length) > self.max_source_bytes:
                logging.warning(
                    f"Skipping {ontology}: source is {int(content_length)/1024/1024:.1f} MB "
                    f"(> {self.max_source_mb} MB limit)."
                )
                download_onto.close()
                self._record(
                    ontology, submission_id, int(content_length), "", "skipped", "too_large"
                )
                continue

            outdir = f"{self.output_dir}/{ontology}/{submission_id}"
            outpath = f"{outdir}/{onto_filename}"
            if not os.path.exists(outdir):
                os.makedirs(outdir)

            # Size gate 2: enforce the cap while streaming, in case the header
            # was missing or wrong. Abort and clean up if we blow past it.
            bytes_written = 0
            too_large = False
            try:
                with open(outpath, "wb") as outfile:
                    for chunk in download_onto.iter_content(chunk_size=_CHUNK):
                        if not chunk:
                            continue
                        bytes_written += len(chunk)
                        if bytes_written > self.max_source_bytes:
                            too_large = True
                            break
                        outfile.write(chunk)
            finally:
                download_onto.close()

            if too_large:
                logging.warning(
                    f"Skipping {ontology}: source exceeded {self.max_source_mb} MB while streaming."
                )
                try:
                    os.remove(outpath)
                except OSError:
                    pass
                self._record(
                    ontology, submission_id, bytes_written, "", "skipped", "too_large"
                )
                continue

            logging.info(f"Downloaded {ontology} ({bytes_written/1024/1024:.2f} MB).")
            self._record(
                ontology, submission_id, bytes_written, outpath, "downloaded", ""
            )

        self._write_report()

        skipped = [r for r in self.results if r["status"] == "skipped"]
        errored = [r for r in self.results if r["status"] == "error"]
        if skipped:
            logging.warning(f"Skipped {len(skipped)} ontologies (too large / skiplist).")
        if errored:
            logging.warning(
                f"Encountered errors downloading: {[r['id'] for r in errored]}"
            )

        return self.results

    def _write_report(self) -> None:
        """Write per-ontology download outcomes to a TSV in the output dir."""
        report_path = os.path.join(self.output_dir, DOWNLOAD_REPORT_NAME)
        fieldnames = ["id", "submission_id", "source_bytes", "status", "reason", "path"]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            for r in self.results:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
        logging.info(f"Wrote download report to {report_path}")

    def get_ontology_list(self) -> None:
        """Get the list of ontologies from BioPortal.

        This includes the descriptive name and most recent version.
        Some versions are not specified, while others are verbose.
        In the latter case, they are truncated to the first three words.

        Args:
            None.

        Returns:
            None.
        """

        headers = {"Authorization": f"apikey token={self.api_key}"}

        logging.info("Getting set of all ontologies...")

        analytics_url = "https://data.bioontology.org/analytics"

        ontologies = self.requests_session.get(
            analytics_url, headers=headers, allow_redirects=True
        ).json()

        logging.info("Retrieving metadata for each...")
        with open(f"{self.output_dir}/{ONTOLOGY_LIST_NAME}", "w") as outfile:
            outfile.write(f"id\tname\tcurrent_version\tsubmission_id\n")
            for acronym in ontologies:
                latest_submission_url = f"https://data.bioontology.org/ontologies/{acronym}/latest_submission"
                latest_submission = self.requests_session.get(
                    latest_submission_url, headers=headers
                ).json()

                if len(latest_submission) > 0:
                    name = (
                        latest_submission["ontology"]["name"]
                        .replace("\n", " ")
                        .replace("\t", " ")
                    )
                    if latest_submission["version"]:
                        current_version = " ".join(
                            (
                                latest_submission["version"]
                                .replace("\n", " ")
                                .replace("\t", " ")
                            ).split()[:3]
                        )
                    else:
                        current_version = "NA"
                    submission_id = latest_submission["submissionId"]
                else:
                    name = acronym
                    current_version = "NA"
                    submission_id = "NA"
                outfile.write(
                    f"{acronym}\t{name}\t{current_version}\t{submission_id}\n"
                )

        logging.info(f"Wrote to {self.output_dir}/{ONTOLOGY_LIST_NAME}")
