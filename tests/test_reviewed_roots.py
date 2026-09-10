"""Roots placed by review, kept apart from the seeds and counted apart (#169).

The seed table holds terms whose Biolink class is not in doubt. What is left
uncategorized mostly hangs off roots that need a judgement about one ontology
-- ICD9CM's chapters, HGNC's locus groups -- and those judgements were made
with an AI agent's help. The file that holds them carries who, when, what was
read, and whether a person has confirmed it; the roll-up treats them as seeds
but remembers which nodes they reached, so the count on the page is exact.
"""

import os
import tempfile
from unittest import TestCase, mock

import yaml

from kg_bioportal import categories
from kg_bioportal.categories import (
    NAMED_THING,
    REVIEW_BAR,
    REVIEWED_ROOTS,
    SEED_INDEX,
    SPECIFIC,
    apply_to,
    canonical_forms,
    load_reviewed_roots,
    review_record,
    reviewed_index,
)

NODE_HEADER = ["id", "category", "name"]
EDGE_HEADER = ["id", "subject", "predicate", "object", "category"]


class Graph:
    def __init__(self, case, nodes, edges):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.nodes = self._write("nodes.tsv", NODE_HEADER, [[n, NAMED_THING, ""] for n in nodes])
        self.edges = self._write("edges.tsv", EDGE_HEADER,
                                 [[f"e{i}", s, p, o, "biolink:Association"]
                                  for i, (s, p, o) in enumerate(edges)])

    def _write(self, name, header, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write("\t".join(header) + "\n")
            for row in rows:
                f.write("\t".join(row) + "\n")
        return path

    def run(self, ontology=""):
        report = apply_to(self.nodes, self.edges, ontology)
        out = {}
        with open(self.nodes) as f:
            f.readline()
            for line in f:
                cells = line.rstrip("\n").split("\t")
                out[cells[0]] = cells[1]
        return out, report


def sub(child, parent):
    return (child, "biolink:subclass_of", parent)


def same(a, b):
    return (a, "biolink:exact_match", b)


FAKE_REVIEWS = {
    "TESTO": {
        "graph": "data-2026.09.09-99",
        "reviewed": "2026-09-10",
        "reviewer": "a test",
        "confirmed_by": "",
        "also": ["TESTO-TWIN"],
        "roots": [
            {"id": "http://example.org/chapterA", "label": "Diseases",
             "category": "biolink:Disease", "reach": 3, "evidence": ["flu"]},
            {"id": "X:1", "label": "genes", "category": "biolink:Gene",
             "reach": 1, "evidence": ["A1BG"]},
        ],
        "refused": [{"id": "http://example.org/chapterT", "label": "Causes", "why": "accidents"}],
    },
}


def reviewed(test):
    return mock.patch.object(categories, "REVIEWED_ROOTS", load_like(FAKE_REVIEWS))


def load_like(reviews):
    """Run a dict through the loader's `also` expansion, the way the file is."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(reviews, tmp)
    tmp.close()
    try:
        return load_reviewed_roots(tmp.name)
    finally:
        os.remove(tmp.name)


class TestTheIndex(TestCase):
    def test_a_reviewed_root_is_keyed_by_every_form(self):
        with reviewed(self):
            index = reviewed_index("TESTO")
        self.assertEqual(index["http://example.org/chapterA"], ("biolink:Disease", SPECIFIC))
        for form in canonical_forms("X:1"):
            self.assertEqual(index[form], ("biolink:Gene", SPECIFIC))

    def test_it_is_scoped_to_the_ontology_reviewed(self):
        with reviewed(self):
            self.assertEqual(reviewed_index("OTHER"), {})

    def test_the_acronym_is_case_insensitive(self):
        with reviewed(self):
            self.assertIn("X:1", reviewed_index("testo"))

    def test_also_gives_the_same_roots_to_the_ontologies_named(self):
        with reviewed(self):
            self.assertEqual(reviewed_index("TESTO-TWIN"), reviewed_index("TESTO"))

    def test_a_refused_root_is_not_in_the_index(self):
        with reviewed(self):
            self.assertNotIn("http://example.org/chapterT", reviewed_index("TESTO"))

    def test_a_missing_file_means_no_reviews(self):
        self.assertEqual(load_reviewed_roots("/nonexistent/reviewed_roots.yaml"), {})


class TestTheRecord(TestCase):
    def test_the_provenance_and_the_counts_and_nothing_else(self):
        with reviewed(self):
            record = review_record("TESTO")
        self.assertEqual(record, {
            "reviewer": "a test", "reviewed": "2026-09-10", "confirmed_by": "",
            "graph": "data-2026.09.09-99", "roots": 2, "refused": 1,
        })

    def test_an_unreviewed_ontology_has_no_record(self):
        with reviewed(self):
            self.assertEqual(review_record("OTHER"), {})


class TestRollingDownFromAReviewedRoot(TestCase):
    def test_the_subtree_takes_the_category(self):
        g = Graph(self, ["http://example.org/chapterA", "a1", "a2"],
                  [sub("a1", "http://example.org/chapterA"), sub("a2", "a1")])
        with reviewed(self):
            cats, report = g.run("TESTO")
        self.assertEqual(cats["a1"], "biolink:Disease")
        self.assertEqual(cats["a2"], "biolink:Disease")

    def test_every_node_it_reaches_is_counted_as_reviewed(self):
        # The root itself, its subclasses, and nothing else: this is the
        # number the disclosure on the page is made of.
        g = Graph(self, ["http://example.org/chapterA", "a1", "a2", "loose"],
                  [sub("a1", "http://example.org/chapterA"), sub("a2", "a1")])
        with reviewed(self):
            _, report = g.run("TESTO")
        self.assertEqual(report.reviewed, 3)
        self.assertEqual(report.seeded, 0)
        self.assertEqual(report.inherited, 0)
        self.assertEqual(report.uncategorized, 1)
        self.assertEqual(report.assigned, 3)

    def test_it_does_nothing_outside_its_ontology(self):
        g = Graph(self, ["http://example.org/chapterA", "a1"],
                  [sub("a1", "http://example.org/chapterA")])
        with reviewed(self):
            cats, report = g.run("OTHER")
        self.assertEqual(cats["a1"], NAMED_THING)
        self.assertEqual(report.reviewed, 0)

    def test_a_nearer_table_seed_wins_and_is_not_counted_as_reviewed(self):
        # MONDO:0000001 is a table seed. A class one step below it and two
        # below the reviewed chapter takes MONDO's category, by inheritance.
        g = Graph(self, ["http://example.org/chapterA", "MONDO:0000001", "m1"],
                  [sub("MONDO:0000001", "http://example.org/chapterA"),
                   sub("m1", "MONDO:0000001")])
        with reviewed(self):
            cats, report = g.run("TESTO")
        self.assertEqual(cats["m1"], "biolink:Disease")
        self.assertEqual(report.reviewed, 1)   # the chapter itself
        self.assertEqual(report.seeded, 1)     # MONDO:0000001
        self.assertEqual(report.inherited, 1)  # m1

    def test_a_tie_with_a_table_seed_counts_as_reviewed(self):
        # Equally near, same tier: the node keeps both categories, and the
        # count errs towards saying a review was involved.
        g = Graph(self, ["X:1", "GO:0008150", "both"],
                  [sub("both", "X:1"), sub("both", "GO:0008150")])
        with reviewed(self):
            cats, report = g.run("TESTO")
        self.assertEqual(set(cats["both"].split("|")),
                         {"biolink:Gene", "biolink:BiologicalProcessOrActivity"})
        self.assertEqual(report.reviewed, 2)
        self.assertEqual(report.ambiguous, 1)

    def test_the_category_stays_reviewed_across_a_mapping(self):
        g = Graph(self, ["X:1", "g1", "UMLS:C1"],
                  [sub("g1", "X:1"), same("g1", "UMLS:C1")])
        with reviewed(self):
            cats, report = g.run("TESTO")
        self.assertEqual(cats["UMLS:C1"], "biolink:Gene")
        self.assertEqual(report.reviewed, 3)
        self.assertEqual(report.mapped, 0)

    def test_a_reviewed_root_with_no_edges_is_still_categorized(self):
        g = Graph(self, ["X:1"], [])
        with reviewed(self):
            cats, report = g.run("TESTO")
        self.assertEqual(cats["X:1"], "biolink:Gene")
        self.assertEqual(report.reviewed, 1)

    def test_the_summary_names_the_review(self):
        g = Graph(self, ["X:1", "g1"], [sub("g1", "X:1")])
        with reviewed(self):
            _, report = g.run("TESTO")
        self.assertIn("2 by reviewed roots", report.summary())
        self.assertEqual(report.sources(), {"reviewed": 2})


class TestTheShippedFile(TestCase):
    """The file itself, as shipped: every entry has to be a full record."""

    def test_it_is_not_empty(self):
        self.assertGreater(len(REVIEWED_ROOTS), 10)

    def test_every_review_carries_its_provenance(self):
        for acronym, review in REVIEWED_ROOTS.items():
            with self.subTest(ontology=acronym):
                for field in ("graph", "reviewed", "reviewer"):
                    self.assertTrue(review.get(field), f"{acronym} has no {field}")
                self.assertIn("confirmed_by", review, f"{acronym} has no confirmed_by")
                self.assertIn("roots", review)

    def test_every_root_names_a_class_and_its_evidence(self):
        for acronym, review in REVIEWED_ROOTS.items():
            for root in review.get("roots") or ():
                with self.subTest(ontology=acronym, root=root.get("id")):
                    self.assertTrue(str(root["category"]).startswith("biolink:"))
                    self.assertNotEqual(root["category"], NAMED_THING)
                    self.assertTrue(root.get("evidence"), "no evidence recorded")
                    self.assertIn("label", root)
                    self.assertIsInstance(root.get("reach"), int)

    def test_every_refusal_says_why(self):
        for acronym, review in REVIEWED_ROOTS.items():
            for refused in review.get("refused") or ():
                with self.subTest(ontology=acronym, root=refused.get("id")):
                    self.assertTrue(refused.get("why"))

    def test_no_root_is_both_accepted_and_refused(self):
        for acronym, review in REVIEWED_ROOTS.items():
            accepted = {r["id"] for r in review.get("roots") or ()}
            refused = {r["id"] for r in review.get("refused") or ()}
            self.assertEqual(accepted & refused, set(), acronym)

    def test_no_reviewed_root_is_also_a_table_seed(self):
        # The count of nodes owing a category to a review has to be exact,
        # and a root in both places would be counted as a seed.
        for acronym, review in REVIEWED_ROOTS.items():
            for root in review.get("roots") or ():
                for form in canonical_forms(str(root["id"])):
                    self.assertNotIn(form, SEED_INDEX, f"{acronym}: {root['id']} is also a seed")

    def test_the_tops_are_never_seeded(self):
        for acronym, review in REVIEWED_ROOTS.items():
            for root in review.get("roots") or ():
                self.assertNotIn(root["id"], ("owl:Thing", "skos:Concept", "BFO:0000001",
                                              "SIO:000000"), acronym)

    def test_the_bar_is_written_down(self):
        for phrase in ("mixed", "refus", "never seeded", "evidence"):
            self.assertIn(phrase, REVIEW_BAR)

    def test_the_moved_roots_still_carry_their_measured_reach(self):
        self.assertEqual(
            next(r["reach"] for r in REVIEWED_ROOTS["OMIT"]["roots"] if r["id"] == "NCRO:0000025"),
            59874)
