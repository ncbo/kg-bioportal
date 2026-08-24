"""ROBOT must not hand the next step a file no XML parser can read.

`robot convert` exits 0, prints "Complete.", and `robot relax` then cannot load
the file it just wrote (#141). The cause is a character XML forbids: legal in
the source, where Turtle spells it as an escape (\\u0001), and raw in the RDF/XML
ROBOT writes back out. Verified against ROBOT 1.9.6 -- convert exit 0, a 964-byte
output holding `<rdfs:label>bad\\x01char</rdfs:label>`, relax exit 1 with
"INVALID ONTOLOGY FILE ERROR Could not load a valid ontology from file".

These tests cover the sanitizer that runs over ROBOT's output, and the
post-condition that stops a command claiming success over an unusable file.
"""

import os
import shutil
import tempfile
from unittest import TestCase, mock
from xml.etree import ElementTree

from kg_bioportal.robot_utils import RobotResult, _output_written, robot_convert
from kg_bioportal.transformer import Transformer, strip_xml_illegal_chars

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
  <owl:Class rdf:about="http://example.org/ns#A">
    <rdfs:label>{label}</rdfs:label>
  </owl:Class>
</rdf:RDF>
"""


class StripIllegalCharsTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def clean(self, label, name="ONTO.owl"):
        """Sanitize a document carrying `label`, and return (path, text)."""
        path = self.write(name, RDFXML.format(label=label))
        out = strip_xml_illegal_chars(path, "ONTO")
        with open(out, encoding="utf-8") as f:
            return out, f.read()

    def assert_parses(self, text):
        """The whole point: an XML parser must be able to read it back."""
        try:
            ElementTree.fromstring(text)
        except ElementTree.ParseError as e:
            self.fail(f"cleaned document still does not parse: {e}")


class TestIllegalCharactersAreRemoved(StripIllegalCharsTestCase):
    def test_the_document_does_not_parse_before_the_fix(self):
        # Establishes that the fixture reproduces the problem, so the tests
        # below are not asserting against an already-valid document.
        with self.assertRaises(ElementTree.ParseError):
            ElementTree.fromstring(RDFXML.format(label="bad\x01char"))

    def test_a_control_character_is_removed(self):
        out, text = self.clean("bad\x01char")
        self.assertNotEqual(out, os.path.join(self._tmp.name, "ONTO.owl"))
        self.assertNotIn("\x01", text)
        self.assert_parses(text)

    def test_the_rest_of_the_label_survives(self):
        _, text = self.clean("bad\x01char")
        self.assertIn("badchar", text)

    def test_a_form_feed_becomes_a_space(self):
        # A form feed sits between words -- dropping it would join them.
        _, text = self.clean("page\x0cbreak")
        self.assertIn("page break", text)
        self.assert_parses(text)

    def test_a_vertical_tab_becomes_a_space(self):
        _, text = self.clean("line\x0bbreak")
        self.assertIn("line break", text)

    def test_every_occurrence_goes_not_just_the_first(self):
        _, text = self.clean("a\x01b\x02c\x1fd")
        self.assertIn("abcd", text)
        self.assert_parses(text)

    def test_the_whole_forbidden_range_is_covered(self):
        forbidden = (
            [chr(c) for c in range(0x00, 0x09)]
            + ["\x0b", "\x0c"]
            + [chr(c) for c in range(0x0e, 0x20)]
            + ["￾", "￿"]
        )
        for char in forbidden:
            with self.subTest(char=f"U+{ord(char):04X}"):
                _, text = self.clean(f"a{char}b", name=f"O{ord(char)}.owl")
                self.assertNotIn(char, text)
                self.assert_parses(text)

    def test_the_ontology_is_otherwise_untouched(self):
        _, text = self.clean("bad\x01char")
        self.assertIn("http://example.org/onto", text)
        self.assertIn("http://example.org/ns#A", text)

    def test_the_original_file_is_left_alone(self):
        path = self.write("ONTO.owl", RDFXML.format(label="bad\x01char"))
        strip_xml_illegal_chars(path, "ONTO")
        with open(path, encoding="utf-8") as f:
            self.assertIn("\x01", f.read())


class TestWhatIsLeftAlone(StripIllegalCharsTestCase):
    """Characters XML does allow must survive: this runs over every ontology."""

    def test_a_clean_document_is_passed_through_untouched(self):
        path = self.write("ONTO.owl", RDFXML.format(label="a normal label"))
        self.assertEqual(strip_xml_illegal_chars(path, "ONTO"), path)

    def test_tab_newline_and_carriage_return_are_kept(self):
        path = self.write("ONTO.owl", RDFXML.format(label="a\tb\nc\rd"))
        self.assertEqual(strip_xml_illegal_chars(path, "ONTO"), path)

    def test_non_ascii_text_is_kept(self):
        # Ontology labels are full of accents, Greek and CJK.
        path = self.write("ONTO.owl", RDFXML.format(label="Ω café 表現 — naïve"))
        self.assertEqual(strip_xml_illegal_chars(path, "ONTO"), path)

    def test_c1_controls_are_kept(self):
        # XML 1.0 permits these in content; removing them would be a change
        # this fix has no reason to make.
        path = self.write("ONTO.owl", RDFXML.format(label="a\x85b\x9fc"))
        self.assertEqual(strip_xml_illegal_chars(path, "ONTO"), path)

    def test_an_unreadable_path_returns_the_input(self):
        missing = os.path.join(self._tmp.name, "nope.owl")
        self.assertEqual(strip_xml_illegal_chars(missing, "ONTO"), missing)


class TestOutputPostcondition(TestCase):
    """A ROBOT command that exits 0 having written nothing has not succeeded.

    ROBOT reads a zero-byte file as a valid empty ontology (checked against
    1.9.6), so without this the next step accepts the empty intermediate and the
    ontology transforms to a graph with nothing in it, recorded OK.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def path(self, name):
        return os.path.join(self._tmp.name, name)

    def test_a_missing_output_is_a_failure(self):
        problem = _output_written(self.path("ONTO.owl"))
        self.assertIn("no output file", problem)
        self.assertIn("ONTO.owl", problem)

    def test_an_empty_output_is_a_failure(self):
        path = self.path("ONTO.owl")
        open(path, "w").close()
        self.assertIn("empty output file", _output_written(path))

    def test_a_written_output_is_fine(self):
        path = self.path("ONTO.owl")
        with open(path, "w") as f:
            f.write(RDFXML.format(label="A"))
        self.assertEqual(_output_written(path), "")

    def test_the_problem_reads_as_a_robot_failure(self):
        # It travels as the RobotResult error, so it lands in onto_stats as
        # transform_error_convert rather than being blamed on the next step.
        result = RobotResult(False, _output_written(self.path("ONTO.owl")))
        self.assertFalse(result)
        self.assertIn("ROBOT exited cleanly", result.error)


class TestRelaxIsHandedACleanFile(TestCase):
    """The pipeline has to sanitize between the two ROBOT steps, not after.

    `relax` is the step that fails, so cleaning up afterwards would be too late.
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
            f.write(RDFXML.format(label="A"))

        self.relax_saw = {}

    def run_transform(self, convert_writes):
        """Drive transform() with ROBOT faked; convert writes `convert_writes`."""
        def fake_convert(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w", encoding="utf-8") as f:
                f.write(convert_writes)
            return RobotResult(True)

        def fake_relax(**kwargs):
            with open(kwargs["input_path"], encoding="utf-8") as f:
                self.relax_saw["path"] = kwargs["input_path"]
                self.relax_saw["text"] = f.read()
            with open(kwargs["output_path"], "w", encoding="utf-8") as f:
                f.write(RDFXML.format(label="A"))
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
            return self.txr.transform(self.source, compress=False)

    def test_relax_never_sees_the_illegal_character(self):
        self.run_transform(RDFXML.format(label="bad\x01char"))
        self.assertNotIn("\x01", self.relax_saw["text"])
        ElementTree.fromstring(self.relax_saw["text"])  # must parse

    def test_relax_is_given_the_cleaned_file(self):
        self.run_transform(RDFXML.format(label="bad\x01char"))
        self.assertTrue(self.relax_saw["path"].endswith("_xmlsafe.owl"),
                        self.relax_saw["path"])

    def test_a_clean_convert_output_is_passed_through_untouched(self):
        # The common case: no rewrite, so this cannot perturb what builds today.
        self.run_transform(RDFXML.format(label="A"))
        self.assertTrue(self.relax_saw["path"].endswith("ONTO.owl"),
                        self.relax_saw["path"])

    def test_the_transform_succeeds(self):
        self.assertTrue(self.run_transform(RDFXML.format(label="bad\x01char")).success)

    def test_the_cleaned_intermediate_is_cleaned_up(self):
        self.run_transform(RDFXML.format(label="bad\x01char"))
        workdir = os.path.join(self.output_dir, "ONTO", "1")
        leftovers = [f for f in os.listdir(workdir) if f.endswith(".owl")]
        self.assertEqual(leftovers, [], f"OWL intermediates left behind: {leftovers}")


class TestRobotCommandsCheckTheirOutput(TestCase):
    """Wiring check: the post-condition is actually applied by the commands.

    /bin/true stands in for a ROBOT that exits 0 and writes nothing -- which is
    the whole failure mode, and needs no ROBOT to reproduce.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.true = shutil.which("true")
        if not self.true:
            self.skipTest("no `true` binary to stand in for ROBOT")

    def test_convert_that_writes_nothing_reports_failure(self):
        result = robot_convert(
            robot_path=self.true,
            input_path=os.path.join(self._tmp.name, "in.owl"),
            output_path=os.path.join(self._tmp.name, "out.owl"),
            robot_env={},
        )
        self.assertFalse(result, "a command that wrote no file claimed success")
        self.assertIn("no output file", result.error)
