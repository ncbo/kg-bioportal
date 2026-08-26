"""Every edge gets an id, and provenance names the ontology rather than a temp file.

Two faults visible in the same rows of every published graph.

**#71.** KGX's RdfSource drains its edge cache in two places. The mid-stream
drain, which fires at CACHE_SIZE (10,000), assigns an id to every edge that has
none. The final drain at end-of-parse does not. So ids arrive only in whole
batches of 10,000 and the remainder never get one -- measured on release
data-2026.08.25-12:

    BFO         115 edges        115 blank (100.0%)   never flushes
    AGRO      8,691 edges      6,466 blank ( 74.4%)
    NANDO    14,133 edges      4,133 blank ( 29.2%)   10,000 with ids
    MONDO   268,909 edges      8,909 blank (  3.3%)  260,000 with ids

In NANDO the boundary is positional, not semantic: rows 2-10001 carry ids and
everything after does not, with the same mix of predicates on both sides.

**#72.** KGX reads provenance out of ``input_args``, in Transformer.transform::

    default_provenance = os.path.basename(f)
    g = source.parse(f, default_provenance=default_provenance, **input_args)

The pipeline set ``provided_by`` and ``aggregator_knowledge_source`` on
``output_args`` instead, where nothing reads them, so every node and edge of all
1190 graphs fell back to the basename of our own intermediate --
``<ACRONYM>_relaxed.owl``, a file that exists only inside a runner's temp
directory.

These tests run against the real KGX, not a stub: the patch threads a generator
that also yields bare ``None`` between records, which a stub would not have
reproduced.
"""

import os
import tempfile
from unittest import TestCase

from kgx.source.owl_source import OwlSource

from kg_bioportal import kgx_patches
from kg_bioportal.transformer import (
    AGGREGATOR_INFORES,
    EDGE_COLUMNS,
    NODE_COLUMNS,
    ontology_infores,
)

kgx_patches.patch_owl_source_format()

# CACHE_SIZE in kgx.source.rdf_source. The tests below straddle it deliberately.
FLUSH_AT = 10000


class Owner:
    """The little of a KGX Transformer that OwlSource actually touches."""

    def log_error(self, **kwargs):
        pass


def ontology_with(edge_count):
    """An RDF/XML ontology with exactly `edge_count` subclass edges."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "onto.owl")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n<rdf:RDF '
                'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
                'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
                '<owl:Ontology rdf:about="http://ex.org/o"/>\n'
                '<owl:Class rdf:about="http://ex.org/Root"/>\n')
        for i in range(edge_count):
            f.write(f'<owl:Class rdf:about="http://ex.org/C{i}">'
                    f'<rdfs:subClassOf rdf:resource="http://ex.org/Root"/>'
                    f'<rdfs:label>C{i}</rdfs:label></owl:Class>\n')
        f.write('</rdf:RDF>\n')
    return path


def parse(path, **provenance):
    """Nodes and edges as KGX yields them, with our patches in place."""
    records = list(OwlSource(owner=Owner()).parse(path, format="owl", **provenance))
    edges = [r[3] for r in records if isinstance(r, tuple) and len(r) == 4]
    nodes = [r[1] for r in records if isinstance(r, tuple) and len(r) == 2]
    return nodes, edges


class TestEveryEdgeHasAnId(TestCase):
    """The counts above go to zero."""

    def test_a_small_ontology_that_never_flushes(self):
        # BFO's case: 115 edges, no flush, and before the fix not one id.
        _, edges = parse(ontology_with(115))
        self.assertEqual(len(edges), 115)
        self.assertEqual([e for e in edges if not e.get("id")], [])

    def test_an_ontology_that_straddles_the_flush(self):
        # NANDO's case: the remainder after the last whole batch.
        _, edges = parse(ontology_with(FLUSH_AT + 200))
        self.assertEqual(len(edges), FLUSH_AT + 200)
        self.assertEqual(len([e for e in edges if not e.get("id")]), 0)

    def test_the_id_is_the_one_kgx_would_have_written(self):
        # Not a second scheme alongside KGX's: the same subject-predicate-object.
        _, edges = parse(ontology_with(3))
        for edge in edges:
            self.assertEqual(
                edge["id"],
                f"{edge['subject']}-{edge['predicate']}-{edge['object']}",
            )

    def test_ids_are_stable_across_parses(self):
        # Derived, not generated: the same ontology yields the same ids, so a
        # rebuilt graph does not look like a graph of entirely new edges.
        path = ontology_with(50)
        first = sorted(e["id"] for e in parse(path)[1])
        self.assertEqual(sorted(e["id"] for e in parse(path)[1]), first)

    def test_an_edge_that_already_has_an_id_keeps_it(self):
        # Edges dereified from an owl:Axiom bring their own; the patch fills
        # gaps rather than overwriting.
        edge = {"subject": "A", "predicate": "p", "object": "B", "id": "kept"}
        self.assertEqual(kgx_patches.edge_key(edge), "A-p-B")
        self.assertEqual(edge["id"], "kept")

    def test_patching_twice_is_a_no_op(self):
        self.assertFalse(kgx_patches.patch_missing_edge_ids())


class TestProvenanceNamesTheOntology(TestCase):
    """Not <ACRONYM>_relaxed.owl, which is a file on a runner that no longer exists."""

    def setUp(self):
        self.path = ontology_with(5)
        self.nodes, self.edges = parse(
            self.path,
            provided_by=ontology_infores("AGRO"),
            primary_knowledge_source=ontology_infores("AGRO"),
            aggregator_knowledge_source=AGGREGATOR_INFORES,
        )

    def flat(self, value):
        return value[0] if isinstance(value, list) else value

    def test_nodes_say_which_ontology_provided_them(self):
        self.assertEqual(self.flat(self.nodes[-1]["provided_by"]),
                         "infores:bioportal.agro")

    def test_edges_name_the_ontology_as_the_primary_source(self):
        self.assertEqual(self.flat(self.edges[-1]["primary_knowledge_source"]),
                         "infores:bioportal.agro")

    def test_edges_name_bioportal_as_the_aggregator(self):
        self.assertEqual(self.flat(self.edges[-1]["aggregator_knowledge_source"]),
                         "infores:bioportal")

    def test_nothing_carries_the_intermediate_filename(self):
        # The whole point. Before the fix every one of these held "onto.owl".
        for record in self.nodes + self.edges:
            for key, value in record.items():
                self.assertNotIn(
                    "onto.owl", str(value), f"{key} still names the intermediate")

    def test_without_provenance_kgx_falls_back_to_the_filename(self):
        # Holds the diagnosis in place: this is what the published graphs show,
        # and what the pipeline gets if the keys go anywhere but input_args.
        # Transformer.transform is what supplies the basename, so pass it the
        # way it does rather than asserting parse() invents it.
        nodes, _ = parse(self.path, default_provenance=os.path.basename(self.path))
        self.assertEqual(self.flat(nodes[-1]["provided_by"]), "onto.owl")

    def test_our_provenance_wins_over_that_fallback(self):
        # The pipeline passes both: KGX supplies default_provenance from the
        # filename and we supply the real thing alongside it.
        nodes, edges = parse(
            self.path,
            default_provenance=os.path.basename(self.path),
            provided_by=ontology_infores("AGRO"),
            primary_knowledge_source=ontology_infores("AGRO"),
            aggregator_knowledge_source=AGGREGATOR_INFORES,
        )
        self.assertEqual(self.flat(nodes[-1]["provided_by"]),
                         "infores:bioportal.agro")
        self.assertEqual(self.flat(edges[-1]["primary_knowledge_source"]),
                         "infores:bioportal.agro")


class TestTheInforesIdentifiers(TestCase):
    def test_the_acronym_is_lowercased_and_namespaced(self):
        self.assertEqual(ontology_infores("AGRO"), "infores:bioportal.agro")

    def test_a_hyphenated_acronym_survives(self):
        self.assertEqual(ontology_infores("FAST-EVENT-SKOS"),
                         "infores:bioportal.fast-event-skos")

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(ontology_infores("  ZP "), "infores:bioportal.zp")

    def test_the_aggregator_is_bioportal_itself(self):
        self.assertEqual(AGGREGATOR_INFORES, "infores:bioportal")

    def test_an_ontology_is_distinguishable_from_the_aggregator(self):
        # A merged graph has to be able to tell "BioPortal gave us this" from
        # "this ontology asserts it".
        self.assertNotEqual(ontology_infores("BIOPORTAL"), AGGREGATOR_INFORES)


class TestTheProvenanceIsWiredWhereKgxReadsIt(TestCase):
    """The bug was never the values -- it was which dict they were in.

    KGX reads provenance from ``input_args`` and the sink ignores it, so the
    same keys on ``output_args`` are silently dropped. Asserting the values
    round-trip through ``parse()`` does not catch that; this drives
    ``transform()`` and looks at what it actually hands KGX.
    """

    def setUp(self):
        import tempfile as _tempfile
        from unittest import mock

        from kg_bioportal.robot_utils import RobotResult
        from kg_bioportal.transformer import Transformer

        self._tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        input_dir = os.path.join(self._tmp.name, "raw")
        source = os.path.join(input_dir, "AGRO", "1", "agro.owl")
        os.makedirs(os.path.dirname(source), exist_ok=True)
        with open(source, "w") as f:
            f.write('<?xml version="1.0"?>\n<rdf:RDF '
                    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                    'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
                    '<owl:Ontology rdf:about="http://example.org/onto"/>\n'
                    '</rdf:RDF>\n')

        txr = Transformer.__new__(Transformer)
        txr.input_dir = input_dir
        txr.output_dir = os.path.join(self._tmp.name, "transformed")
        txr.timeout_sec, txr.timeout_min = 60, 1
        txr.max_source_bytes = 0
        txr.robot_path, txr.robot_env = "/nonexistent/robot", {}

        captured = {}

        def robot_ok(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write('<?xml version="1.0"?>\n<rdf:RDF '
                        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                        'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
                        '<owl:Ontology rdf:about="http://example.org/onto"/>\n'
                        '</rdf:RDF>\n')
            return RobotResult(True)

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                captured["input"] = dict(input_args)
                captured["output"] = dict(output_args)
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as fh:
                        fh.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot_ok), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot_ok), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            txr.transform(source, compress=False)
        self.captured = captured

    def test_provided_by_reaches_input_args(self):
        self.assertEqual(self.captured["input"]["provided_by"],
                         "infores:bioportal.agro")

    def test_primary_knowledge_source_reaches_input_args(self):
        self.assertEqual(self.captured["input"]["primary_knowledge_source"],
                         "infores:bioportal.agro")

    def test_aggregator_reaches_input_args(self):
        self.assertEqual(self.captured["input"]["aggregator_knowledge_source"],
                         AGGREGATOR_INFORES)

    def test_none_of_it_is_left_on_output_args(self):
        # Where it was, and where KGX never looks.
        for key in ("provided_by", "primary_knowledge_source",
                    "aggregator_knowledge_source", "knowledge_source"):
            self.assertNotIn(key, self.captured["output"])

    def test_the_acronym_is_what_names_the_ontology(self):
        # Not the intermediate file the transform happens to have written.
        self.assertNotIn(
            "relaxed", str(self.captured["input"]["primary_knowledge_source"]))

    def test_the_columns_are_declared_on_output_args(self):
        # Streaming sinks fix their columns before the first record, so without
        # this the provenance is on every record and in no file.
        self.assertEqual(self.captured["output"]["edge_properties"], EDGE_COLUMNS)
        self.assertEqual(self.captured["output"]["node_properties"], NODE_COLUMNS)


class TestTheColumnsExistToWriteItInto(TestCase):
    """Values on a record reach no file if the sink has no column for them.

    KGX streams -- the only way a 250 MB ontology fits on a runner -- and a
    streaming TSV sink fixes its columns before the first record, so it cannot
    discover them. Given no `edge_properties` it falls back to a default set
    that carries `knowledge_source` and neither of the slots we populate. The
    provenance was correct on every record and absent from every file; only
    running the real pipeline showed it.
    """

    def test_the_edge_provenance_columns_are_declared(self):
        self.assertIn("primary_knowledge_source", EDGE_COLUMNS)
        self.assertIn("aggregator_knowledge_source", EDGE_COLUMNS)

    def test_the_node_provenance_column_is_declared(self):
        self.assertIn("provided_by", NODE_COLUMNS)

    def test_the_empty_generic_column_is_gone(self):
        # Nothing fills knowledge_source once the specific slots are set, and an
        # always-empty column is worse than no column.
        self.assertNotIn("knowledge_source", EDGE_COLUMNS)

    def test_edges_keep_every_other_column_they_had(self):
        # 1190 published graphs have these; a consumer reading them must not
        # find one missing.
        for column in ("id", "subject", "predicate", "object", "category", "relation"):
            self.assertIn(column, EDGE_COLUMNS)

    def test_nodes_keep_every_column_they_had(self):
        for column in ("id", "category", "name", "description", "provided_by",
                       "synonym", "exact_synonym", "broad_synonym",
                       "narrow_synonym", "related_synonym"):
            self.assertIn(column, NODE_COLUMNS)

    def test_the_columns_are_ordered_not_a_set(self):
        # The header has to be stable across runs, so a diff of two releases
        # shows changed data rather than reshuffled columns.
        self.assertIsInstance(EDGE_COLUMNS, list)
        self.assertIsInstance(NODE_COLUMNS, list)
