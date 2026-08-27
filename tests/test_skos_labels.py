"""SKOS vocabularies get their names back (#173).

KGX reads the node properties the Biolink model names, where `name` is
`rdfs:label` and nothing else. A vocabulary that labels with `skos:prefLabel` --
which is what SKOS is for -- therefore came out with no names at all. Measured
on release ``data-2026.08.26-16``, over the twenty ontologies holding the most
uncategorized nodes:

    DDSS               89,369 nodes        0 named
    GEXO              166,291 nodes        0 named
    ICD10PCS          192,698 nodes        4 named
    NLMVS              75,182 nodes        1 named
    OCHV              171,288 nodes        1 named
    SNMI              109,166 nodes       10 named
    XREF-FUNDER-REG   205,916 nodes        1 named

1,009,910 nodes, published as if fine. ICD-10-PCS ships 192,698 procedure codes
and four names, three of which are metadata properties rather than codes.

The fix is configuration -- ``Transformer.transform`` already forwards
``predicate_mappings`` and ``node_property_predicates`` to ``RdfSource`` -- with
one trap in it, which is what most of these tests are about. Mapping
``skos:prefLabel`` straight onto ``name`` is *not safe*: ``name`` is
single-valued, so for a term carrying both ``rdfs:label`` and a differing
``prefLabel`` the winner is whichever the parser reaches last, and that order
comes out of a set. Across ``PYTHONHASHSEED`` 0-7 the same file yielded the
rdfs:label three times and the prefLabel five. So prefLabel gets a column of its
own and is folded into `name` afterwards, where the choice can be made against
what was written rather than against parse order.
"""

import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal.transformer import (
    KGX_NODE_COLUMNS,
    NODE_COLUMNS,
    PREF_LABEL_COLUMN,
    SKOS,
    SKOS_PROPERTY_MAP,
    adopt_pref_labels,
)


class NodeFile:
    """A node TSV on disk, which is what the pass reads."""

    def __init__(self, case, header, *rows):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.path = os.path.join(tmp.name, "nodes.tsv")
        with open(self.path, "w") as f:
            f.write("\t".join(header) + "\n")
            for row in rows:
                f.write("\t".join(row) + "\n")

    def read(self):
        with open(self.path) as f:
            return [line.rstrip("\n").split("\t") for line in f]

    def rows(self):
        out = self.read()
        return [dict(zip(out[0], r)) for r in out[1:]]


HEADER = ["id", "category", "name", "description", PREF_LABEL_COLUMN]


class TestAdoptingAPrefLabel(TestCase):
    def test_an_empty_name_takes_the_pref_label(self):
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "", "", "aspirin tablet"])
        self.assertEqual(adopt_pref_labels(f.path), 1)
        self.assertEqual(f.rows()[0]["name"], "aspirin tablet")

    def test_an_existing_name_is_kept(self):
        # rdfs:label always wins. This is the whole reason for the extra column.
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "from rdfs", "", "from skos"])
        self.assertEqual(adopt_pref_labels(f.path), 0)
        self.assertEqual(f.rows()[0]["name"], "from rdfs")

    def test_a_whitespace_only_name_counts_as_empty(self):
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "   ", "", "real label"])
        adopt_pref_labels(f.path)
        self.assertEqual(f.rows()[0]["name"], "real label")

    def test_a_whitespace_only_pref_label_is_not_adopted(self):
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "", "", "  "])
        self.assertEqual(adopt_pref_labels(f.path), 0)
        self.assertEqual(f.rows()[0]["name"], "")

    def test_the_scratch_column_is_dropped(self):
        # It exists only to keep prefLabel from racing rdfs:label; publishing it
        # would put the same string in two columns of every SKOS graph.
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "", "", "x"])
        adopt_pref_labels(f.path)
        self.assertNotIn(PREF_LABEL_COLUMN, f.read()[0])

    def test_the_other_columns_survive_in_order(self):
        f = NodeFile(self, HEADER, ["A:1", "biolink:Disease", "", "a def", "x"])
        adopt_pref_labels(f.path)
        self.assertEqual(f.read()[0], ["id", "category", "name", "description"])
        self.assertEqual(f.rows()[0],
                         {"id": "A:1", "category": "biolink:Disease",
                          "name": "x", "description": "a def"})

    def test_the_row_count_does_not_change(self):
        rows = [[f"X:{i}", "biolink:NamedThing", "", "", f"label {i}"] for i in range(25)]
        f = NodeFile(self, HEADER, *rows)
        self.assertEqual(adopt_pref_labels(f.path), 25)
        self.assertEqual(len(f.read()), 26)

    def test_a_short_row_is_padded_rather_than_dropped(self):
        f = NodeFile(self, HEADER, ["A:1"])
        adopt_pref_labels(f.path)
        self.assertEqual(f.rows()[0]["id"], "A:1")
        self.assertEqual(len(f.read()), 2)

    def test_a_file_without_the_column_is_left_alone(self):
        # Written by an older run, or by a test. Must not be rewritten to no
        # effect, and must not lose a column.
        f = NodeFile(self, ["id", "category", "name"], ["A:1", "biolink:NamedThing", "n"])
        self.assertEqual(adopt_pref_labels(f.path), 0)
        self.assertEqual(f.read(), [["id", "category", "name"],
                                    ["A:1", "biolink:NamedThing", "n"]])

    def test_an_empty_file_does_not_raise(self):
        path = os.path.join(tempfile.mkdtemp(), "empty.tsv")
        open(path, "w").close()
        self.assertEqual(adopt_pref_labels(path), 0)

    def test_a_header_only_file_keeps_its_trimmed_header(self):
        f = NodeFile(self, HEADER)
        self.assertEqual(adopt_pref_labels(f.path), 0)
        self.assertEqual(f.read(), [["id", "category", "name", "description"]])

    def test_no_temporary_file_is_left_behind(self):
        f = NodeFile(self, HEADER, ["A:1", "biolink:NamedThing", "", "", "x"])
        adopt_pref_labels(f.path)
        self.assertEqual([n for n in os.listdir(f.dir) if n != "nodes.tsv"], [])


class TestTheMappingItself(TestCase):
    """The trap: prefLabel must not be handed straight to `name`."""

    def test_pref_label_is_not_mapped_onto_name(self):
        # Doing so makes the published name depend on set iteration order --
        # measured to flip across PYTHONHASHSEED 0-7 on the same input.
        self.assertEqual(SKOS_PROPERTY_MAP[SKOS + "prefLabel"], PREF_LABEL_COLUMN)
        self.assertNotEqual(SKOS_PROPERTY_MAP[SKOS + "prefLabel"], "name")

    def test_alt_label_becomes_a_synonym(self):
        self.assertEqual(SKOS_PROPERTY_MAP[SKOS + "altLabel"], "synonym")

    def test_definition_becomes_the_description(self):
        self.assertEqual(SKOS_PROPERTY_MAP[SKOS + "definition"], "description")

    def test_every_target_is_a_column_we_write(self):
        # A property mapped to a column KGX is not asked for is silently lost.
        for source, target in SKOS_PROPERTY_MAP.items():
            self.assertIn(target, KGX_NODE_COLUMNS, f"{source} -> {target}")

    def test_the_scratch_column_is_asked_for_but_not_published(self):
        self.assertIn(PREF_LABEL_COLUMN, KGX_NODE_COLUMNS)
        self.assertNotIn(PREF_LABEL_COLUMN, NODE_COLUMNS)

    def test_the_published_columns_are_otherwise_unchanged(self):
        # 1,183 published graphs have these; a consumer must not find one moved.
        self.assertEqual(KGX_NODE_COLUMNS[: len(NODE_COLUMNS)], NODE_COLUMNS)


class TestItIsWiredIntoTheTransform(TestCase):
    """A pass nothing calls renames nothing."""

    def setUp(self):
        from kg_bioportal.robot_utils import RobotResult
        from kg_bioportal.transformer import Transformer

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        input_dir = os.path.join(self._tmp.name, "raw")
        source = os.path.join(input_dir, "VOCAB", "1", "onto.owl")
        os.makedirs(os.path.dirname(source))
        rdfxml = ('<?xml version="1.0"?>\n<rdf:RDF '
                  'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                  'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
                  '<owl:Ontology rdf:about="http://example.org/onto"/>\n'
                  '</rdf:RDF>\n')
        with open(source, "w") as f:
            f.write(rdfxml)

        txr = Transformer.__new__(Transformer)
        txr.input_dir = input_dir
        txr.output_dir = os.path.join(self._tmp.name, "transformed")
        txr.timeout_sec, txr.timeout_min = 60, 1
        txr.max_source_bytes = 0
        txr.robot_path, txr.robot_env = "/nonexistent/robot", {}

        def robot(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(rdfxml)
            return RobotResult(True)

        captured = {}

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                captured["input"] = dict(input_args)
                captured["output"] = dict(output_args)
                cols = output_args["node_properties"]
                with open(output_args["filename"] + "_nodes.tsv", "w") as f:
                    f.write("\t".join(cols) + "\n")
                    row = {"id": "A:1", "category": "biolink:NamedThing",
                           PREF_LABEL_COLUMN: "from skos"}
                    f.write("\t".join(row.get(c, "") for c in cols) + "\n")
                with open(output_args["filename"] + "_edges.tsv", "w") as f:
                    f.write("id\tsubject\tpredicate\tobject\tcategory\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            self.outcome = txr.transform(source, compress=False)
        self.captured = captured
        self.nodes = os.path.join(txr.output_dir, "VOCAB", "1", "VOCAB_nodes.tsv")

    def test_the_skos_predicates_reach_input_args(self):
        self.assertEqual(self.captured["input"]["predicate_mappings"], SKOS_PROPERTY_MAP)
        self.assertEqual(sorted(self.captured["input"]["node_property_predicates"]),
                         sorted(SKOS_PROPERTY_MAP))

    def test_kgx_is_asked_for_the_scratch_column(self):
        self.assertEqual(self.captured["output"]["node_properties"], KGX_NODE_COLUMNS)

    def test_the_published_file_has_the_name_and_not_the_column(self):
        with open(self.nodes) as f:
            header = f.readline().rstrip("\n").split("\t")
            row = dict(zip(header, f.readline().rstrip("\n").split("\t")))
        self.assertNotIn(PREF_LABEL_COLUMN, header)
        self.assertEqual(row["name"], "from skos")

    def test_the_transform_still_succeeds(self):
        self.assertTrue(self.outcome.success)
        self.assertEqual(self.outcome.nodecount, 1)
