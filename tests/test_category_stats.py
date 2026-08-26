"""Biolink category counts for every ontology, in the logs and in the index (#98).

The issue asks for the set of node and edge categories per ontology, propagated
to the stats and shown on the dashboard. Measuring what the pipeline actually
produces first, across 12 graphs sampled from release ``data-2026.08.25-12``:

    nodes   100% biolink:NamedThing, in every one of them -- MONDO's diseases,
            VTO's taxa, GO-PLUS's processes alike
    edges   blank, except where an ontology's axioms are reified

Neither is a tally of anything. ``NamedThing`` is what KGX's RdfSource writes
when nothing has set a category (rdf_source.py:176), which for a plain OWL file
is always; ``biolink:Association`` is set only on the reified path
(owl_source.py:144), so MONDO and VTO are 100% blank while MCBCC, whose axioms
are reified, is mostly ``Association``.

So this change is in two parts:

* the edges get the root ``biolink:Association``, the way the reified ones
  already do -- correct-but-general for any edge, and the same "KGX assigns it
  inconsistently" shape as the missing edge ids in #71;
* the tally is counted, logged, recorded in onto_stats.yaml and rendered.

Making the categories *specific* is a separate problem and not this one: node
prefixes cap out at about 11.5% of nodes (57,096 of 497,959 sampled), because
the big prefixes are genuinely ambiguous in Biolink -- GO spans
``biological process or activity`` and ``anatomical entity``, CHEBI spans the
``named thing`` and ``attribute`` branches.
"""

import os
import tempfile
from unittest import TestCase, mock

import yaml

from kg_bioportal import kgx_patches
from kg_bioportal.kgx_patches import ROOT_ASSOCIATION
from kg_bioportal.robot_utils import RobotResult
from kg_bioportal.transformer import (
    UNCATEGORIZED,
    Transformer,
    format_tally,
    tally_column,
)

# Captured before any test touches the flag. Importing kg_bioportal.transformer
# -- which the imports above just did -- is what puts the patch in place for the
# pipeline; nothing else in this file applies it at module scope. Read here
# rather than asserted in a test body, because the helpers below toggle it.
PATCHED_AT_IMPORT = kgx_patches._edge_category_patched

RDFXML = (
    '<?xml version="1.0"?>\n<rdf:RDF '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
    '<owl:Ontology rdf:about="http://example.org/onto"/>\n'
    '</rdf:RDF>\n'
)


def tsv(tmpdir, name, *rows):
    """Write a TSV whose first row is the header. Returns its path."""
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        for row in rows:
            f.write("\t".join(row) + "\n")
    return path


class TestTheTally(TestCase):
    """What comes out of a KGX TSV, counted in one pass over it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_rows_are_counted_without_the_header(self):
        path = tsv(self.dir, "n.tsv",
                   ["id", "category"], ["A", "biolink:NamedThing"],
                   ["B", "biolink:NamedThing"])
        self.assertEqual(tally_column(path)[0], 2)

    def test_each_category_is_counted(self):
        path = tsv(self.dir, "n.tsv",
                   ["id", "category"], ["A", "biolink:Disease"],
                   ["B", "biolink:Disease"], ["C", "biolink:NamedThing"])
        self.assertEqual(tally_column(path)[1],
                         {"biolink:Disease": 2, "biolink:NamedThing": 1})

    def test_a_multi_valued_cell_counts_under_each_category(self):
        # KGX writes a multi-valued column pipe-delimited, and a node may
        # legitimately be both. "How many nodes are a Disease" is the question
        # being answered, so both get the row.
        path = tsv(self.dir, "n.tsv",
                   ["id", "category"],
                   ["A", "biolink:Disease|biolink:NamedThing"])
        rows, counts = tally_column(path)
        self.assertEqual(rows, 1)
        self.assertEqual(counts,
                         {"biolink:Disease": 1, "biolink:NamedThing": 1})

    def test_an_empty_cell_is_counted_as_uncategorized(self):
        # Not dropped: "how many carry nothing" is the finding this whole
        # change came out of, and a blank key in YAML says it badly.
        path = tsv(self.dir, "e.tsv", ["id", "category"], ["A", ""])
        self.assertEqual(tally_column(path)[1], {UNCATEGORIZED: 1})

    def test_whitespace_only_cells_are_uncategorized_too(self):
        path = tsv(self.dir, "e.tsv", ["id", "category"], ["A", "   "])
        self.assertEqual(tally_column(path)[1], {UNCATEGORIZED: 1})

    def test_the_column_is_found_by_name_not_position(self):
        # Column order is set by NODE_COLUMNS/EDGE_COLUMNS and has changed
        # before; an index baked in here would silently tally the wrong field.
        path = tsv(self.dir, "e.tsv",
                   ["id", "subject", "predicate", "object", "category"],
                   ["e1", "A", "biolink:subclass_of", "B", ROOT_ASSOCIATION])
        self.assertEqual(tally_column(path)[1], {ROOT_ASSOCIATION: 1})

    def test_a_file_without_the_column_still_counts_its_rows(self):
        path = tsv(self.dir, "n.tsv", ["id", "name"], ["A", "a"], ["B", "b"])
        self.assertEqual(tally_column(path), (2, {}))

    def test_a_short_row_does_not_raise(self):
        # A row with fewer cells than the header would be an IndexError.
        path = tsv(self.dir, "n.tsv",
                   ["id", "name", "category"], ["A", "a", "biolink:NamedThing"],
                   ["B"])
        rows, counts = tally_column(path)
        self.assertEqual(rows, 2)
        self.assertEqual(counts, {"biolink:NamedThing": 1, UNCATEGORIZED: 1})

    def test_a_header_only_file_has_no_rows(self):
        self.assertEqual(tally_column(tsv(self.dir, "n.tsv", ["id", "category"])),
                         (0, {}))

    def test_an_empty_file_has_no_rows(self):
        # The old count was len(readlines()) - 1, which made this -1.
        path = os.path.join(self.dir, "empty.tsv")
        open(path, "w").close()
        self.assertEqual(tally_column(path), (0, {}))

    def test_another_column_can_be_tallied(self):
        path = tsv(self.dir, "e.tsv",
                   ["id", "predicate", "category"],
                   ["e1", "biolink:subclass_of", ROOT_ASSOCIATION],
                   ["e2", "biolink:part_of", ROOT_ASSOCIATION])
        self.assertEqual(tally_column(path, "predicate")[1],
                         {"biolink:subclass_of": 1, "biolink:part_of": 1})

    def test_the_file_is_not_read_into_memory(self):
        # The reason this replaced readlines(): a large ontology's node file
        # runs to hundreds of megabytes and was being held whole to take its
        # length. Reading lazily is the property under test.
        path = tsv(self.dir, "n.tsv", ["id", "category"], ["A", "x"])
        with mock.patch("builtins.open", mock.mock_open(
                read_data="id\tcategory\nA\tx\n")) as opened:
            tally_column(path)
        handle = opened.return_value
        self.assertFalse(handle.readlines.called)
        self.assertFalse(handle.read.called)


class TestTheLogLine(TestCase):
    """The tally as one line, since it is logged per ontology across ~1200 of them."""

    def test_the_biggest_category_comes_first(self):
        self.assertEqual(
            format_tally({"biolink:Disease": 3, "biolink:NamedThing": 90}),
            "biolink:NamedThing 90, biolink:Disease 3")

    def test_ties_are_ordered_by_name_so_a_log_is_reproducible(self):
        self.assertEqual(format_tally({"b": 1, "a": 1}), "a 1, b 1")

    def test_large_counts_are_grouped(self):
        self.assertEqual(format_tally({"biolink:NamedThing": 268909}),
                         "biolink:NamedThing 268,909")

    def test_a_long_tail_is_truncated_rather_than_dumped(self):
        line = format_tally({f"c{i}": i for i in range(25)}, limit=3)
        self.assertEqual(line, "c24 24, c23 23, c22 22, and 22 more")

    def test_nothing_to_report_says_so(self):
        self.assertEqual(format_tally({}), "none")

    def test_it_stays_on_one_line(self):
        self.assertNotIn("\n", format_tally({f"c{i}": i for i in range(50)}))


class TestEveryEdgeGetsACategory(TestCase):
    """Blank on almost every published edge; biolink:Association on all of them now."""

    def test_an_edge_without_one_gets_the_root_association(self):
        edge = {"subject": "A", "predicate": "biolink:subclass_of", "object": "B"}
        self.apply(edge)
        self.assertEqual(edge["category"], [ROOT_ASSOCIATION])

    def test_an_edge_that_already_has_one_keeps_it(self):
        # The reified path sets biolink:Association itself, and a future KGX
        # may set something specific. This fills gaps, it does not overwrite.
        edge = {"subject": "A", "object": "B", "category": ["biolink:GeneToGeneAssociation"]}
        self.apply(edge)
        self.assertEqual(edge["category"], ["biolink:GeneToGeneAssociation"])

    def test_nodes_are_left_alone(self):
        # Node records are 2-tuples; only the 4-tuples are edges.
        node = {"id": "A", "category": ["biolink:NamedThing"]}
        records = list(self.patched([("A", node)]))
        self.assertEqual(records[0][1]["category"], ["biolink:NamedThing"])

    def test_the_bare_none_between_records_survives(self):
        # RdfSource yields None for every triple that did not complete a
        # record. Calling len() on it took down the whole parse.
        self.assertEqual(list(self.patched([None, None])), [None, None])

    def test_the_root_is_the_biolink_association_class(self):
        self.assertEqual(ROOT_ASSOCIATION, "biolink:Association")

    def test_the_transform_pipeline_applies_it(self):
        # A patch nothing installs fixes nothing. Every test above drives the
        # patch directly, so they all pass whether or not transformer.py ever
        # calls it -- this is the one that notices.
        self.assertTrue(PATCHED_AT_IMPORT)

    def test_patching_twice_is_a_no_op(self):
        # A second call must not stack another generator on top of the first.
        self.assertFalse(kgx_patches.patch_missing_edge_categories())

    # -- helpers ----------------------------------------------------------- #
    def patched(self, records):
        """Run `records` through the patch as KGX's parse would yield them."""
        from kgx.source.owl_source import OwlSource

        with mock.patch.object(OwlSource, "parse", lambda self, *a, **k: iter(records)):
            was = kgx_patches._edge_category_patched
            kgx_patches._edge_category_patched = False
            try:
                kgx_patches.patch_missing_edge_categories()
                return list(OwlSource.parse(None))
            finally:
                # Restore what it was, not an assumed True: forcing it True here
                # is what let a build that never applies the patch pass.
                kgx_patches._edge_category_patched = was

    def apply(self, edge):
        list(self.patched([("A", "B", "key", edge)]))


class TestItReachesTheStats(TestCase):
    """A count nobody can read is not a report. It has to land in the index."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "transformed")
        os.makedirs(self.output_dir, exist_ok=True)

        self.txr = Transformer.__new__(Transformer)
        self.txr.input_dir = self.input_dir
        self.txr.output_dir = self.output_dir
        self.txr.timeout_sec, self.txr.timeout_min = 60, 1
        self.txr.max_source_bytes = 0
        self.txr.robot_path, self.txr.robot_env = "/nonexistent/robot", {}

        self.source = os.path.join(self.input_dir, "ONTO", "1", "onto.owl")
        os.makedirs(os.path.dirname(self.source), exist_ok=True)
        with open(self.source, "w") as f:
            f.write(RDFXML)

    def run_transform(self, nodes, edges, all_at_once=False):
        """Run one ontology through, with KGX writing exactly these TSV rows."""
        def robot(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(RDFXML)
            return RobotResult(True)

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                for suffix, rows in (("_nodes.tsv", nodes), ("_edges.tsv", edges)):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        for row in rows:
                            fh.write("\t".join(row) + "\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            if all_at_once:
                self.txr.transform_all(compress=False)
                return None
            return self.txr.transform(self.source, compress=False)

    NODES = (["id", "category"], ["A", "biolink:Disease"], ["B", "biolink:NamedThing"])
    EDGES = (["id", "category"], ["e1", ROOT_ASSOCIATION], ["e2", ROOT_ASSOCIATION])

    def stats(self):
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            return {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}["ONTO"]

    def test_the_node_tally_reaches_the_outcome(self):
        outcome = self.run_transform(self.NODES, self.EDGES)
        self.assertEqual(outcome.node_categories,
                         {"biolink:Disease": 1, "biolink:NamedThing": 1})

    def test_the_edge_tally_reaches_the_outcome(self):
        outcome = self.run_transform(self.NODES, self.EDGES)
        self.assertEqual(outcome.edge_categories, {ROOT_ASSOCIATION: 2})

    def test_the_counts_still_come_out_right(self):
        # tally_column replaced the readlines() that produced these; they are
        # published numbers and must not shift.
        outcome = self.run_transform(self.NODES, self.EDGES)
        self.assertEqual((outcome.nodecount, outcome.edgecount), (2, 2))

    def test_the_node_tally_reaches_onto_stats(self):
        self.run_transform(self.NODES, self.EDGES, all_at_once=True)
        self.assertEqual(self.stats()["node_categories"],
                         {"biolink:Disease": 1, "biolink:NamedThing": 1})

    def test_the_edge_tally_reaches_onto_stats(self):
        self.run_transform(self.NODES, self.EDGES, all_at_once=True)
        self.assertEqual(self.stats()["edge_categories"], {ROOT_ASSOCIATION: 2})

    def test_it_survives_a_yaml_round_trip_as_plain_data(self):
        # onto_stats.yaml is read by merge_stats.py and the site builder with
        # safe_load; a tagged Python object would fail to load there.
        self.run_transform(self.NODES, self.EDGES, all_at_once=True)
        text = open(os.path.join(self.output_dir, "onto_stats.yaml")).read()
        self.assertNotIn("!!python", text)
        self.assertIsInstance(self.stats()["node_categories"], dict)

    def test_an_ontology_with_no_edges_carries_no_edge_field(self):
        # An empty mapping on every such entry would be noise in the index.
        self.run_transform(self.NODES, (["id", "category"],), all_at_once=True)
        self.assertNotIn("edge_categories", self.stats())

    def test_a_failure_records_no_tally(self):
        # There are no files to tally, and a stale count would be worse than none.
        def robot_fails(**kwargs):
            return RobotResult(False, error="ROBOT could not load it")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot_fails):
            outcome = self.txr.transform(self.source, compress=False)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.node_categories, {})
        self.assertEqual(outcome.edge_categories, {})

    def test_the_tally_is_logged_per_ontology(self):
        # The other half of the issue: a shard log should say what came out of
        # an ontology, not only how much.
        with self.assertLogs(level="INFO") as logs:
            self.run_transform(self.NODES, self.EDGES)
        output = "\n".join(logs.output)
        self.assertIn("ONTO: node categories: biolink:Disease 1", output)
        self.assertIn(f"ONTO: edge categories: {ROOT_ASSOCIATION} 2", output)
