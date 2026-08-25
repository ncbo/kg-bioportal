"""A source ROBOT cannot read is not the same as a transform that went wrong.

Four ontologies fail on the file exactly as BioPortal served it:

    INVALID ONTOLOGY FILE ERROR Could not load a valid ontology from file:
    shedding-hub.ttl

Nothing on this side will change that, so they should not sit in the same
bucket as the failures that are ours to fix (#142). They get their own reason,
and a detail that says which kind of unusable the file is -- broken RDF, with
the parse error an upstream report needs, or valid RDF that ROBOT will not
accept as an ontology, which might yet be readable another way.

The error strings here are ROBOT 1.9.6's own, taken from a run against a Turtle
file with a missing '.' (stderr, under -vvv, as the pipeline invokes it).
"""

import os
import tempfile
from unittest import TestCase, mock

import yaml

from kg_bioportal.robot_utils import RobotResult
from kg_bioportal.transformer import (
    INVALID_SOURCE_REASON,
    MAX_SYNTAX_CHECK_MB,
    Transformer,
    diagnose_load_failure,
    diagnose_source,
    is_load_failure,
)


def detail_of(path, **kw):
    """The phrase diagnose_source records, for tests that only care about that."""
    return diagnose_source(path, **kw).detail

LOAD_FAILURE = (
    "java.lang.IllegalArgumentException: java.io.IOException: errors#INVALID "
    "ONTOLOGY FILE ERROR Could not load a valid ontology from file: shedding-hub.ttl"
)
UNPARSABLE = (
    "org.semanticweb.owlapi.io.UnparsableOntologyException: Problem parsing "
    "file:/data/raw/NCOD/1/NCOD-2021-04-15.ttl"
)
STORAGE_ERROR = (
    "java.io.IOException: errors#ONTOLOGY STORAGE ERROR Could not save ontology to IRI"
)
IMPORT_ERROR = (
    "java.lang.IllegalArgumentException: org.semanticweb.owlapi.model."
    "UnloadableImportException: Could not load imported ontology: <http://dead/>"
)

GOOD_TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/onto> a owl:Ontology .
<http://example.org/ns#A> a owl:Class ; rdfs:label "A" .
"""

# A missing '.' after the ontology declaration -- the shape of a real typo.
BAD_TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> a owl:Ontology
<http://example.org/ns#A> a owl:Class .
"""

# What a served error page looks like when it arrives under a .ttl name.
HTML_PAGE = "<!DOCTYPE html>\n<html><head><title>Error</title></head></html>\n"

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
</rdf:RDF>
"""


class TestLoadFailureIsRecognized(TestCase):
    def test_invalid_ontology_file_error(self):
        self.assertTrue(is_load_failure(LOAD_FAILURE))

    def test_unparsable_ontology_exception(self):
        self.assertTrue(is_load_failure(UNPARSABLE))

    def test_a_write_failure_is_not_a_load_failure(self):
        # The ontology loaded fine there; the output format was the problem.
        self.assertFalse(is_load_failure(STORAGE_ERROR))

    def test_an_unresolvable_import_is_not_a_load_failure(self):
        # The source is readable; something it points at is not. Stripping
        # imports is what fixes those, and they must keep their own reason.
        self.assertFalse(is_load_failure(IMPORT_ERROR))

    def test_a_timeout_is_not_a_load_failure(self):
        self.assertFalse(is_load_failure("ROBOT convert timed out after 60s"))


class DiagnoseTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class TestDiagnosis(DiagnoseTestCase):
    """Which of the two kinds of unusable a file is."""

    def test_broken_turtle_is_reported_as_invalid(self):
        detail = detail_of(self.write("onto.ttl", BAD_TURTLE))
        self.assertIn("not valid turtle", detail)

    def test_the_parse_error_is_kept(self):
        # A line number is the difference between a useful bug report and "it
        # doesn't work".
        detail = detail_of(self.write("onto.ttl", BAD_TURTLE))
        self.assertIn("line", detail.lower())

    def test_html_served_as_an_ontology_is_named_outright(self):
        # rdflib's RDF/XML parser reads arbitrary XML, so an error page comes
        # back as "valid XML, 3 triples" unless it is caught first -- a
        # diagnosis that reassures exactly where it should not.
        detail = detail_of(self.write("onto.ttl", HTML_PAGE))
        self.assertIn("HTML document", detail)
        self.assertNotIn("triples", detail)

    def test_html_under_an_owl_name_is_caught_too(self):
        detail = detail_of(self.write("onto.owl", HTML_PAGE))
        self.assertIn("HTML document", detail)

    def test_valid_rdf_is_reported_as_such(self):
        # This is the "might be recoverable another way" case, and it must not
        # be described as broken.
        detail = detail_of(self.write("onto.ttl", GOOD_TURTLE))
        self.assertIn("valid turtle", detail)
        self.assertNotIn("not valid", detail)
        self.assertIn("will not load as an ontology", detail)

    def test_the_triple_count_is_reported(self):
        detail = detail_of(self.write("onto.ttl", GOOD_TURTLE))
        self.assertIn("3 triples", detail)

    def test_broken_rdfxml_is_reported_as_invalid(self):
        detail = detail_of(self.write("onto.owl", RDFXML.replace("</rdf:RDF>", "")))
        self.assertIn("not valid xml", detail)

    def test_valid_rdfxml_is_reported_as_such(self):
        self.assertIn("valid xml", detail_of(self.write("onto.owl", RDFXML)))

    def test_a_non_rdf_serialization_says_so(self):
        # OBO is not RDF; rdflib has nothing to say about it either way.
        detail = detail_of(
            self.write("onto.obo", "format-version: 1.2\n\n[Term]\nid: X:1\n"))
        self.assertIn("not an RDF serialization", detail)

    def test_a_large_source_is_not_checked(self):
        path = self.write("onto.ttl", GOOD_TURTLE)
        detail = detail_of(path, max_mb=0.000001)
        self.assertIn("not syntax-checked", detail)

    def test_the_default_ceiling_is_finite(self):
        self.assertGreater(MAX_SYNTAX_CHECK_MB, 0)

    def test_a_missing_file_says_nothing(self):
        self.assertEqual(detail_of(os.path.join(self._tmp.name, "nope.ttl")), "")


class TransformTestCase(TestCase):
    """Drives transform() with ROBOT and KGX faked."""

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

    def source(self, name, text):
        path = os.path.join(self.input_dir, "ONTO", "1", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_transform(self, source_path, convert_error=LOAD_FAILURE, all_at_once=False):
        def fake_convert(**kwargs):
            if convert_error:
                return RobotResult(False, convert_error)
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        def fake_relax(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        fh.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", fake_convert), \
             mock.patch("kg_bioportal.transformer.robot_relax", fake_relax), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            if all_at_once:
                self.txr.transform_all(compress=False)
                return None
            return self.txr.transform(source_path, compress=False)

    def stats(self):
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            entries = {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}
        return entries["ONTO"]


class TestUnusableSourcesAreRecordedApart(TransformTestCase):
    def test_the_reason_is_invalid_source(self):
        outcome = self.run_transform(self.source("onto.ttl", BAD_TURTLE))
        self.assertEqual(outcome.reason, INVALID_SOURCE_REASON)

    def test_the_stage_is_still_recorded(self):
        # Where it failed is still true and still useful; it is the reason that
        # needed to stop saying "the transform went wrong".
        outcome = self.run_transform(self.source("onto.ttl", BAD_TURTLE))
        self.assertEqual(outcome.stage, "convert")

    def test_robots_own_message_survives(self):
        outcome = self.run_transform(self.source("onto.ttl", BAD_TURTLE))
        self.assertIn("INVALID ONTOLOGY FILE ERROR", outcome.detail)

    def test_the_diagnosis_is_appended(self):
        outcome = self.run_transform(self.source("onto.ttl", BAD_TURTLE))
        self.assertIn("not valid turtle", outcome.detail)

    def test_a_valid_rdf_source_is_described_as_such(self):
        outcome = self.run_transform(self.source("onto.ttl", GOOD_TURTLE))
        self.assertEqual(outcome.reason, INVALID_SOURCE_REASON)
        self.assertIn("will not load as an ontology", outcome.detail)

    def test_it_reaches_onto_stats(self):
        self.source("onto.ttl", BAD_TURTLE)
        self.run_transform(None, all_at_once=True)
        entry = self.stats()
        self.assertEqual(entry["status"], "Failed")
        self.assertEqual(entry["reason"], INVALID_SOURCE_REASON)
        self.assertIn("not valid turtle", entry["detail"])


class TestEverythingElseKeepsItsReason(TransformTestCase):
    """Only a source ROBOT could not read gets the new reason."""

    def test_an_unresolvable_import_stays_a_transform_error(self):
        self.source("onto.ttl", GOOD_TURTLE)
        self.run_transform(None, convert_error=IMPORT_ERROR, all_at_once=True)
        self.assertEqual(self.stats()["reason"], "transform_error_convert")

    def test_a_write_failure_stays_a_transform_error(self):
        # It falls back to Turtle first (#139); failing both ways is still ours.
        self.source("onto.ttl", GOOD_TURTLE)
        self.run_transform(None, convert_error=STORAGE_ERROR, all_at_once=True)
        self.assertEqual(self.stats()["reason"], "transform_error_convert")

    def test_a_working_ontology_is_untouched(self):
        self.source("onto.ttl", GOOD_TURTLE)
        self.run_transform(None, convert_error="", all_at_once=True)
        entry = self.stats()
        self.assertEqual(entry["status"], "OK")
        self.assertEqual(entry["reason"], "")


# A source with an import, of the shape strip_imports rewrites. What matters
# for the tests below is only that the two files differ.
TURTLE_WITH_IMPORT = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/onto> a owl:Ontology ;
    owl:imports <http://dead.example/gone.owl> ;
    rdfs:label "Onto" .
<http://example.org/ns#A> a owl:Class ; rdfs:label "A" .
"""


class TestWhoBrokeIt(DiagnoseTestCase):
    """invalid_source is a claim about BioPortal's file, so check BioPortal's file.

    strip_imports rewrites most sources before ROBOT sees them, so the file
    named in "Could not load a valid ontology from file: X" is often one we
    wrote. Recording that as invalid_source blames the ontology's maintainers
    for our own bug, and buries a stripper that corrupts files inside a bucket
    labelled "nothing we can do".

    SHEDDING-HUB in the 2026-08-25 run is the case: it failed with
    "shedding-hub_noimports.ttl", the _noimports copy, and the recorded
    diagnosis described that copy while calling it the source -- so the run
    could not say whether the syntax error was upstream's or ours.
    """

    def attribute(self, source_text, stripped_text=None, **kw):
        source = self.write("onto.ttl", source_text)
        robot_input = source
        if stripped_text is not None:
            robot_input = self.write("onto_noimports.ttl", stripped_text)
        return diagnose_load_failure(source, robot_input, **kw)

    def test_an_unstripped_source_is_judged_on_itself(self):
        reason, detail = self.attribute(BAD_TURTLE)
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("not valid turtle", detail)

    def test_a_broken_source_stays_the_source_even_when_stripped(self):
        # The stripped copy of a broken file is broken too; the source is still
        # the thing to report.
        reason, detail = self.attribute(BAD_TURTLE, stripped_text=BAD_TURTLE)
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("source is not valid turtle", detail)

    def test_a_good_source_and_a_broken_copy_is_ours(self):
        # The case the run could not distinguish.
        reason, detail = self.attribute(TURTLE_WITH_IMPORT, stripped_text=BAD_TURTLE)
        self.assertNotEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("not valid turtle", detail)

    def test_our_own_file_is_not_called_the_source(self):
        # The whole point: the phrase must not pin our corruption on upstream.
        _, detail = self.attribute(TURTLE_WITH_IMPORT, stripped_text=BAD_TURTLE)
        self.assertNotIn("source is not valid", detail)
        self.assertIn("import-stripped copy", detail)

    def test_the_detail_says_the_source_was_fine(self):
        # Without this the reader cannot tell a stripper bug from a source that
        # happened to fail after stripping.
        _, detail = self.attribute(TURTLE_WITH_IMPORT, stripped_text=BAD_TURTLE)
        self.assertIn("source that parses cleanly", detail)

    def test_a_good_source_and_a_good_copy_is_still_the_source(self):
        # Both parse, so ROBOT is refusing valid RDF as an ontology -- #142's
        # second kind of unusable, and not ours.
        reason, detail = self.attribute(TURTLE_WITH_IMPORT, stripped_text=GOOD_TURTLE)
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("will not load as an ontology", detail)

    def test_an_unknowable_source_is_not_blamed_on_us(self):
        # Too large to check: we have no evidence either way, and inventing a
        # stripper bug is as wrong as inventing an upstream one.
        reason, detail = self.attribute(
            TURTLE_WITH_IMPORT, stripped_text=BAD_TURTLE, max_mb=0.000001)
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("not syntax-checked", detail)

    def test_a_non_rdf_source_is_not_blamed_on_us_either(self):
        reason, detail = self.attribute(
            "format-version: 1.2\n\n[Term]\nid: X:1\n", stripped_text=BAD_TURTLE)
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertIn("not an RDF serialization", detail)

    def test_a_missing_source_says_nothing_and_blames_nobody(self):
        reason, detail = diagnose_load_failure(
            os.path.join(self._tmp.name, "nope.ttl"),
            self.write("onto_noimports.ttl", BAD_TURTLE),
        )
        self.assertEqual(reason, INVALID_SOURCE_REASON)
        self.assertEqual(detail, "")


class TestTheDiagnosisReportsWhatItKnows(DiagnoseTestCase):
    """parsed is three-valued, and None must not read as either answer."""

    def test_a_parsable_file_is_true(self):
        self.assertIs(diagnose_source(self.write("onto.ttl", GOOD_TURTLE)).parsed, True)

    def test_an_unparsable_file_is_false(self):
        self.assertIs(diagnose_source(self.write("onto.ttl", BAD_TURTLE)).parsed, False)

    def test_html_is_false_not_unknown(self):
        self.assertIs(diagnose_source(self.write("onto.ttl", HTML_PAGE)).parsed, False)

    def test_an_unchecked_file_is_unknown(self):
        self.assertIsNone(
            diagnose_source(self.write("onto.ttl", GOOD_TURTLE), max_mb=1e-6).parsed)

    def test_a_non_rdf_file_is_unknown(self):
        self.assertIsNone(diagnose_source(self.write("onto.obo", "[Term]\n")).parsed)

    def test_a_missing_file_is_unknown(self):
        self.assertIsNone(
            diagnose_source(os.path.join(self._tmp.name, "nope.ttl")).parsed)


class TestAStripperBugReachesTheStats(TransformTestCase):
    """End to end: a file we corrupted is recorded as ours, and says why."""

    def run_with_stripper_output(self, source_text, stripped_text):
        source = self.source("onto.ttl", source_text)
        # Outside input_dir, so transform_all does not pick it up as an ontology.
        stripped = os.path.join(self._tmp.name, "onto_noimports.ttl")
        with open(stripped, "w", encoding="utf-8") as f:
            f.write(stripped_text)
        with mock.patch(
            "kg_bioportal.transformer.strip_imports",
            lambda p: stripped if p == source else p,
        ):
            self.run_transform(None, all_at_once=True)
        return self.stats()

    def test_a_corrupted_copy_is_recorded_as_a_transform_error(self):
        entry = self.run_with_stripper_output(TURTLE_WITH_IMPORT, BAD_TURTLE)
        self.assertEqual(entry["reason"], "transform_error_convert")

    def test_it_is_not_recorded_as_an_unusable_source(self):
        entry = self.run_with_stripper_output(TURTLE_WITH_IMPORT, BAD_TURTLE)
        self.assertNotEqual(entry["reason"], INVALID_SOURCE_REASON)

    def test_the_stats_say_which_file_was_broken(self):
        entry = self.run_with_stripper_output(TURTLE_WITH_IMPORT, BAD_TURTLE)
        self.assertIn("import-stripped copy", entry["detail"])
        self.assertIn("source that parses cleanly", entry["detail"])

    def test_robots_own_message_is_still_kept(self):
        entry = self.run_with_stripper_output(TURTLE_WITH_IMPORT, BAD_TURTLE)
        self.assertIn("INVALID ONTOLOGY FILE ERROR", entry["detail"])

    def test_a_genuinely_broken_source_is_still_invalid_source(self):
        # The stripper ran here too; what decides is that the source is broken.
        entry = self.run_with_stripper_output(BAD_TURTLE, BAD_TURTLE)
        self.assertEqual(entry["reason"], INVALID_SOURCE_REASON)
