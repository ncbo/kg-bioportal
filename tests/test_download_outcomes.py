"""Tests for how download outcomes are classified and counted.

Covers the split of the old catch-all ``not_downloadable`` into reasons driven
by the download endpoint's status code, and the separate accounting for
license-restricted ontologies.
"""

import csv
import os
import tempfile
from unittest import TestCase

from kg_bioportal.downloader import DOWNLOAD_REPORT_NAME, Downloader
from kg_bioportal.transformer import summarize

METADATA = {"name": "Test Ontology"}
SUBMISSION = {"submissionId": "3", "version": "1.0", "released": "2026-01-01"}


class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code=200, headers=None, payload=None, text="", chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text
        self._chunks = chunks
        self.closed = False

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)

    def close(self):
        self.closed = True


class FakeSession:
    """Answers the three GETs Downloader.download makes, in order."""

    def __init__(self, download_response, metadata_response=None, submission_payload=SUBMISSION):
        self.download_response = download_response
        self.metadata_response = metadata_response or FakeResponse(payload=METADATA)
        self.submission_payload = submission_payload

    def get(self, url, **kwargs):
        if url.endswith("/download"):
            return self.download_response
        if url.endswith("/latest_submission"):
            return FakeResponse(payload=self.submission_payload)
        return self.metadata_response


def run_download(download_response, **session_kwargs):
    """Run one ontology through Downloader.download with a faked session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dl = Downloader(output_dir=tmpdir, api_key="fake-key")
        dl.requests_session = FakeSession(download_response, **session_kwargs)
        results = dl.download(["TESTONTO"])
        with open(os.path.join(tmpdir, DOWNLOAD_REPORT_NAME), newline="") as f:
            report = list(csv.DictReader(f, delimiter="\t"))
    return results[0], report[0]


class TestDownloadOutcomeReasons(TestCase):
    """The status code, not the missing header, decides the reason."""

    def test_403_is_license_restricted(self):
        result, _ = run_download(
            FakeResponse(status_code=403, text="You must accept the license terms.")
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "license_restricted")
        self.assertEqual(result["http_status"], 403)

    def test_401_is_also_license_restricted(self):
        # From our side, "not authorized" and "forbidden" are the same situation.
        result, _ = run_download(FakeResponse(status_code=401))
        self.assertEqual(result["reason"], "license_restricted")

    def test_404_is_no_download_file(self):
        result, _ = run_download(FakeResponse(status_code=404))
        self.assertEqual(result["reason"], "no_download_file")
        self.assertEqual(result["http_status"], 404)

    def test_other_non_2xx_is_download_http_error(self):
        result, _ = run_download(FakeResponse(status_code=502))
        self.assertEqual(result["reason"], "download_http_error")
        self.assertEqual(result["http_status"], 502)

    def test_2xx_without_filename_stays_not_downloadable(self):
        # BioPortal answered, just not with a file: the genuinely ambiguous case.
        result, _ = run_download(FakeResponse(status_code=200, headers={}))
        self.assertEqual(result["reason"], "not_downloadable")
        self.assertEqual(result["http_status"], 200)

    def test_successful_download_is_recorded(self):
        result, _ = run_download(
            FakeResponse(
                status_code=200,
                headers={"Content-Disposition": 'attachment; filename="testonto.owl"'},
                chunks=[b"<rdf:RDF/>"],
            )
        )
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["source_bytes"], len(b"<rdf:RDF/>"))

    def test_error_responses_are_closed(self):
        response = FakeResponse(status_code=403)
        run_download(response)
        self.assertTrue(response.closed, "the streamed response must be released")


class TestDownloadReport(TestCase):
    """The status code has to survive into the report the transform step reads."""

    def test_report_carries_http_status(self):
        _, row = run_download(FakeResponse(status_code=403))
        self.assertIn("http_status", row)
        self.assertEqual(row["http_status"], "403")
        self.assertEqual(row["reason"], "license_restricted")

    def test_report_leaves_http_status_blank_when_irrelevant(self):
        # Skiplisted ontologies never hit the network, so there is no code.
        with tempfile.TemporaryDirectory() as tmpdir:
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            dl.requests_session = FakeSession(FakeResponse())
            dl.download(["NCBITAXON"])
            with open(os.path.join(tmpdir, DOWNLOAD_REPORT_NAME), newline="") as f:
                row = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(row["reason"], "skiplist")
        self.assertEqual(row["http_status"], "")


def entry(status, reason="", nodes=0, edges=0):
    return {"status": status, "reason": reason, "nodecount": nodes, "edgecount": edges}


class TestSummarize(TestCase):
    """licensedcount is its own line and does not inflate failedcount."""

    def setUp(self):
        self.onto_log = {
            "GOOD": entry("OK", nodes=10, edges=20),
            "ALSOGOOD": entry("OK", nodes=5, edges=7),
            "BIG": entry("Skipped", "too_large"),
            "GIANT": entry("Skipped", "skiplist"),
            "BROKEN": entry("Failed", "transform_error"),
            "MISSING": entry("Failed", "no_download_file"),
            "UMLS1": entry("Failed", "license_restricted"),
            "UMLS2": entry("Failed", "license_restricted"),
        }

    def test_licensed_are_counted_separately(self):
        totals = summarize(self.onto_log)
        self.assertEqual(totals["licensedcount"], 2)

    def test_licensed_are_excluded_from_failed(self):
        totals = summarize(self.onto_log)
        # Four entries have status Failed; only two of them are real failures.
        self.assertEqual(totals["failedcount"], 2)

    def test_every_ontology_is_accounted_for_exactly_once(self):
        totals = summarize(self.onto_log)
        counted = (
            totals["totalcount"]
            + totals["skippedcount"]
            + totals["failedcount"]
            + totals["licensedcount"]
        )
        self.assertEqual(counted, len(self.onto_log))

    def test_counts_are_unchanged_without_licensed_entries(self):
        for acronym in ("UMLS1", "UMLS2"):
            del self.onto_log[acronym]
        totals = summarize(self.onto_log)
        self.assertEqual(totals["failedcount"], 2)
        self.assertEqual(totals["licensedcount"], 0)

    def test_node_and_edge_totals(self):
        totals = summarize(self.onto_log)
        self.assertEqual(totals["totalnodecount"], 15)
        self.assertEqual(totals["totaledgecount"], 27)
