"""One ontology's warnings should not bury a whole shard's log.

BDPM types its dates as xsd:dateTime and writes them DD/MM/YYYY, so rdflib
warned once per literal -- 36,710 times, each with exc_info, which is two
formatted tracebacks apiece. That was about 95% of that shard's 515,366 log
lines, and a real ROBOT or KGX error in the same shard was one line among half
a million (#152).

None of it was a failure: rdflib keeps the lexical form and BDPM transformed
fine. So the fix counts rather than silences -- the same fact, said once, and
carried into the stats where it is a data-quality signal about the source
rather than noise.

The rdflib warning these tests exercise is the real one: the fixtures are
parsed by rdflib, not hand-built log records.
"""

import logging
import os
import tempfile
from unittest import TestCase, mock

import rdflib
import yaml

from kg_bioportal.robot_utils import RobotResult
from kg_bioportal.transformer import (
    LiteralConversionTally,
    Transformer,
    abbreviate_datatype,
)

# Dates written the way BDPM writes them, declared as xsd:dateTime.
BAD_LITERALS = """@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ns#> .
ex:a ex:date "06/09/2012"^^xsd:dateTime .
ex:b ex:date "31/12/2024"^^xsd:dateTime .
ex:c ex:count "not-a-number"^^xsd:integer .
ex:d ex:date "2012-06-09T00:00:00"^^xsd:dateTime .
"""

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto"/>
</rdf:RDF>
"""


def parse_with(tally):
    """Parse the fixture with the tally installed, as the transform does."""
    with tally.installed():
        graph = rdflib.Graph()
        graph.parse(data=BAD_LITERALS, format="turtle")
    return graph


class TestTallyCounts(TestCase):
    def setUp(self):
        self.tally = LiteralConversionTally()
        self.graph = parse_with(self.tally)

    def test_every_bad_literal_is_counted(self):
        self.assertEqual(self.tally.count, 3)

    def test_a_well_formed_literal_is_not_counted(self):
        # The fourth triple's date is a valid xsd:dateTime.
        self.assertEqual(len(self.graph), 4)

    def test_the_datatypes_are_broken_down(self):
        self.assertEqual(self.tally.by_datatype,
                         {"xsd:dateTime": 2, "xsd:integer": 1})

    def test_an_example_names_the_offending_value(self):
        # The value is only in the exception, not in rdflib's message, and it
        # is the thing that tells a maintainer what to fix.
        self.assertIn("06/09/2012", self.tally.example)
        self.assertIn("xsd:dateTime", self.tally.example)

    def test_a_clean_graph_counts_nothing(self):
        tally = LiteralConversionTally()
        with tally.installed():
            rdflib.Graph().parse(
                data='<http://example.org/a> <http://example.org/b> "plain" .',
                format="turtle")
        self.assertEqual(tally.count, 0)
        self.assertEqual(tally.summary(), "")


class TestNothingIsPrinted(TestCase):
    """The point of the exercise: the log stops carrying 36,710 tracebacks."""

    def test_the_warnings_do_not_reach_a_handler(self):
        tally = LiteralConversionTally()
        with self.assertLogs("rdflib.term", level="DEBUG") as captured:
            logging.getLogger("rdflib.term").debug("marker")  # so assertLogs has one
            parse_with(tally)
        self.assertEqual(captured.output, ["DEBUG:rdflib.term:marker"])
        self.assertEqual(tally.count, 3)

    def test_the_warnings_come_back_after_the_block(self):
        # The filter is removed again: a later ontology's warnings are not
        # silently swallowed by a tally nobody is reading.
        tally = LiteralConversionTally()
        parse_with(tally)
        with self.assertLogs("rdflib.term", level="WARNING") as captured:
            rdflib.Graph().parse(data=BAD_LITERALS, format="turtle")
        self.assertTrue(captured.output)

    def test_other_warnings_from_the_same_logger_still_print(self):
        # rdflib.term also warns about things like an IRI that will not
        # serialize -- suppressing those would hide a real problem.
        tally = LiteralConversionTally()
        with tally.installed():
            with self.assertLogs("rdflib.term", level="WARNING") as captured:
                logging.getLogger("rdflib.term").warning(
                    "does not look like a valid URI, trying to serialize this will break.")
        self.assertEqual(len(captured.output), 1)
        self.assertEqual(tally.count, 0)

    def test_a_record_that_cannot_be_formatted_is_left_alone(self):
        tally = LiteralConversionTally()
        record = logging.LogRecord(
            "rdflib.term", logging.WARNING, __file__, 1, "%d", ("not an int",), None)
        self.assertTrue(tally.filter(record))


class TestSummary(TestCase):
    def test_the_summary_says_the_count(self):
        tally = LiteralConversionTally()
        parse_with(tally)
        self.assertIn("3 literal", tally.summary())

    def test_the_summary_names_the_datatypes(self):
        tally = LiteralConversionTally()
        parse_with(tally)
        self.assertIn("xsd:dateTime x2", tally.summary())

    def test_the_summary_says_the_values_are_kept(self):
        # It is not a failure and should not read like one.
        tally = LiteralConversionTally()
        parse_with(tally)
        self.assertIn("kept as written", tally.summary())

    def test_the_summary_is_one_line(self):
        tally = LiteralConversionTally()
        parse_with(tally)
        self.assertNotIn("\n", tally.summary())

    def test_many_datatypes_are_truncated(self):
        tally = LiteralConversionTally()
        tally.count = 10
        tally.by_datatype = {f"xsd:t{i}": 1 for i in range(6)}
        self.assertIn("and 3 more", tally.summary())


class TestAbbreviation(TestCase):
    def test_xsd_is_abbreviated(self):
        self.assertEqual(
            abbreviate_datatype("http://www.w3.org/2001/XMLSchema#dateTime"),
            "xsd:dateTime")

    def test_an_unknown_namespace_is_left_whole(self):
        self.assertEqual(abbreviate_datatype("http://example.org/my#type"),
                         "http://example.org/my#type")


class TestItReachesTheStats(TestCase):
    """The count is per-ontology data quality, so it belongs in the index."""

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

    def run_transform(self, warnings=0, kgx_raises=None, all_at_once=False):
        """Run one ontology through; KGX emits `warnings` bad literals."""
        def robot(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                # Emit the real rdflib warning, the real number of times.
                for i in range(warnings):
                    rdflib.Graph().parse(
                        data='@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
                             f'<http://example.org/{i}> <http://example.org/d> '
                             '"06/09/2012"^^xsd:dateTime .',
                        format="turtle")
                if kgx_raises is not None:
                    raise kgx_raises
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        fh.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            if all_at_once:
                self.txr.transform_all(compress=False)
                return None
            return self.txr.transform(self.source, compress=False)

    def stats(self):
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            return {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}["ONTO"]

    def test_the_count_reaches_the_outcome(self):
        outcome = self.run_transform(warnings=5)
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.malformed_literals, 5)

    def test_the_count_reaches_onto_stats(self):
        self.run_transform(warnings=5, all_at_once=True)
        self.assertEqual(self.stats()["malformed_literals"], 5)

    def test_a_clean_ontology_carries_no_field(self):
        # A zero on every one of 1135 OK entries would be noise in the index.
        self.run_transform(warnings=0, all_at_once=True)
        self.assertNotIn("malformed_literals", self.stats())

    def test_the_ontology_still_transforms(self):
        # This is not a failure mode: the graph is fine, the literals are kept.
        self.run_transform(warnings=3, all_at_once=True)
        self.assertEqual(self.stats()["status"], "OK")

    def test_a_kgx_failure_still_reports_what_it_counted(self):
        outcome = self.run_transform(warnings=4, kgx_raises=ValueError("boom"))
        self.assertEqual(outcome.stage, "kgx")
        self.assertEqual(outcome.malformed_literals, 4)

    def test_one_line_is_logged_not_thousands(self):
        with self.assertLogs("root", level="WARNING") as captured:
            self.run_transform(warnings=25)
        summaries = [line for line in captured.output if "lexical form" in line]
        self.assertEqual(len(summaries), 1, captured.output)
        self.assertIn("25 literal", summaries[0])
