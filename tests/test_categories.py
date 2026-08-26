"""Real Biolink categories on the nodes, decided here rather than upstream (#169).

Before this, every node in every published graph was ``biolink:NamedThing``.
That is the right thing for KGX to write -- a plain OWL file says nothing about
Biolink -- but deciding what these ontologies mean in Biolink terms is a
KG-Bioportal judgement, because giving the collection one consistent structure
is much of what the pipeline is for.

Two sources of evidence, both already in the files KGX writes: the subclass
hierarchy, seeded with terms whose meaning is not in doubt, and ``exact_match``
edges, which assert the same referent and so carry a category across. On the 12
graphs sampled from release ``data-2026.08.25-12`` the two together categorize
83.9% of 497,959 nodes (from 0%), and the mapping half is what reaches MONDO's
UMLS/ICD/SNOMED targets -- 74.6% of its nodes -- which have no subclass edges
at all.

The interesting failures are not "a node got nothing", which is the safe
outcome. They are a node getting the *wrong* category because two seeds landed
on it from the same distance, so the tie-breaking has its own tests below.
"""

import os
import re
import tempfile
from unittest import TestCase, mock

from kg_bioportal import categories
from kg_bioportal.categories import (
    CATEGORY_ANCESTORS,
    GENERAL,
    NAMED_THING,
    SEED_INDEX,
    SEEDS,
    SPECIFIC,
    UPPER_SEEDS,
    apply_to,
    assign,
    canonical_forms,
    categorize,
    most_specific,
)

NODE_HEADER = ["id", "category", "name"]
EDGE_HEADER = ["id", "subject", "predicate", "object", "category"]


class Graph:
    """A tiny pair of KGX TSVs on disk, which is what assignment reads."""

    def __init__(self, case, nodes, edges):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.nodes = self._write("nodes.tsv", NODE_HEADER,
                                 [[n, NAMED_THING, ""] for n in nodes])
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

    def categories(self):
        apply_to(self.nodes, self.edges)
        out = {}
        with open(self.nodes) as f:
            f.readline()
            for line in f:
                cells = line.rstrip("\n").split("\t")
                out[cells[0]] = cells[1]
        return out


def sub(child, parent):
    return (child, "biolink:subclass_of", parent)


def same(a, b):
    return (a, "biolink:exact_match", b)


class TestTheSeedTable(TestCase):
    def test_every_seed_names_a_biolink_class(self):
        for curie, category in {**SEEDS, **UPPER_SEEDS}.items():
            self.assertTrue(category.startswith("biolink:"), curie)
            self.assertNotEqual(category, NAMED_THING,
                                f"{curie} seeds the root, which assigns nothing")

    def test_the_two_tables_do_not_overlap(self):
        # A term in both would get whichever tier the expansion happened to
        # write last -- silently, and differently per Python version.
        self.assertEqual(set(SEEDS) & set(UPPER_SEEDS), set())

    def test_upper_seeds_are_the_general_tier(self):
        for curie in UPPER_SEEDS:
            self.assertEqual(SEED_INDEX[curie][1], GENERAL)

    def test_domain_seeds_are_the_specific_tier(self):
        for curie in SEEDS:
            self.assertEqual(SEED_INDEX[curie][1], SPECIFIC)

    def test_owl_thing_is_not_a_seed(self):
        # It is the top root of several ontologies in the sample and rolling up
        # from it would only re-derive NamedThing on everything.
        for useless in ("owl:Thing", "BFO:0000001"):
            self.assertNotIn(useless, SEED_INDEX)


class TestTheIdShapesASeedArrivesIn(TestCase):
    """The same term is not written the same way twice across 1,200 ontologies."""

    def test_the_curie_itself_is_recognised(self):
        self.assertIn("GO:0008150", SEED_INDEX)

    def test_the_obo_wrapped_form_is_recognised(self):
        # VTO's own root arrives as OBO:VTO_0000001, not VTO:0000001.
        self.assertIn("OBO:VTO_0000001", SEED_INDEX)

    def test_the_full_purl_is_recognised(self):
        self.assertIn("http://purl.obolibrary.org/obo/GO_0008150", SEED_INDEX)

    def test_all_three_mean_the_same_category(self):
        forms = canonical_forms("MONDO:0000001")
        self.assertEqual({SEED_INDEX[f][0] for f in forms}, {"biolink:Disease"})

    def test_an_iri_seed_yields_only_itself(self):
        # BFO 1.1's terms are IRIs. Deriving CURIE forms from one would produce
        # "OBO:http_//www..." -- never matched by anything, but junk in an index
        # that is otherwise a list of shapes a node id can actually take.
        iri = "http://www.ifomis.org/bfo/1.1/snap#Quality"
        self.assertEqual(canonical_forms(iri), (iri,))

    OBO_LOCAL = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9.]+$")

    def test_no_seed_index_key_is_a_mangled_iri(self):
        # An IRI put through the CURIE derivation comes out as
        # "OBO:http_//www.ifomis.org/..." -- a key nothing can ever match. Every
        # derived key should look like the OBO local name it claims to be.
        for key in SEED_INDEX:
            for prefix in ("OBO:", "http://purl.obolibrary.org/obo/"):
                if key.startswith(prefix):
                    local = key[len(prefix):]
                    self.assertRegex(local, self.OBO_LOCAL, f"{key} is not an OBO id")

    def test_a_curie_without_a_prefix_does_not_crash(self):
        self.assertEqual(canonical_forms("plain")[0], "plain")


class TestNarrowingAnOverlappingPair(TestCase):
    def test_an_implied_ancestor_is_dropped(self):
        # Every Cell is an AnatomicalEntity, so saying both says nothing more.
        self.assertEqual(
            most_specific({"biolink:Cell", "biolink:AnatomicalEntity"}),
            {"biolink:Cell"})

    def test_an_unrelated_pair_is_left_alone(self):
        # A real disagreement, and worth leaving visible.
        pair = {"biolink:Disease", "biolink:ChemicalEntity"}
        self.assertEqual(most_specific(pair), pair)

    def test_a_single_category_is_returned_unchanged(self):
        self.assertEqual(most_specific({"biolink:Disease"}), {"biolink:Disease"})

    def test_the_ancestor_table_matches_the_model(self):
        # The table is written out so assignment needs no model download at
        # transform time. This is what stops it drifting from Biolink silently.
        try:
            from bmt import Toolkit
            toolkit = Toolkit()
        except Exception as e:  # noqa: BLE001 -- bmt absent, or it cannot fetch
            self.skipTest(f"biolink model toolkit unavailable: {e}")
        used = set(SEEDS.values()) | set(UPPER_SEEDS.values())
        for category in used:
            element = toolkit.get_element(category)
            self.assertIsNotNone(element, f"{category} is not a Biolink class")
            actual = {
                a for a in toolkit.get_ancestors(
                    element.name, reflexive=False, mixin=False, formatted=True)
                if a in used
            }
            self.assertEqual(
                set(CATEGORY_ANCESTORS.get(category, ())), actual,
                f"CATEGORY_ANCESTORS[{category}] is out of step with the model")


class TestRollingDownTheHierarchy(TestCase):
    def test_a_subclass_inherits_from_its_seeded_parent(self):
        g = Graph(self, ["MONDO:0000001", "MONDO:0005148"],
                  [sub("MONDO:0005148", "MONDO:0000001")])
        self.assertEqual(g.categories()["MONDO:0005148"], "biolink:Disease")

    def test_it_reaches_the_bottom_of_a_deep_chain(self):
        chain = ["GO:0008150"] + [f"GO:100000{i}" for i in range(6)]
        edges = [sub(chain[i + 1], chain[i]) for i in range(len(chain) - 1)]
        cats = Graph(self, chain, edges).categories()
        self.assertEqual(cats[chain[-1]], "biolink:BiologicalProcessOrActivity")

    def test_a_class_under_nothing_seeded_keeps_named_thing(self):
        # The safe outcome, and the one every uncategorizable ontology gets.
        g = Graph(self, ["X:1", "X:2"], [sub("X:2", "X:1")])
        self.assertEqual(g.categories()["X:2"], NAMED_THING)

    def test_the_nearer_seed_wins(self):
        # cell is below anatomical entity; a cell type is a Cell, not the
        # AnatomicalEntity it also descends from.
        g = Graph(self,
                  ["UBERON:0001062", "CL:0000000", "CL:0000232"],
                  [sub("CL:0000000", "UBERON:0001062"),
                   sub("CL:0000232", "CL:0000000")])
        self.assertEqual(g.categories()["CL:0000232"], "biolink:Cell")

    def test_a_class_that_is_itself_a_seed_keeps_its_own_category(self):
        g = Graph(self, ["UBERON:0001062", "CL:0000000"],
                  [sub("CL:0000000", "UBERON:0001062")])
        self.assertEqual(g.categories()["CL:0000000"], "biolink:Cell")

    def test_a_seed_with_no_subclasses_is_still_categorized(self):
        # It never enters the graph built from the edge file, so it has to be
        # recognised while the node file is streamed.
        g = Graph(self, ["CHEBI:24431"], [])
        self.assertEqual(g.categories()["CHEBI:24431"], "biolink:ChemicalEntity")

    def test_a_cycle_in_the_hierarchy_terminates(self):
        # rdfs:subClassOf cycles are legal OWL and do occur after relax.
        g = Graph(self, ["MONDO:0000001", "A:1", "A:2"],
                  [sub("A:1", "MONDO:0000001"), sub("A:2", "A:1"), sub("A:1", "A:2")])
        cats = g.categories()
        self.assertEqual(cats["A:1"], "biolink:Disease")
        self.assertEqual(cats["A:2"], "biolink:Disease")


class TestBreakingATie(TestCase):
    """Two seeds, same distance. This is where a wrong category comes from.

    Measured before the tiers existed: 461 AGRO classes came out
    ``Activity|Procedure``, 6,794 OBA and 4,663 GO-PLUS classes came out
    ``AnatomicalEntity|PhysicalEntity``. Biolink does not put AnatomicalEntity
    under PhysicalEntity, so narrowing by the model does not resolve these --
    only knowing that a domain seed says more than an upper-ontology one does.
    """

    def test_a_domain_seed_beats_an_upper_ontology_one(self):
        # UBERON's "material anatomical entity", the real case: one step below
        # anatomical entity and one step below BFO's material entity.
        g = Graph(self,
                  ["UBERON:0001062", "BFO:0000040", "UBERON:0000465"],
                  [sub("UBERON:0000465", "UBERON:0001062"),
                   sub("UBERON:0000465", "BFO:0000040")])
        self.assertEqual(g.categories()["UBERON:0000465"], "biolink:AnatomicalEntity")

    def test_a_planned_process_is_a_procedure_not_a_bare_activity(self):
        # AGRO's "tillage process", under both OBI planned process and BFO process.
        g = Graph(self, ["OBI:0000011", "BFO:0000015", "AGRO:00000002"],
                  [sub("AGRO:00000002", "OBI:0000011"),
                   sub("AGRO:00000002", "BFO:0000015")])
        self.assertEqual(g.categories()["AGRO:00000002"], "biolink:Procedure")

    def test_the_tier_wins_whichever_seed_is_visited_first(self):
        # The tie-break must not depend on visit order. These two pairs put the
        # general seed on either side of the specific one alphabetically, which
        # is what the seeds are walked in.
        for general, specific, expected in (
            ("BFO:0000040", "UBERON:0001062", "biolink:AnatomicalEntity"),
            ("PATO:0000001", "CL:0000000", "biolink:Cell"),
        ):
            with self.subTest(general=general, specific=specific):
                g = Graph(self, [general, specific, "A:1"],
                          [sub("A:1", general), sub("A:1", specific)])
                self.assertEqual(g.categories()["A:1"], expected)

    def test_a_nearer_upper_seed_still_beats_a_distant_domain_one(self):
        # Tiers only break ties. Nearness outranks them, because a seed three
        # steps up says less about a class than one directly above it.
        g = Graph(self,
                  ["MONDO:0000001", "BFO:0000040", "A:1", "A:2", "A:3"],
                  [sub("A:1", "MONDO:0000001"), sub("A:2", "A:1"),
                   sub("A:3", "A:2"), sub("A:3", "BFO:0000040")])
        self.assertEqual(g.categories()["A:3"], "biolink:PhysicalEntity")

    def test_an_implied_ancestor_is_dropped_from_a_tie(self):
        # Reached from cell and from anatomical entity at the same distance and
        # the same tier. Every Cell is an AnatomicalEntity, so the pair says
        # nothing the narrower one does not -- and this is the path that carries
        # most_specific into the result, which testing the helper alone missed.
        g = Graph(self, ["CL:0000000", "UBERON:0001062", "A:1"],
                  [sub("A:1", "CL:0000000"), sub("A:1", "UBERON:0001062")])
        self.assertEqual(g.categories()["A:1"], "biolink:Cell")

    def test_two_equally_specific_seeds_both_stand(self):
        # No basis to pick, and Biolink permits several. #98's tally counts a
        # node once per category, so this stays visible rather than hidden.
        g = Graph(self, ["MONDO:0000001", "CHEBI:24431", "A:1"],
                  [sub("A:1", "MONDO:0000001"), sub("A:1", "CHEBI:24431")])
        self.assertEqual(g.categories()["A:1"],
                         "biolink:ChemicalEntity|biolink:Disease")


class TestCarryingACategoryAcrossAMapping(TestCase):
    """74.6% of MONDO's nodes are mapping targets with no subclass edges at all."""

    def test_an_exact_match_target_takes_the_category(self):
        g = Graph(self,
                  ["MONDO:0000001", "MONDO:0005148", "UMLS:C0011860"],
                  [sub("MONDO:0005148", "MONDO:0000001"),
                   same("MONDO:0005148", "UMLS:C0011860")])
        self.assertEqual(g.categories()["UMLS:C0011860"], "biolink:Disease")

    def test_it_travels_in_either_direction(self):
        g = Graph(self, ["MONDO:0000001", "UMLS:C1"],
                  [same("UMLS:C1", "MONDO:0000001")])
        self.assertEqual(g.categories()["UMLS:C1"], "biolink:Disease")

    def test_the_hierarchy_is_never_overruled_by_a_mapping(self):
        # A mapping only ever fills a gap; the ontology's own structure wins.
        g = Graph(self,
                  ["MONDO:0000001", "CHEBI:24431", "A:1"],
                  [sub("A:1", "CHEBI:24431"), same("A:1", "MONDO:0000001")])
        self.assertEqual(g.categories()["A:1"], "biolink:ChemicalEntity")

    def test_a_close_match_does_not_carry(self):
        # "close" is not "same". MONDO is careful about the difference and so
        # should we be.
        g = Graph(self, ["MONDO:0000001", "X:1"],
                  [("X:1", "biolink:close_match", "MONDO:0000001")])
        self.assertEqual(g.categories()["X:1"], NAMED_THING)

    def test_a_chain_of_mappings_is_followed(self):
        g = Graph(self, ["MONDO:0000001", "A:1", "B:1"],
                  [same("A:1", "MONDO:0000001"), same("B:1", "A:1")])
        self.assertEqual(g.categories()["B:1"], "biolink:Disease")

    def test_mappings_between_two_unknown_nodes_assign_nothing(self):
        g = Graph(self, ["A:1", "B:1"], [same("A:1", "B:1")])
        self.assertEqual(g.categories()["A:1"], NAMED_THING)


class TestRewritingTheNodeFile(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def write(self, name, header, *rows):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write("\t".join(header) + "\n")
            for row in rows:
                f.write("\t".join(row) + "\n")
        return path

    def read(self, path):
        with open(path) as f:
            return [line.rstrip("\n").split("\t") for line in f]

    def test_the_other_columns_survive(self):
        nodes = self.write("n.tsv", ["id", "category", "name", "provided_by"],
                           ["MONDO:0000001", NAMED_THING, "disease", "infores:x"])
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        apply_to(nodes, edges)
        self.assertEqual(self.read(nodes)[1],
                         ["MONDO:0000001", "biolink:Disease", "disease", "infores:x"])

    def test_the_header_is_untouched(self):
        header = ["id", "category", "name"]
        nodes = self.write("n.tsv", header, ["MONDO:0000001", NAMED_THING, "d"])
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        apply_to(nodes, edges)
        self.assertEqual(self.read(nodes)[0], header)

    def test_a_file_with_no_category_column_is_left_alone(self):
        nodes = self.write("n.tsv", ["id", "name"], ["MONDO:0000001", "disease"])
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        report = apply_to(nodes, edges)
        self.assertEqual(self.read(nodes)[1], ["MONDO:0000001", "disease"])
        self.assertEqual(report.total, 0)

    def test_no_temporary_file_is_left_behind(self):
        nodes = self.write("n.tsv", ["id", "category"], ["MONDO:0000001", NAMED_THING])
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        apply_to(nodes, edges)
        self.assertEqual(
            [f for f in os.listdir(self.dir) if f.startswith("n.tsv.")], [])

    def test_a_short_row_is_padded_rather_than_dropped(self):
        nodes = self.write("n.tsv", ["id", "category", "name"], ["MONDO:0000001"])
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        apply_to(nodes, edges)
        self.assertEqual(self.read(nodes)[1][:2], ["MONDO:0000001", "biolink:Disease"])

    def test_the_row_count_does_not_change(self):
        # Whatever else happens, the graph must have as many nodes afterwards.
        rows = [[f"X:{i}", NAMED_THING, str(i)] for i in range(20)]
        rows[0][0] = "MONDO:0000001"
        nodes = self.write("n.tsv", ["id", "category", "name"], *rows)
        edges = self.write("e.tsv", ["subject", "predicate", "object"])
        apply_to(nodes, edges)
        self.assertEqual(len(self.read(nodes)), 21)


class TestTheReport(TestCase):
    def test_each_route_is_counted_separately(self):
        # The seed table is tuned from these numbers, so they have to say which
        # half of the approach did the work.
        g = Graph(self,
                  ["MONDO:0000001", "MONDO:0005148", "UMLS:C1", "X:1"],
                  [sub("MONDO:0005148", "MONDO:0000001"),
                   same("MONDO:0005148", "UMLS:C1")])
        report = apply_to(g.nodes, g.edges)
        self.assertEqual(report.total, 4)
        self.assertEqual(report.seeded, 1)
        self.assertEqual(report.inherited, 1)
        self.assertEqual(report.mapped, 1)
        self.assertEqual(report.uncategorized, 1)
        self.assertEqual(report.assigned, 3)

    def test_the_summary_says_the_share(self):
        g = Graph(self, ["MONDO:0000001", "X:1"], [])
        self.assertIn("1/2 nodes categorized (50.0%)", apply_to(g.nodes, g.edges).summary())

    def test_an_empty_graph_summarizes_without_dividing_by_zero(self):
        g = Graph(self, [], [])
        self.assertEqual(apply_to(g.nodes, g.edges).summary(), "no nodes to categorize")


class TestAFailureCannotCostTheGraph(TestCase):
    """Every other stage has already succeeded by the time this runs."""

    def test_a_broken_assignment_leaves_the_graph_alone(self):
        g = Graph(self, ["MONDO:0000001"], [])
        with mock.patch.object(categories, "apply_to", side_effect=RuntimeError("boom")):
            self.assertIsNone(categorize(g.nodes, g.edges, "DEMO"))
        with open(g.nodes) as f:
            self.assertIn(NAMED_THING, f.read())

    def test_a_missing_edge_file_is_survivable(self):
        g = Graph(self, ["MONDO:0000001"], [])
        self.assertIsNone(categorize(g.nodes, os.path.join(g.dir, "gone.tsv"), "DEMO"))

    def test_the_failure_is_logged_with_the_ontology_named(self):
        g = Graph(self, ["MONDO:0000001"], [])
        with mock.patch.object(categories, "apply_to", side_effect=RuntimeError("boom")):
            with self.assertLogs(level="WARNING") as logs:
                categorize(g.nodes, g.edges, "DEMO")
        self.assertIn("DEMO", "\n".join(logs.output))


class TestTheTransformActuallyRunsIt(TestCase):
    """A module nothing calls categorizes nothing.

    Every test above drives categories.py directly, so they would all pass on a
    build where the transform never invokes it -- which is exactly how a
    mutation survived in #168.
    """

    def test_the_transformer_imports_and_calls_categorize(self):
        from kg_bioportal import transformer
        self.assertIs(transformer.categorize, categorize)

    def test_it_runs_between_kgx_and_the_tally(self):
        # The tally has to see the assigned categories, not the ones KGX wrote,
        # or onto_stats and the site would report NamedThing for everything
        # while the published TSVs said otherwise.
        from kg_bioportal.robot_utils import RobotResult
        from kg_bioportal.transformer import Transformer

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        input_dir = os.path.join(tmp.name, "raw")
        source = os.path.join(input_dir, "ONTO", "1", "onto.owl")
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
        txr.output_dir = os.path.join(tmp.name, "transformed")
        txr.timeout_sec, txr.timeout_min = 60, 1
        txr.max_source_bytes = 0
        txr.robot_path, txr.robot_env = "/nonexistent/robot", {}

        def robot(**kwargs):
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(rdfxml)
            return RobotResult(True)

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                with open(output_args["filename"] + "_nodes.tsv", "w") as f:
                    f.write("id\tcategory\n")
                    f.write(f"MONDO:0000001\t{NAMED_THING}\n")
                    f.write(f"MONDO:0005148\t{NAMED_THING}\n")
                with open(output_args["filename"] + "_edges.tsv", "w") as f:
                    f.write("id\tsubject\tpredicate\tobject\tcategory\n")
                    f.write("e1\tMONDO:0005148\tbiolink:subclass_of\t"
                            "MONDO:0000001\tbiolink:Association\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            outcome = txr.transform(source, compress=False)

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.node_categories, {"biolink:Disease": 2})
