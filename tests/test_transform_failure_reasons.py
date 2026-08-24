"""A failed transform has to say what failed, and why.

Every failing ontology used to land in onto_stats.yaml with the same string:

    - id: FYPO
      status: Failed
      reason: transform_error

so auditing 66 failures meant reconstructing the stage from half a million lines
of Actions logs, which GitHub expires (#134). These tests drive a transform to
its knees at each stage in turn and assert that the stats say which one, and
carry the message that stage gave.
"""

import os
import tempfile
from unittest import TestCase, mock

import yaml

from kg_bioportal.robot_utils import RobotResult, _error_text
from kg_bioportal.transformer import (
    MAX_DETAIL_CHARS,
    TRANSFORM_STAGES,
    SourceTooLarge,
    TransformOutcome,
    Transformer,
    TransformTimeout,
    reason_for_stage,
    summarize_detail,
)

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
</rdf:RDF>
"""

CONVERT_ERROR = (
    "java.lang.IllegalArgumentException: org.semanticweb.owlapi.model."
    "UnloadableImportException: Could not load imported ontology: "
    "<http://purl.example.org/dead.owl>"
)
RELAX_ERROR = "org.semanticweb.owlapi.model.OWLOntologyStorageException: ONTOLOGY STORAGE ERROR"


class FakeKGXTransformer:
    """Writes the TSVs KGX would, or raises what KGX would."""

    raises = None

    def __init__(self, *args, **kwargs):
        pass

    def transform(self, input_args, output_args):
        if type(self).raises is not None:
            raise type(self).raises
        for suffix in ("_nodes.tsv", "_edges.tsv"):
            with open(output_args["filename"] + suffix, "w") as f:
                f.write("id\n")


class TransformFailureTestCase(TestCase):
    """Drives Transformer with ROBOT and KGX faked, one stage failing at a time."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "transformed")
        os.makedirs(self.output_dir, exist_ok=True)

        self.txr = Transformer.__new__(Transformer)
        self.txr.input_dir = self.input_dir
        self.txr.output_dir = self.output_dir
        self.txr.timeout_sec = 60
        self.txr.timeout_min = 1
        self.txr.max_source_bytes = 0
        self.txr.robot_path = "/nonexistent/robot"
        self.txr.robot_env = {}

        self.source = os.path.join(self.input_dir, "ONTO", "1", "onto.owl")
        os.makedirs(os.path.dirname(self.source), exist_ok=True)
        with open(self.source, "w") as f:
            f.write(RDFXML)

        FakeKGXTransformer.raises = None

    def run_transform(self, convert=None, relax=None, kgx_raises=None, all_at_once=False):
        """Run one ontology through, with the named stage rigged to fail.

        `convert` and `relax` take a RobotResult; None means "succeed and write
        the file the step would have".
        """
        def writer(result):
            def run(**kwargs):
                if result is not None and not result.ok:
                    return result
                os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
                with open(kwargs["output_path"], "w") as f:
                    f.write(RDFXML)
                return RobotResult(True)
            return run

        FakeKGXTransformer.raises = kgx_raises
        with mock.patch("kg_bioportal.transformer.robot_convert", writer(convert)), \
             mock.patch("kg_bioportal.transformer.robot_relax", writer(relax)), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGXTransformer):
            if all_at_once:
                self.txr.transform_all(compress=False)
                return None
            return self.txr.transform(self.source, compress=False)

    def stats(self):
        """The ONTO entry of the onto_stats.yaml just written."""
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            data = yaml.safe_load(f)
        by_id = {o["id"]: o for o in data["ontologies"]}
        self.assertIn("ONTO", by_id, "the ontology is missing from the stats")
        return by_id["ONTO"]


class TestStageIsRecorded(TransformFailureTestCase):
    def test_convert_failure_names_the_convert_stage(self):
        outcome = self.run_transform(convert=RobotResult(False, CONVERT_ERROR))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "convert")

    def test_relax_failure_names_the_relax_stage(self):
        outcome = self.run_transform(relax=RobotResult(False, RELAX_ERROR))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "relax")

    def test_kgx_failure_names_the_kgx_stage(self):
        outcome = self.run_transform(kgx_raises=TypeError(
            "'<' not supported between instances of 'str' and 'int'"))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "kgx")

    def test_decompress_failure_names_the_decompress_stage(self):
        archive = os.path.join(self.input_dir, "ONTO", "1", "onto.owl.gz")
        with open(archive, "wb") as f:
            f.write(b"not actually gzipped")
        outcome = self.txr.transform(archive, compress=False)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "decompress")

    def test_a_kgx_constructor_failure_is_recorded_not_raised(self):
        # Building the transformer is part of the KGX stage; an exception
        # escaping here would end the shard, not just this ontology.
        class ExplodingKGX:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("kgx would not start")

        def writer(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        with mock.patch("kg_bioportal.transformer.robot_convert", writer), \
             mock.patch("kg_bioportal.transformer.robot_relax", writer), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", ExplodingKGX):
            outcome = self.txr.transform(self.source, compress=False)
        self.assertEqual(outcome.stage, "kgx")
        self.assertIn("kgx would not start", outcome.detail)

    def test_a_successful_transform_has_no_stage_or_detail(self):
        outcome = self.run_transform()
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.stage, "")
        self.assertEqual(outcome.detail, "")


class TestDetailIsCarried(TransformFailureTestCase):
    def test_robot_error_text_reaches_the_outcome(self):
        outcome = self.run_transform(convert=RobotResult(False, CONVERT_ERROR))
        self.assertIn("UnloadableImportException", outcome.detail)
        self.assertIn("purl.example.org/dead.owl", outcome.detail)

    def test_kgx_exception_reaches_the_outcome(self):
        outcome = self.run_transform(kgx_raises=TypeError(
            "'<' not supported between instances of 'str' and 'int'"))
        self.assertIn("not supported between instances", outcome.detail)

    def test_an_exception_with_no_message_still_says_its_type(self):
        outcome = self.run_transform(kgx_raises=RecursionError())
        self.assertIn("RecursionError", outcome.detail)


class TestStatsFileRecordsIt(TransformFailureTestCase):
    """The point of the exercise: reading a run is a grep of onto_stats.yaml."""

    def test_convert_failure_is_written_to_onto_stats(self):
        self.run_transform(convert=RobotResult(False, CONVERT_ERROR), all_at_once=True)
        entry = self.stats()
        self.assertEqual(entry["status"], "Failed")
        self.assertEqual(entry["reason"], "transform_error_convert")
        self.assertIn("UnloadableImportException", entry["detail"])

    def test_kgx_failure_is_written_to_onto_stats(self):
        self.run_transform(kgx_raises=ValueError("bad literal"), all_at_once=True)
        entry = self.stats()
        self.assertEqual(entry["reason"], "transform_error_kgx")
        self.assertIn("bad literal", entry["detail"])

    def test_every_reason_still_greps_as_a_transform_error(self):
        # Whatever the stage, the coarse grouping the old string gave is intact.
        for stage in TRANSFORM_STAGES:
            self.assertTrue(reason_for_stage(stage).startswith("transform_error"))

    def test_a_stageless_failure_keeps_the_old_reason(self):
        self.assertEqual(reason_for_stage(""), "transform_error")

    def test_successful_transforms_carry_no_detail_field(self):
        self.run_transform(all_at_once=True)
        entry = self.stats()
        self.assertEqual(entry["status"], "OK")
        self.assertNotIn("detail", entry)

    def test_the_stats_file_is_still_valid_yaml_with_a_robot_error_in_it(self):
        # ROBOT errors carry colons, angle brackets and quotes; a detail field
        # that broke the YAML would take the whole index down with it.
        self.run_transform(convert=RobotResult(
            False, 'ERROR: could not load <http://x/y#z>: "bad" value @ line 1'),
            all_at_once=True)
        self.assertIn("could not load", self.stats()["detail"])


class TestSkipsAlsoExplainThemselves(TransformFailureTestCase):
    """A deliberate skip keeps its own reason, and says what the limit was.

    These are not transform_error and must not be relabelled as one -- nothing
    about them is broken -- but "too_slow" alone doesn't say slower than what.
    """

    def run_with(self, exception):
        with mock.patch.object(Transformer, "transform", side_effect=exception):
            self.txr.transform_all(compress=False)
        return self.stats()

    def test_a_timeout_stays_too_slow_and_names_the_limit(self):
        entry = self.run_with(TransformTimeout())
        self.assertEqual(entry["status"], "Skipped")
        self.assertEqual(entry["reason"], "too_slow")
        self.assertIn("1 min", entry["detail"])

    def test_an_oversized_source_stays_too_large_and_names_the_size(self):
        entry = self.run_with(SourceTooLarge("ONTO unpacks to 141.0 MB (> 100 MB limit)"))
        self.assertEqual(entry["status"], "Skipped")
        self.assertEqual(entry["reason"], "too_large")
        self.assertIn("141.0 MB", entry["detail"])


class TestDetailSummary(TestCase):
    def test_a_multiline_message_becomes_one_line(self):
        self.assertEqual(summarize_detail("first line\n  second line\n"), "first line second line")

    def test_a_long_message_is_truncated(self):
        detail = summarize_detail("x" * (MAX_DETAIL_CHARS * 2))
        self.assertLessEqual(len(detail), MAX_DETAIL_CHARS)
        self.assertTrue(detail.endswith("..."))

    def test_a_short_message_is_left_alone(self):
        self.assertEqual(summarize_detail("ONTOLOGY STORAGE ERROR"), "ONTOLOGY STORAGE ERROR")

    def test_an_exception_can_be_passed_directly(self):
        self.assertEqual(summarize_detail(ValueError("nope")), "nope")


class FakeShError(Exception):
    """Stands in for sh.ErrorReturnCode, which carries stdout/stderr as bytes."""

    def __init__(self, stderr, message="RAN: robot convert ... (the whole blob)"):
        super().__init__(message)
        self.stderr = stderr.encode() if isinstance(stderr, str) else stderr


# Verbatim from ROBOT 1.9.6 (an unresolvable import), stack frames included.
ROBOT_STDERR = """java.lang.IllegalArgumentException: org.semanticweb.owlapi.model.\
UnloadableImportException: Could not load imported ontology: <http://x.invalid/dead.owl>
	at org.obolibrary.robot.CommandLineHelper.updateInputOntology(CommandLineHelper.java:585)
	at org.obolibrary.robot.ConvertCommand.execute(ConvertCommand.java:130)
Caused by: org.semanticweb.owlapi.model.UnloadableImportException: Could not load
	... 6 more
"""


class TestRobotErrorText(TestCase):
    """What gets pulled out of a ROBOT failure decides whether the stats help."""

    def test_the_exception_line_is_picked(self):
        detail = _error_text(FakeShError(ROBOT_STDERR))
        self.assertIn("UnloadableImportException", detail)
        self.assertIn("x.invalid/dead.owl", detail)

    def test_stack_frames_are_not_picked(self):
        self.assertNotIn("at org.obolibrary", _error_text(FakeShError(ROBOT_STDERR)))

    def test_jvm_preamble_is_skipped(self):
        # A runner with JAVA_TOOL_OPTIONS set prints a line to stderr before
        # ROBOT runs at all; taking it would bury the actual error.
        noisy = ("Picked up JAVA_TOOL_OPTIONS: -Dhttps.proxyHost=127.0.0.1\n"
                 "SLF4J: Defaulting to no-operation (NOP) logger implementation\n"
                 + ROBOT_STDERR)
        detail = _error_text(FakeShError(noisy))
        self.assertNotIn("Picked up", detail)
        self.assertNotIn("SLF4J", detail)
        self.assertIn("UnloadableImportException", detail)

    def test_a_message_with_no_throwable_still_comes_through(self):
        self.assertEqual(_error_text(FakeShError("something went sideways\n")),
                         "something went sideways")

    def test_empty_stderr_falls_back_to_the_exception(self):
        self.assertIn("RAN: robot convert", _error_text(FakeShError("")))

    def test_an_exception_without_stderr_at_all_is_handled(self):
        self.assertEqual(_error_text(ValueError("plain old exception")),
                         "plain old exception")

    def test_the_text_is_capped(self):
        self.assertLessEqual(len(_error_text(FakeShError("Error: " + "x" * 5000))), 500)


class TestOutcomeContract(TestCase):
    def test_a_failure_carries_no_counts(self):
        outcome = TransformOutcome.failed("kgx", "boom")
        self.assertFalse(outcome.success)
        self.assertEqual((outcome.nodecount, outcome.edgecount), (0, 0))

    def test_robot_result_is_truthy_only_when_ok(self):
        # transform() tests these with `if not ...`, as it did when they were bools.
        self.assertTrue(RobotResult(True))
        self.assertFalse(RobotResult(False, "boom"))
