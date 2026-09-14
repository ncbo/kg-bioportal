"""Downloader for KG-Bioportal."""

import csv
import logging
import os
import time
from typing import Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter, Retry

from kg_bioportal.config import (
    LICENSE_RESTRICTED_REASON,
    LICENSE_STATUSES,
    MAX_SOURCE_MB,
    is_skiplisted,
)

ONTOLOGY_LIST_NAME = "ontologylist.tsv"

# Per-ontology download outcomes are written here so later stages (transform,
# finalize) can account for ontologies that were never downloaded.
DOWNLOAD_REPORT_NAME = "download_report.tsv"

# Streaming chunk size (bytes).
_CHUNK = 1024 * 1024

# (connect, read) timeout for every request to BioPortal, in seconds. Without
# one a stalled connection hangs the shard for the rest of the job's six hours.
# The read timeout is per chunk, not per file: a 200 MB source that trickles is
# fine, a source that stops is not.
_TIMEOUT = (30, 300)

# How many times to fetch a source whose byte stream breaks partway, and how
# long to wait between tries. On 2026-09-09 BioPortal closed every large
# download after a megabyte or two for an evening; the retry is for the
# ordinary dropped connection, and the wait is so twenty shards do not all
# come straight back at once (#180).
_STREAM_ATTEMPTS = 3
_STREAM_BACKOFF_S = 15


def submission_license(submission: dict) -> str:
    """The license IRI a BioPortal submission records, or "".

    BioPortal keeps it as ``hasLicense`` on the submission, an IRI string
    where the submitter filled it in and null where they did not. Most did
    not: on 2026-09-14, 157 of 1,261 latest submissions carried one. The
    transformer falls back to the license the ontology's own header declares
    (see ``source_license``), and the index says which of the two it got.
    """
    value = submission.get("hasLicense")
    if isinstance(value, list):
        value = value[0] if value else ""
    return " ".join(str(value or "").split())


def bioportal_licenses(api_key: str, session=None) -> dict:
    """{acronym: license IRI} for every BioPortal ontology whose latest
    submission records one (``hasLicense``), in one request.

    Backs the ``backfill-licenses`` command, which writes BioPortal's record
    into an index built before the downloader carried it. The transform
    records the same field at download time; this is for the entries no run
    has rebuilt since.
    """
    session = session or requests.Session()
    response = session.get(
        "https://data.bioontology.org/submissions",
        params={"display": "hasLicense,ontology"},
        headers={"Authorization": f"apikey token={api_key}"},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    found = {}
    for submission in response.json():
        acronym = (submission.get("ontology") or {}).get("acronym")
        license = submission_license(submission)
        if acronym and license:
            found[acronym] = license
    return found


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

    def _record(
        self, acronym, submission_id, source_bytes, path, status, reason,
        name="", version="", http_status: Union[int, str] = "", detail: str = "",
        license: str = "",
    ):
        """Append a per-ontology outcome to the results list.

        ``http_status`` is the response code from BioPortal, recorded for the
        outcomes that hinge on it so the reason can be audited later without
        re-running the download. ``detail`` is the error text for an outcome
        that has one, on one line, the way the transformer records its own.
        ``license`` is the license IRI BioPortal holds for the submission
        (``hasLicense``), "" where it holds none; it rides along to the index
        so the site can say what a graph may be reused under.
        """
        self.results.append(
            {
                "id": acronym,
                "name": name,
                "version": version,
                "license": license,
                "submission_id": submission_id,
                "source_bytes": source_bytes,
                "path": path,
                "status": status,
                "reason": reason,
                "http_status": http_status,
                "detail": " ".join(str(detail).split())[:500],
            }
        )

    def _stream_to_file(self, response, outpath: str) -> Tuple[int, bool]:
        """Write a streaming response to ``outpath`` under the size gate.

        Returns ``(bytes_written, too_large)``. Raises whatever ``requests``
        raises when the connection breaks partway; the caller decides whether
        to try again.
        """
        bytes_written = 0
        try:
            with open(outpath, "wb") as outfile:
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > self.max_source_bytes:
                        return bytes_written, True
                    outfile.write(chunk)
        finally:
            response.close()
        return bytes_written, False

    def _fetch_source(
        self, ontology: str, download_url: str, headers: dict, response, outpath: str
    ) -> Tuple[int, bool, str]:
        """Stream a source to disk, fetching it again if the stream breaks.

        ``response`` is the already-opened streaming response for the first
        try; later tries open their own. A broken stream used to escape as a
        ChunkedEncodingError and end the whole shard, every ontology behind it
        included (#180). Now it costs at most this one ontology.

        Returns ``(bytes_written, too_large, error)``; ``error`` is "" on
        success and the last exception's text when every try failed.
        """
        error = ""
        for attempt in range(1, _STREAM_ATTEMPTS + 1):
            if response is None:
                try:
                    response = self.requests_session.get(
                        download_url, headers=headers, allow_redirects=True,
                        stream=True, timeout=_TIMEOUT,
                    )
                except requests.RequestException as e:
                    error = f"{type(e).__name__}: {e}"
                    logging.warning(f"{ontology}: fetch attempt {attempt} failed to connect: {error}")
                    response = None
                    self._wait_before_retry(attempt)
                    continue
                if not response.ok:
                    error = f"HTTP {response.status_code} on retry"
                    response.close()
                    response = None
                    self._wait_before_retry(attempt)
                    continue
            try:
                return (*self._stream_to_file(response, outpath), "")
            except (requests.RequestException, OSError) as e:
                error = f"{type(e).__name__}: {e}"
                logging.warning(
                    f"{ontology}: download broke on attempt {attempt} of {_STREAM_ATTEMPTS}: {error}"
                )
                try:
                    os.remove(outpath)
                except OSError:
                    pass
                response = None
                self._wait_before_retry(attempt)
        return 0, False, error

    @staticmethod
    def _wait_before_retry(attempt: int) -> None:
        if attempt < _STREAM_ATTEMPTS:
            time.sleep(_STREAM_BACKOFF_S * attempt)

    @staticmethod
    def _body_snippet(response) -> str:
        """First line of an error response body, for the log.

        BioPortal explains itself in the body ("You must accept the license
        terms..."), which is the quickest way to tell a licensing refusal from
        anything else. Best effort only — never let this raise.
        """
        try:
            text = " ".join(response.text[:200].split())
        except Exception:  # noqa: BLE001 - diagnostics must not break the download
            return ""
        return text

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

            # The metadata calls are guarded like the download: a connection
            # that drops here is this ontology's problem, not the shard's.
            try:
                metadata_resp = self.requests_session.get(
                    metadata_url, headers=headers, timeout=_TIMEOUT
                )
            except requests.RequestException as e:
                logging.error(f"Failed to fetch metadata for {ontology}: {e}")
                self._record(ontology, "NA", 0, "", "error", "metadata_http_error",
                             detail=f"{type(e).__name__}: {e}")
                continue
            if metadata_resp.status_code != 200:
                logging.error(
                    f"Failed to fetch metadata for {ontology}: HTTP {metadata_resp.status_code}"
                )
                self._record(ontology, "NA", 0, "", "error", "metadata_http_error",
                             http_status=metadata_resp.status_code)
                continue
            metadata = metadata_resp.json()
            onto_name = str(metadata.get("name") or ontology)
            logging.info(f"Name: {onto_name}")
            try:
                latest_submission = self.requests_session.get(
                    latest_submission_url, headers=headers, timeout=_TIMEOUT
                ).json()
            except (requests.RequestException, ValueError) as e:
                logging.error(f"Failed to fetch the latest submission for {ontology}: {e}")
                self._record(ontology, "NA", 0, "", "error", "metadata_http_error",
                             name=onto_name, detail=f"{type(e).__name__}: {e}")
                continue
            if len(latest_submission) > 0:
                submission_id = latest_submission["submissionId"]
                onto_version = str(latest_submission.get("version") or "NA")
                onto_license = submission_license(latest_submission)
            else:
                logging.warning(f"No submission found for {ontology}.")
                self._record(ontology, "NA", 0, "", "error", "no_submission", name=onto_name)
                continue
            logging.info(
                f"Latest submission: {latest_submission['version']} - submission ID {submission_id} - released {latest_submission['released']}"
            )

            # Stream the download so we can enforce the size gate before pulling
            # the whole (potentially huge) file into memory or onto disk.
            try:
                download_onto = self.requests_session.get(
                    download_url, headers=headers, allow_redirects=True, stream=True,
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as e:
                logging.warning(f"Could not download {ontology}: {e}")
                self._record(ontology, submission_id, 0, "", "error", "download_error",
                             name=onto_name, version=onto_version,
                             detail=f"{type(e).__name__}: {e}", license=onto_license)
                continue

            # Why we didn't get a file matters, and the status code is the only
            # thing that distinguishes the cases. Without this check every one of
            # them looks like "not_downloadable", which lumps licensed
            # terminologies (working as intended) in with broken records.
            code = download_onto.status_code
            if not download_onto.ok:
                if code in LICENSE_STATUSES:
                    reason = LICENSE_RESTRICTED_REASON
                    note = "license does not cover this API key"
                elif code == 404:
                    reason = "no_download_file"
                    note = "no source file attached to the submission"
                else:
                    reason = "download_http_error"
                    note = "unexpected response"
                logging.warning(
                    f"Not downloading {ontology}: HTTP {code} ({note}). "
                    f"{self._body_snippet(download_onto)}"
                )
                download_onto.close()
                self._record(ontology, submission_id, 0, "", "error", reason,
                             name=onto_name, version=onto_version, http_status=code,
                             license=onto_license)
                continue

            try:
                onto_filename = (
                    download_onto.headers["Content-Disposition"]
                    .split("filename=")[1]
                    .replace('"', "")
                )
            except KeyError:
                # A 2xx with no filename: BioPortal answered, but not with a file.
                logging.warning(
                    f"Could not download {ontology}: HTTP {code} with no Content-Disposition. "
                    f"Check if the ontology is downloadable."
                )
                download_onto.close()
                self._record(ontology, submission_id, 0, "", "error", "not_downloadable",
                             name=onto_name, version=onto_version, http_status=code,
                             license=onto_license)
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
                    ontology, submission_id, int(content_length), "", "skipped", "too_large",
                    name=onto_name, version=onto_version, license=onto_license,
                )
                continue

            outdir = f"{self.output_dir}/{ontology}/{submission_id}"
            outpath = f"{outdir}/{onto_filename}"
            if not os.path.exists(outdir):
                os.makedirs(outdir)

            # Size gate 2: enforce the cap while streaming, in case the header
            # was missing or wrong. Abort and clean up if we blow past it. A
            # stream that breaks is fetched again, and if it keeps breaking
            # this ontology is recorded as the failure, not the shard.
            bytes_written, too_large, error = self._fetch_source(
                ontology, download_url, headers, download_onto, outpath
            )
            if error:
                logging.error(f"Could not download {ontology}: {error}")
                self._record(ontology, submission_id, 0, "", "error", "download_error",
                             name=onto_name, version=onto_version, detail=error,
                             license=onto_license)
                continue

            if too_large:
                logging.warning(
                    f"Skipping {ontology}: source exceeded {self.max_source_mb} MB while streaming."
                )
                try:
                    os.remove(outpath)
                except OSError:
                    pass
                self._record(
                    ontology, submission_id, bytes_written, "", "skipped", "too_large",
                    name=onto_name, version=onto_version, license=onto_license,
                )
                continue

            logging.info(f"Downloaded {ontology} ({bytes_written/1024/1024:.2f} MB).")
            self._record(
                ontology, submission_id, bytes_written, outpath, "downloaded", "",
                name=onto_name, version=onto_version, license=onto_license,
            )

        self._write_report()

        skipped = [r for r in self.results if r["status"] == "skipped"]
        errored = [r for r in self.results if r["status"] == "error"]
        licensed = [r for r in errored if r["reason"] == LICENSE_RESTRICTED_REASON]
        if skipped:
            logging.warning(f"Skipped {len(skipped)} ontologies (too large / skiplist).")
        if licensed:
            # Not a failure: we simply aren't licensed for these. Reported apart
            # from the errors so a run's real problems stay visible.
            logging.info(
                f"{len(licensed)} ontologies are license-restricted: {[r['id'] for r in licensed]}"
            )
        if len(errored) > len(licensed):
            logging.warning(
                "Encountered errors downloading: "
                f"{[r['id'] for r in errored if r['reason'] != LICENSE_RESTRICTED_REASON]}"
            )

        return self.results

    def _write_report(self) -> None:
        """Write per-ontology download outcomes to a TSV in the output dir."""
        report_path = os.path.join(self.output_dir, DOWNLOAD_REPORT_NAME)
        fieldnames = ["id", "name", "version", "license", "submission_id", "source_bytes",
                      "status", "reason", "http_status", "detail", "path"]
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
