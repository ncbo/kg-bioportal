"""A dropped connection costs one ontology, never the shard (#180).

On 2026-09-09 BioPortal closed every large download after a megabyte or two,
and the ChunkedEncodingError that raised out of the streaming loop ended all
twenty shards of the run before a single ontology was recorded. The download
report never got written, so finalize carried the whole run forward as if
nothing had happened.
"""

import csv
import os
import tempfile
from unittest import TestCase, mock

import requests

from kg_bioportal.downloader import DOWNLOAD_REPORT_NAME, Downloader

METADATA = {"name": "Test Ontology"}
SUBMISSION = {"submissionId": "3", "version": "1.0", "released": "2026-01-01"}
FILE_HEADERS = {"Content-Disposition": 'attachment; filename="onto.owl"', "Content-Length": "6"}


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None, chunks=(), break_after=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self._chunks = list(chunks)
        # Raise the error BioPortal's dropped connections raised, after this
        # many chunks have been yielded.
        self._break_after = break_after
        self.closed = False
        self.text = ""

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=None):
        for i, chunk in enumerate(self._chunks):
            if self._break_after is not None and i >= self._break_after:
                raise requests.exceptions.ChunkedEncodingError(
                    "Connection broken: IncompleteRead(81549 bytes read, 216176459 more expected)"
                )
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    """Answers the GETs, handing out download responses in order per ontology."""

    def __init__(self, downloads, metadata_error=None):
        # {acronym: [response, response, ...]} -- one per fetch attempt.
        self.downloads = {k: list(v) for k, v in downloads.items()}
        self.metadata_error = metadata_error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        acronym = url.split("/ontologies/")[1].split("/")[0]
        if url.endswith("/download"):
            return self.downloads[acronym].pop(0)
        if url.endswith("/latest_submission"):
            return FakeResponse(payload=SUBMISSION)
        if self.metadata_error and acronym in self.metadata_error:
            raise self.metadata_error[acronym]
        return FakeResponse(payload=METADATA)


def run(downloads, acronyms, **session_kwargs):
    with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch("kg_bioportal.downloader.time.sleep") as sleep:
        dl = Downloader(output_dir=tmpdir, api_key="fake-key")
        dl.requests_session = FakeSession(downloads, **session_kwargs)
        results = dl.download(acronyms)
        with open(os.path.join(tmpdir, DOWNLOAD_REPORT_NAME), newline="") as f:
            report = list(csv.DictReader(f, delimiter="\t"))
        files = {r["id"]: os.path.exists(r["path"]) if r["path"] else False for r in results}
    return {r["id"]: r for r in results}, {r["id"]: r for r in report}, files, sleep, dl.requests_session


def good():
    return FakeResponse(headers=FILE_HEADERS, chunks=[b"abc", b"def"])


def broken():
    return FakeResponse(headers=FILE_HEADERS, chunks=[b"abc", b"def"], break_after=1)


class TestBrokenStream(TestCase):
    def test_a_stream_that_keeps_breaking_is_recorded_not_raised(self):
        results, report, _, _, _ = run({"BAD": [broken(), broken(), broken()]}, ["BAD"])
        self.assertEqual(results["BAD"]["status"], "error")
        self.assertEqual(results["BAD"]["reason"], "download_error")
        self.assertIn("ChunkedEncodingError", results["BAD"]["detail"])
        self.assertIn("IncompleteRead", report["BAD"]["detail"])

    def test_the_rest_of_the_shard_still_downloads(self):
        # The whole point: 19 shards lost every ontology behind the first bad
        # stream. Now the next one is fetched as if nothing happened.
        results, _, files, _, _ = run(
            {"BAD": [broken(), broken(), broken()], "GOOD": [good()]}, ["BAD", "GOOD"]
        )
        self.assertEqual(results["GOOD"]["status"], "downloaded")
        self.assertEqual(results["GOOD"]["source_bytes"], 6)

    def test_a_stream_that_breaks_once_is_fetched_again_and_succeeds(self):
        results, _, _, sleep, session = run({"FLAKY": [broken(), good()]}, ["FLAKY"])
        self.assertEqual(results["FLAKY"]["status"], "downloaded")
        self.assertEqual(results["FLAKY"]["source_bytes"], 6)
        self.assertEqual(sum(1 for u in session.calls if u.endswith("/download")), 2)
        self.assertEqual(sleep.call_count, 1, "one wait between the two tries")

    def test_no_partial_file_is_left_behind(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("kg_bioportal.downloader.time.sleep"):
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            dl.requests_session = FakeSession({"BAD": [broken(), broken(), broken()]})
            dl.download(["BAD"])
            leftovers = [f for _, _, fs in os.walk(tmpdir) for f in fs if f != DOWNLOAD_REPORT_NAME]
        self.assertEqual(leftovers, [])

    def test_report_is_written_even_when_every_download_broke(self):
        _, report, _, _, _ = run({"BAD": [broken(), broken(), broken()]}, ["BAD"])
        self.assertIn("BAD", report)
        self.assertEqual(report["BAD"]["status"], "error")

    def test_a_reconnect_that_fails_counts_as_a_try(self):
        class Refusing(FakeSession):
            def get(self, url, **kwargs):
                if url.endswith("/download") and not self.downloads["X"]:
                    raise requests.exceptions.ConnectionError("Failed to connect")
                return super().get(url, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("kg_bioportal.downloader.time.sleep"):
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            dl.requests_session = Refusing({"X": [broken()]})
            results = dl.download(["X"])
        self.assertEqual(results[0]["reason"], "download_error")
        self.assertIn("ConnectionError", results[0]["detail"])


class TestMetadataFailures(TestCase):
    def test_a_connection_error_on_metadata_is_recorded(self):
        results, report, _, _, _ = run(
            {"GOOD": [good()]}, ["DEAD", "GOOD"],
            metadata_error={"DEAD": requests.exceptions.ConnectionError("Couldn't connect to server")},
        )
        self.assertEqual(results["DEAD"]["status"], "error")
        self.assertEqual(results["DEAD"]["reason"], "metadata_http_error")
        self.assertIn("ConnectionError", report["DEAD"]["detail"])
        self.assertEqual(results["GOOD"]["status"], "downloaded")


class TestTimeouts(TestCase):
    def test_every_request_carries_a_timeout(self):
        # A stalled connection with no timeout hangs the shard for the rest of
        # the job. Every GET the downloader makes must say how long it waits.
        seen = []

        class Recording(FakeSession):
            def get(self, url, **kwargs):
                seen.append(kwargs.get("timeout"))
                return super().get(url, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            dl.requests_session = Recording({"X": [good()]})
            dl.download(["X"])
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(t for t in seen), seen)


class TestDetailReachesTheIndex(TestCase):
    def test_transformer_seeds_the_detail_from_the_report(self):
        from kg_bioportal.transformer import Transformer

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("kg_bioportal.downloader.time.sleep"):
            raw = os.path.join(tmpdir, "raw")
            dl = Downloader(output_dir=raw, api_key="fake-key")
            dl.requests_session = FakeSession({"BAD": [broken(), broken(), broken()]})
            dl.download(["BAD"])
            txr = Transformer.__new__(Transformer)
            txr.input_dir = raw
            report = txr._load_download_report()
        self.assertIn("IncompleteRead", report["BAD"]["detail"])
