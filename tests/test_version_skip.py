"""A run should skip what it already has, not what it failed to build.

Version-skip stops a monthly run re-transforming 1100 unchanged ontologies. It
did that by comparing submission ids alone, which also skipped every *failed*
ontology whose submission had not moved -- so a failure was carried forward as
if it were a graph, and a fix to this pipeline could never reach the ontologies
it fixed. The five transform fixes in #138, #139, #141, #142 and #152 would
have gone to nothing on the next scheduled run: those ontologies' submissions
have not changed, so none of them would have been retried.

What is worth carrying forward is an artifact we have. Anything else gets
another go.
"""

import json
import os
import tempfile
from unittest import TestCase

import yaml
from click.testing import CliRunner

from kg_bioportal.cli import main


def entry(oid, status="OK", submission="1", reason="", **kw):
    e = {
        "id": oid, "status": status, "reason": reason, "name": oid,
        "submission_id": submission, "source_bytes": 1000,
        "nodecount": 10 if status == "OK" else 0,
        "edgecount": 20 if status == "OK" else 0,
    }
    e.update(kw)
    return e


class VersionSkipTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runner = CliRunner()

    def index(self, entries):
        path = os.path.join(self._tmp.name, "onto_stats.yaml")
        with open(path, "w") as f:
            yaml.dump({"ontologies": entries}, f, sort_keys=False)
        return path

    def bioportal_list(self, submissions):
        """The ontology list as BioPortal currently serves it."""
        path = os.path.join(self._tmp.name, "ontologylist.tsv")
        with open(path, "w") as f:
            f.write("id\tname\tversion\tsubmission_id\n")
            for acr, sub in submissions.items():
                f.write(f"{acr}\tname\tv1\t{sub}\n")
        return path

    def scheduled(self, entries, submissions):
        """The acronyms a scheduled run would transform."""
        result = self.runner.invoke(
            main,
            ["shard-list", "-f", self.bioportal_list(submissions), "-n", "5",
             "--index", self.index(entries)],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, result.output)
        return sorted(" ".join(json.loads(result.stdout.strip())).split())


class TestWhatIsCarriedForward(VersionSkipTestCase):
    def test_an_unchanged_ok_ontology_is_skipped(self):
        # The whole point of version-skip: 1100 graphs do not get rebuilt.
        self.assertEqual(
            self.scheduled([entry("AGRO")], {"AGRO": "1"}), [])

    def test_a_changed_ok_ontology_is_transformed(self):
        self.assertEqual(
            self.scheduled([entry("AGRO", submission="1")], {"AGRO": "2"}), ["AGRO"])

    def test_an_ontology_not_in_the_index_is_transformed(self):
        self.assertEqual(self.scheduled([entry("AGRO")], {"NEW": "1"}), ["NEW"])


class TestFailuresAreRetried(VersionSkipTestCase):
    """The change: a failure has no artifact, so it is not worth keeping."""

    def test_a_transform_failure_is_retried(self):
        # This is the case that matters: FYPO failed, BioPortal has not
        # republished it, and a fix landed on our side in the meantime.
        self.assertEqual(
            self.scheduled(
                [entry("FYPO", status="Failed", reason="transform_error_relax")],
                {"FYPO": "1"}),
            ["FYPO"])

    def test_every_transform_error_stage_is_retried(self):
        stages = ["decompress", "convert", "relax", "kgx"]
        entries = [entry(f"O{i}", status="Failed", reason=f"transform_error_{s}")
                   for i, s in enumerate(stages)]
        self.assertEqual(
            self.scheduled(entries, {f"O{i}": "1" for i in range(len(stages))}),
            sorted(f"O{i}" for i in range(len(stages))))

    def test_a_skipped_ontology_is_retried(self):
        # too_slow and too_large are worth another go: the gates are configurable
        # and the runner's capacity changes.
        self.assertEqual(
            self.scheduled(
                [entry("ROR", status="Skipped", reason="too_large")], {"ROR": "1"}),
            ["ROR"])

    def test_an_unusable_source_is_retried(self):
        # Cheap: it fails again at convert in seconds, and if the maintainers
        # fix the file without a new submission, we pick it up.
        self.assertEqual(
            self.scheduled(
                [entry("NCOD", status="Failed", reason="invalid_source")],
                {"NCOD": "1"}),
            ["NCOD"])

    def test_a_licensed_ontology_is_retried_but_costs_nothing(self):
        # No source is served, so it stops at download. Keeping it in the run
        # means a licence that becomes available is noticed.
        self.assertEqual(
            self.scheduled(
                [entry("NDDF", status="Failed", reason="license_restricted")],
                {"NDDF": "1"}),
            ["NDDF"])

    def test_a_download_failure_was_already_retried(self):
        # These carry submission_id NA, so they were never skipped; the change
        # does not alter them.
        self.assertEqual(
            self.scheduled(
                [entry("X", status="Failed", reason="no_download_file",
                       submission="NA")],
                {"X": "3"}),
            ["X"])


class TestTheMixedRun(VersionSkipTestCase):
    """What a real monthly run looks like after the change."""

    def setUp(self):
        super().setUp()
        self.entries = [
            entry("AGRO"),                                     # fine, unchanged
            entry("CHEBI"),                                    # fine, unchanged
            entry("UBERON", submission="4"),                   # fine, republished
            entry("FYPO", status="Failed", reason="transform_error_kgx"),
            entry("ELD", status="Failed", reason="transform_error_relax"),
            entry("ROR", status="Skipped", reason="too_large"),
        ]
        self.submissions = {"AGRO": "1", "CHEBI": "1", "UBERON": "5",
                            "FYPO": "1", "ELD": "1", "ROR": "1", "BRANDNEW": "1"}

    def test_only_the_working_unchanged_graphs_are_skipped(self):
        self.assertEqual(
            self.scheduled(self.entries, self.submissions),
            ["BRANDNEW", "ELD", "FYPO", "ROR", "UBERON"])

    def test_the_count_of_skips_is_reported(self):
        result = self.runner.invoke(
            main,
            ["shard-list", "-f", self.bioportal_list(self.submissions), "-n", "5",
             "--index", self.index(self.entries)],
            catch_exceptions=False,
        )
        self.assertIn("2 unchanged skipped", result.stderr)

    def test_a_run_with_nothing_to_do_is_still_a_no_op(self):
        # A month where nothing changed and nothing failed must stay empty, or
        # the scheduled run stops being free.
        self.assertEqual(
            self.scheduled([entry("AGRO"), entry("CHEBI")],
                           {"AGRO": "1", "CHEBI": "1"}),
            [])
