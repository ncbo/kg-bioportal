"""The review packet: what a reviewer reads before placing a root (#169)."""

import os
import tarfile
import tempfile
from unittest import TestCase

from kg_bioportal.categories import NAMED_THING
from kg_bioportal.roots import format_packet, open_graph, review_packet

NODE_HEADER = ["id", "category", "name"]
EDGE_HEADER = ["id", "subject", "predicate", "object", "category"]


class TestThePacket(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        # Two roots: a big uncategorized one, and a small categorized one.
        nodes = [
            ("R", NAMED_THING, "root"),
            ("A", NAMED_THING, "chapter a"), ("A1", NAMED_THING, "a one"), ("A2", NAMED_THING, "a two"),
            ("B", NAMED_THING, "chapter b"), ("B1", NAMED_THING, ""),
            ("D", "biolink:Disease", "disease"), ("D1", "biolink:Disease", "flu"),
            ("loose", NAMED_THING, "nothing above or below"),
        ]
        edges = [
            ("A", "biolink:subclass_of", "R"), ("A1", "biolink:subclass_of", "A"),
            ("A2", "biolink:subclass_of", "A"), ("B", "skos:broader", "R"),
            ("B1", "biolink:subclass_of", "B"), ("D1", "biolink:subclass_of", "D"),
        ]
        self.nodes = self._write("T_nodes.tsv", NODE_HEADER, nodes)
        self.edges = self._write("T_edges.tsv", EDGE_HEADER,
                                 [(f"e{i}", s, p, o, "biolink:Association")
                                  for i, (s, p, o) in enumerate(edges)])
        self.packet = review_packet(self.nodes, self.edges, "T")

    def _write(self, name, header, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write("\t".join(header) + "\n")
            for row in rows:
                f.write("\t".join(row) + "\n")
        return path

    def test_the_totals(self):
        self.assertEqual(self.packet["ontology"], "T")
        self.assertEqual(self.packet["nodes"], 9)
        self.assertEqual(self.packet["uncategorized"], 7)
        self.assertEqual(self.packet["hierarchy_edges"], 6)

    def test_only_roots_with_uncategorized_nodes_beneath_are_listed(self):
        self.assertEqual([r["id"] for r in self.packet["roots"]], ["R"])

    def test_children_are_ranked_by_what_a_review_could_still_reach(self):
        kids = self.packet["roots"][0]["children"]
        self.assertEqual([k["id"] for k in kids], ["A", "B"])
        self.assertEqual(kids[0]["uncategorized_descendants"], 2)
        self.assertEqual(kids[0]["sample"], ["a one", "a two"])

    def test_skos_broader_counts_as_hierarchy(self):
        self.assertIn("B", [k["id"] for k in self.packet["roots"][0]["children"]])

    def test_an_unlabelled_child_is_sampled_by_id(self):
        b = next(k for k in self.packet["roots"][0]["children"] if k["id"] == "B")
        self.assertEqual(b["sample"], ["B1"])

    def test_the_reach_is_what_the_listed_roots_cover(self):
        self.assertEqual(self.packet["reachable_from_roots"], 5)

    def test_it_formats_as_yaml(self):
        text = format_packet(self.packet)
        self.assertIn("ontology: T", text)
        self.assertIn("label: chapter a", text)


class TestOpeningAGraph(TestCase):
    def test_a_tarball_is_unpacked_and_found(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = os.path.join(tmp.name, "src")
        os.makedirs(src)
        for name in ("X_nodes.tsv", "X_edges.tsv"):
            with open(os.path.join(src, name), "w") as f:
                f.write("id\n")
        tgz = os.path.join(tmp.name, "X.tar.gz")
        with tarfile.open(tgz, "w:gz") as tar:
            tar.add(src, arcname="X")
        work = os.path.join(tmp.name, "work")
        os.makedirs(work)
        node_file, edge_file = open_graph(tgz, work)
        self.assertTrue(node_file.endswith("X_nodes.tsv"))
        self.assertTrue(edge_file.endswith("X_edges.tsv"))
        self.assertTrue(os.path.exists(node_file))

    def test_anything_else_is_refused(self):
        with self.assertRaises(ValueError):
            open_graph(__file__, tempfile.gettempdir())
