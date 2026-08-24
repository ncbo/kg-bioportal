"""Some ontologies cannot be written as RDF/XML at all.

ROBOT loads them fine and then cannot save them:

    java.io.IOException: errors#ONTOLOGY STORAGE ERROR Could not save ontology
    to IRI: file:/…/PHENX.owl

RDF/XML cannot express an IRI whose local part is not a legal XML element name,
and there is no escaping around it -- rdflib refuses the same graph with "no
valid way to shorten". Turtle can write any IRI, and stays RDF all the way to
the KGX step, so the intermediate falls back to it (#139).

Checked against ROBOT 1.9.6, converting an ontology with the property IRI
<http://example.org/prop/1>: to .owl exits 1 having written 0 bytes; to .ttl
exits 0; and relax reads that Turtle and writes Turtle happily, while relax
from Turtle to .owl hits the same wall again -- which is why the relaxed output
keeps the fallback format rather than going back to RDF/XML.
"""

import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal import kgx_patches
from kg_bioportal.robot_utils import RobotResult
from kg_bioportal.transformer import (
    FALLBACK_SERIALIZATION,
    Transformer,
    is_serialization_failure,
)

# Verbatim from the issue, and from ROBOT 1.9.6 respectively.
STORAGE_ERROR = (
    "java.io.IOException: errors#ONTOLOGY STORAGE ERROR Could not save ontology "
    "to IRI: file:/home/runner/work/kg-bioportal/data/transformed/PHENX/16/PHENX.owl"
)
ELEMENT_ERROR = (
    'java.io.IOException: errors#INVALID ELEMENT ERROR "http://example.org/prop/1" '
    "contains invalid characters"
)
LOAD_ERROR = (
    "java.lang.IllegalArgumentException: org.semanticweb.owlapi.model."
    "UnloadableImportException: Could not load imported ontology: <http://dead/>"
)

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
</rdf:RDF>
"""


class TestFailureClassification(TestCase):
    """Only a write-side failure earns a retry; everything else fails as before."""

    def test_storage_error_is_a_serialization_failure(self):
        self.assertTrue(is_serialization_failure(STORAGE_ERROR))

    def test_invalid_element_error_is_a_serialization_failure(self):
        # ROBOT reports the same underlying problem this way when it can name
        # the offending IRI.
        self.assertTrue(is_serialization_failure(ELEMENT_ERROR))

    def test_owlapi_storage_exception_is_a_serialization_failure(self):
        self.assertTrue(is_serialization_failure(
            "org.semanticweb.owlapi.model.OWLOntologyStorageException: nope"))

    def test_a_load_failure_is_not(self):
        # An unresolvable import is the source's problem; another format would
        # fail identically, and retrying would just cost another ROBOT run.
        self.assertFalse(is_serialization_failure(LOAD_ERROR))

    def test_a_timeout_is_not(self):
        self.assertFalse(is_serialization_failure("ROBOT convert timed out after 60s"))

    def test_an_empty_error_is_not(self):
        self.assertFalse(is_serialization_failure(""))


class FallbackTestCase(TestCase):
    """Drives transform() with ROBOT and KGX faked, recording what was asked for."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "transformed")

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

        self.convert_outputs = []
        self.relax_outputs = []
        self.kgx_input = None

    def run_transform(self, convert_fails_on=(), relax_fails_on=(), error=STORAGE_ERROR):
        """Run one ontology through; the named extensions fail to be written.

        `convert_fails_on=(".owl",)` models an ontology RDF/XML cannot express.
        """
        def writer(record, failing):
            def run(**kwargs):
                out = kwargs["output_path"]
                record.append(out)
                if os.path.splitext(out)[1] in failing:
                    return RobotResult(False, error)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w") as f:
                    f.write(RDFXML)
                return RobotResult(True)
            return run

        test = self

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                test.kgx_input = input_args["filename"][0]
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        fh.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert",
                        writer(self.convert_outputs, convert_fails_on)), \
             mock.patch("kg_bioportal.transformer.robot_relax",
                        writer(self.relax_outputs, relax_fails_on)), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            return self.txr.transform(self.source, compress=False)

    def exts(self, paths):
        return [os.path.splitext(p)[1] for p in paths]


class TestNothingChangesForOntologiesThatWork(FallbackTestCase):
    """1108 ontologies transform today; none of them may take a different path."""

    def test_convert_is_asked_for_rdfxml_first(self):
        self.run_transform()
        self.assertEqual(self.exts(self.convert_outputs), [".owl"])

    def test_a_working_ontology_never_retries(self):
        outcome = self.run_transform()
        self.assertTrue(outcome.success)
        self.assertEqual(len(self.convert_outputs), 1)
        self.assertEqual(len(self.relax_outputs), 1)

    def test_the_relaxed_output_stays_rdfxml(self):
        self.run_transform()
        self.assertEqual(self.exts(self.relax_outputs), [".owl"])

    def test_kgx_is_still_handed_rdfxml(self):
        self.run_transform()
        self.assertTrue(self.kgx_input.endswith(".owl"), self.kgx_input)

    def test_a_load_failure_still_fails_without_a_retry(self):
        outcome = self.run_transform(convert_fails_on=(".owl",), error=LOAD_ERROR)
        self.assertEqual(outcome.stage, "convert")
        self.assertEqual(len(self.convert_outputs), 1, "should not have retried")
        self.assertIn("UnloadableImportException", outcome.detail)


class TestFallbackWhenRdfXmlCannotHoldIt(FallbackTestCase):
    def test_convert_retries_as_turtle(self):
        self.run_transform(convert_fails_on=(".owl",))
        self.assertEqual(self.exts(self.convert_outputs), [".owl", FALLBACK_SERIALIZATION])

    def test_the_relaxed_output_keeps_the_fallback_format(self):
        # Going back to RDF/XML here would hit the same wall one step later.
        self.run_transform(convert_fails_on=(".owl",))
        self.assertEqual(self.exts(self.relax_outputs), [FALLBACK_SERIALIZATION])

    def test_kgx_is_handed_the_turtle(self):
        self.run_transform(convert_fails_on=(".owl",))
        self.assertTrue(self.kgx_input.endswith(FALLBACK_SERIALIZATION), self.kgx_input)

    def test_the_transform_succeeds(self):
        self.assertTrue(self.run_transform(convert_fails_on=(".owl",)).success)

    def test_relax_falls_back_on_its_own_account(self):
        # convert could write RDF/XML; relax could not.
        self.run_transform(relax_fails_on=(".owl",))
        self.assertEqual(self.exts(self.relax_outputs), [".owl", FALLBACK_SERIALIZATION])
        self.assertTrue(self.kgx_input.endswith(FALLBACK_SERIALIZATION), self.kgx_input)

    def test_a_format_neither_can_write_still_fails_as_relax(self):
        outcome = self.run_transform(relax_fails_on=(".owl", FALLBACK_SERIALIZATION))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "relax")

    def test_a_format_convert_cannot_write_at_all_fails_as_convert(self):
        outcome = self.run_transform(convert_fails_on=(".owl", FALLBACK_SERIALIZATION))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "convert")
        self.assertIn("ONTOLOGY STORAGE ERROR", outcome.detail)

    def test_the_intermediates_are_cleaned_up(self):
        self.run_transform(convert_fails_on=(".owl",))
        workdir = os.path.join(self.output_dir, "ONTO", "1")
        leftovers = [f for f in os.listdir(workdir)
                     if f.endswith((".owl", FALLBACK_SERIALIZATION))]
        self.assertEqual(leftovers, [], f"intermediates left behind: {leftovers}")


class TestKgxReadsWhatWeWrote(TestCase):
    """KGX maps its "owl" format straight to "xml", whatever the file is.

    The patch resolves the format from the file name instead. For .owl that is
    the same answer rdflib's guess_format gives -- "xml" -- so nothing that
    parses today parses differently.
    """

    def test_owl_still_resolves_to_xml(self):
        self.assertEqual(kgx_patches.owl_source_format("ONTO_relaxed.owl", "owl"), "xml")

    def test_every_intermediate_name_the_pipeline_writes_resolves_to_xml(self):
        for name in ("ONTO.owl", "ONTO_relaxed.owl", "ONTO_relaxed_noimports.owl",
                     "ONTO_relaxed_langfix.owl", "ONTO_xmlsafe.owl"):
            with self.subTest(name=name):
                self.assertEqual(kgx_patches.owl_source_format(name, "owl"), "xml")

    def test_turtle_resolves_to_turtle(self):
        self.assertEqual(
            kgx_patches.owl_source_format("ONTO_relaxed.ttl", "owl"), "turtle")

    def test_an_unguessable_name_falls_back_to_xml(self):
        # Exactly what KGX does today, so an odd name is no worse off.
        self.assertEqual(kgx_patches.owl_source_format("ONTO", "owl"), "xml")

    def test_an_explicit_format_is_left_alone(self):
        self.assertEqual(kgx_patches.owl_source_format("ONTO.owl", "turtle"), "turtle")

    def test_a_missing_format_is_resolved_too(self):
        self.assertEqual(kgx_patches.owl_source_format("ONTO.ttl", None), "turtle")


class TestOwlSourcePatch(TestCase):
    """The patch has to be applied to KGX itself, and be safe to apply twice."""

    def test_the_patch_reports_it_is_already_in_place(self):
        # transformer applies it at import; a second call is a no-op, not a
        # second layer of wrapping.
        kgx_patches.patch_owl_source_format()
        self.assertFalse(kgx_patches.patch_owl_source_format())

    def parsed_as(self, filename):
        """The rdflib format KGX's OwlSource actually parses `filename` with.

        Recorded at the one call that matters -- rdflib's own parse -- and
        stopped there, so nothing needs the file to exist or KGX to be wired to
        a real Transformer. parse() touches no attribute of self before that
        call, which is why a bare object stands in for the source instance.
        """
        import rdflib

        from kgx.source.owl_source import OwlSource

        seen = {}

        class Stop(Exception):
            pass

        class RecordingGraph:
            def parse(self, source=None, format=None, **kwargs):
                seen["format"] = format
                raise Stop

        kgx_patches.patch_owl_source_format()
        with mock.patch.object(rdflib, "Graph", RecordingGraph):
            with self.assertRaises(Stop):
                result = OwlSource.parse(object(), filename, format="owl")
                if hasattr(result, "__next__"):
                    next(result)  # parse() is a generator in KGX; make it run
        return seen["format"]

    def test_owl_source_parses_turtle_as_turtle(self):
        self.assertEqual(self.parsed_as("ONTO_relaxed.ttl"), "turtle")

    def test_owl_source_still_parses_owl_as_xml(self):
        # The behaviour every ontology that works today depends on.
        self.assertEqual(self.parsed_as("ONTO_relaxed.owl"), "xml")
