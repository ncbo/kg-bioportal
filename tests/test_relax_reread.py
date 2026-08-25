"""ROBOT would not read back the RDF/XML ROBOT had just written.

Five ontologies in the 2026-08-25 run failed at relax with

    INVALID ONTOLOGY FILE ERROR Could not load a valid ontology from file:
    ELD.owl

and ELD.owl is convert's own output. The cause, from ROBOT 1.9.6:

    [line=26:column=46] IRI 'http://ex.org/a%b' cannot be resolved against
    current base IRI http://ex.org/o reason is: Malformed escape pair at index 15

The RDF/XML parser resolves every IRI against the base with java.net.URI, which
is stricter than the Turtle parser that read the source a step earlier. An IRI
carrying a stray '%', a quote, a '<' or a second '#' therefore loads from the
source and fails on the way back in. Nothing is wrong with the ontology.

Turtle round-trips all four with the IRIs intact, so the intermediate falls back
to it -- converting again from the source, since ROBOT cannot read the RDF/XML
it produced and so has nothing to convert it *from*.

The error strings here are ROBOT 1.9.6's own, from convert/relax over an
ontology whose only oddity is the IRI in the message.
"""

import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal.robot_utils import RobotResult, _error_text
from kg_bioportal.transformer import FALLBACK_SERIALIZATION, Transformer

# What relax says about an RDF/XML file its own convert wrote, before and after
# the cause line is kept alongside the headline.
BARE_LOAD_ERROR = (
    "java.lang.IllegalArgumentException: java.io.IOException: errors#INVALID "
    "ONTOLOGY FILE ERROR Could not load a valid ontology from file: ELD.owl"
)
IRI_CAUSE = (
    "org.semanticweb.owlapi.rdf.rdfxml.parser.RDFParserException: "
    "[line=26:column=46] IRI 'http://ex.org/a%b' cannot be resolved against "
    "current base IRI http://ex.org/o reason is: Malformed escape pair at index 15"
)
LOAD_ERROR = f"{BARE_LOAD_ERROR} | {IRI_CAUSE}"
STORAGE_ERROR = (
    "java.io.IOException: errors#ONTOLOGY STORAGE ERROR Could not save ontology to IRI"
)
IMPORT_ERROR = (
    "java.lang.IllegalArgumentException: org.semanticweb.owlapi.model."
    "UnloadableImportException: Could not load imported ontology: <http://dead/>"
)

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
</rdf:RDF>
"""


class RereadTestCase(TestCase):
    """Drives transform() with a ROBOT that fails on what it is *given*.

    The distinguishing fact here is the input's serialization, not the output's:
    relax refuses the .owl and accepts the .ttl.
    """

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

        self.converted = []   # output extensions convert was asked for
        self.convert_inputs = []  # the files convert was actually handed
        self.relaxed = []     # (input ext, output ext) pairs relax was asked for
        self.kgx_input = None

    def run_transform(
        self,
        relax_rejects=(".owl",),
        error=LOAD_ERROR,
        convert_fails_on=(),
        convert_error=STORAGE_ERROR,
    ):
        def fake_convert(**kw):
            out = kw["output_path"]
            self.converted.append(os.path.splitext(out)[1])
            self.convert_inputs.append(kw["input_path"])
            if os.path.splitext(out)[1] in convert_fails_on:
                return RobotResult(False, convert_error)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        def fake_relax(**kw):
            in_ext = os.path.splitext(kw["input_path"])[1]
            out = kw["output_path"]
            self.relaxed.append((in_ext, os.path.splitext(out)[1]))
            if in_ext in relax_rejects:
                return RobotResult(False, error)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        test = self

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                test.kgx_input = input_args["filename"][0]
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        fh.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", fake_convert), \
             mock.patch("kg_bioportal.transformer.robot_relax", fake_relax), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            return self.txr.transform(self.source, compress=False)


class TestTheOntologyGetsThrough(RereadTestCase):
    def test_it_succeeds(self):
        self.assertTrue(self.run_transform().success)

    def test_the_source_is_converted_again_to_turtle(self):
        self.run_transform()
        self.assertEqual(self.converted, [".owl", FALLBACK_SERIALIZATION])

    def test_relax_is_retried_on_the_turtle(self):
        self.run_transform()
        self.assertEqual(
            self.relaxed,
            [(".owl", ".owl"), (FALLBACK_SERIALIZATION, FALLBACK_SERIALIZATION)],
        )

    def test_the_relaxed_output_keeps_the_fallback_format(self):
        # Writing it back to RDF/XML would walk into the same wall.
        self.run_transform()
        _, out_ext = self.relaxed[-1]
        self.assertEqual(out_ext, FALLBACK_SERIALIZATION)

    def test_kgx_reads_the_turtle(self):
        self.run_transform()
        self.assertTrue(self.kgx_input.endswith(FALLBACK_SERIALIZATION))


class TestNothingElseTakesThisPath(RereadTestCase):
    """The retry costs a whole second conversion; only this failure earns it."""

    def test_an_ontology_that_works_converts_once(self):
        self.run_transform(relax_rejects=())
        self.assertEqual(self.converted, [".owl"])
        self.assertEqual(self.relaxed, [(".owl", ".owl")])

    def test_a_write_failure_keeps_its_own_fallback(self):
        # #139's path: relax loaded the file and could not save it. Retrying the
        # conversion would not help, and it already has a retry of its own.
        self.run_transform(relax_rejects=(".owl",), error=STORAGE_ERROR)
        self.assertEqual(self.converted, [".owl"])

    def test_an_unresolvable_import_is_not_retried(self):
        outcome = self.run_transform(relax_rejects=(".owl",), error=IMPORT_ERROR)
        self.assertFalse(outcome.success)
        self.assertEqual(self.converted, [".owl"])

    def test_a_turtle_intermediate_is_not_converted_a_third_time(self):
        # Already Turtle and still unreadable: there is nowhere left to fall back
        # to, and retrying forever is worse than failing.
        outcome = self.run_transform(relax_rejects=(".owl", FALLBACK_SERIALIZATION))
        self.assertFalse(outcome.success)
        self.assertEqual(self.converted, [".owl", FALLBACK_SERIALIZATION])
        self.assertEqual(len(self.relaxed), 2)


class TestWhenTheFallbackAlsoFails(RereadTestCase):
    def test_a_failed_reconversion_still_reports_the_relax_failure(self):
        outcome = self.run_transform(convert_fails_on=(FALLBACK_SERIALIZATION,))
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.stage, "relax")

    def test_the_original_error_survives(self):
        # The reconversion failing is not the story; what relax said is.
        outcome = self.run_transform(convert_fails_on=(FALLBACK_SERIALIZATION,))
        self.assertIn("Could not load a valid ontology", outcome.detail)

    def test_the_reason_is_still_a_relax_error(self):
        outcome = self.run_transform(relax_rejects=(".owl", FALLBACK_SERIALIZATION))
        self.assertEqual(outcome.stage, "relax")


class FakeFailure(Exception):
    def __init__(self, stderr):
        super().__init__("robot failed")
        self.stderr = stderr.encode()


class TestTheReasonIsKept(TestCase):
    """"Could not load a valid ontology" is true of every unreadable file.

    It named the problem for none of the five, which is why they sat unexplained
    for a run. The line that identifies them is further down, under
    UnparsableOntologyException, where each parser reports where it gave up.
    """

    STDERR = "\n".join([
        "Picked up JAVA_TOOL_OPTIONS: -Dfoo",
        BARE_LOAD_ERROR,
        "\tat org.obolibrary.robot.IOHelper.loadOntology(IOHelper.java:596)",
        "Caused by: java.io.IOException: errors#INVALID ONTOLOGY FILE ERROR "
        "Could not load a valid ontology from file: ELD.owl",
        "Caused by: org.semanticweb.owlapi.io.UnparsableOntologyException: "
        "Problem parsing file:/data/ELD.owl",
        # ROBOT glues the first stack element onto the message line itself,
        # after a run of spaces -- so it is not filtered out by the "at " rule.
        IRI_CAUSE + "        org.semanticweb.owlapi.rdf.rdfxml.parser."
        "RDFXMLParser.parse(RDFXMLParser.java:74)",
        "\tat org.semanticweb.owlapi.rdf.rdfxml.parser.RDFParser.resolveIRI(RDFParser.java:355)",
    ])

    def error(self, stderr=None):
        return _error_text(FakeFailure(self.STDERR if stderr is None else stderr))

    def test_the_headline_is_still_there(self):
        self.assertIn("Could not load a valid ontology", self.error())

    def test_the_reason_is_appended(self):
        self.assertIn("Malformed escape pair", self.error())

    def test_the_offending_iri_is_named(self):
        self.assertIn("http://ex.org/a%b", self.error())

    def test_the_position_is_kept(self):
        self.assertIn("[line=26:column=46]", self.error())

    def test_stack_frames_are_not(self):
        # Including the one ROBOT glues onto the end of the message line, which
        # is longer than the message and would eat the detail budget.
        self.assertNotIn("RDFXMLParser.java:74", self.error())
        self.assertNotIn("IOHelper.java:596", self.error())

    def test_the_reason_ends_at_the_reason(self):
        self.assertTrue(self.error().rstrip().endswith("Malformed escape pair at index 15"))

    def test_jvm_noise_is_not(self):
        self.assertNotIn("JAVA_TOOL_OPTIONS", self.error())

    def test_an_error_that_explains_itself_is_left_alone(self):
        # UnloadableImportException names the dead URL on the headline; there is
        # no position below it and nothing to append.
        stderr = "\n".join([IMPORT_ERROR, "\tat org.obolibrary.robot.Foo.bar(Foo.java:1)"])
        self.assertEqual(self.error(stderr), IMPORT_ERROR)

    def test_only_the_first_reason_is_taken(self):
        # The OWL API tries every parser and each complains in its own syntax;
        # the rest say nothing new about the ontology.
        second = ("org.semanticweb.owlapi.rdf.turtle.parser.ParseException: "
                  "Encountered \"\" at line 1, column 1.")
        text = self.error(self.STDERR + "\n" + second)
        self.assertNotIn("turtle.parser.ParseException", text)

    def test_a_stderr_with_no_position_still_reports_something(self):
        self.assertEqual(self.error(BARE_LOAD_ERROR), BARE_LOAD_ERROR)


# An xml:lang an XML attribute takes and a Turtle language tag cannot express.
# Real: DRMO ships an email address in one (#140).
BAD_TAG = "editor@example.com"
RDFXML_WITH_BAD_TAG = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
  <owl:Class rdf:about="http://example.org/ns#A">
    <rdfs:label xml:lang="%s">A</rdfs:label>
  </owl:Class>
</rdf:RDF>
""" % BAD_TAG


class TestTheFallbackCannotCarryABadLanguageTag(RereadTestCase):
    """Falling back to Turtle must not trade one failure for another.

    An XML attribute takes any string, but a Turtle language tag is part of the
    grammar. Handed an ontology with xml:lang="editor@example.com", ROBOT writes
    `"A"@editor@example.com` into Turtle -- checked against ROBOT 1.9.6 -- which
    is not Turtle at all, and rdflib rejects the file at the KGX step. Cleaning
    the source on the way in means no serialization ROBOT picks can carry it.
    """

    def setUp(self):
        super().setUp()
        with open(self.source, "w") as f:
            f.write(RDFXML_WITH_BAD_TAG)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_convert_never_sees_the_bad_tag(self):
        self.run_transform(relax_rejects=())
        for path in self.convert_inputs:
            self.assertNotIn(BAD_TAG, self.read(path), path)

    def test_it_is_gone_on_the_fallback_conversion_too(self):
        # The path that would have written it into Turtle.
        self.run_transform()
        self.assertEqual(len(self.convert_inputs), 2)
        self.assertNotIn(BAD_TAG, self.read(self.convert_inputs[-1]))

    def test_the_literal_itself_is_kept(self):
        # The tag is dropped, not the label: there is nothing wrong with "A".
        self.run_transform(relax_rejects=())
        self.assertIn(">A<", self.read(self.convert_inputs[0]))

    def test_the_ontology_still_transforms(self):
        self.assertTrue(self.run_transform().success)

    def test_a_source_with_no_language_tags_is_not_rewritten(self):
        # The ontologies that build today must be handed the file they are now.
        with open(self.source, "w") as f:
            f.write(RDFXML)
        self.run_transform(relax_rejects=())
        self.assertEqual(self.convert_inputs[0], self.source)
