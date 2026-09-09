"""Base and full graphs for every ontology (#177).

The base graph is the ontology with its imports stripped, as always. The full
graph is the ontology with its import closure merged in by ROBOT, published
beside it. An import-only ontology (SWEET, OBOE) yields a base graph that is
nothing but a header, and the index has to say so instead of calling it OK
like any other.

ROBOT and KGX are faked throughout: what is under test is which file each
step is handed, what gets written where, and what the index records.
"""

import os
import tarfile
import tempfile
from unittest import TestCase, mock

import yaml

from kg_bioportal.robot_utils import RobotResult, mentions_unloadable_import
from kg_bioportal.transformer import (
    BASE,
    FULL,
    SourceTooLarge,
    TransformOutcome,
    Transformer,
    is_import_only,
)

SOURCE_WITH_IMPORTS = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto">
    <owl:imports rdf:resource="https://example.org/part-one"/>
    <owl:imports rdf:resource="https://example.org/part-two"/>
  </owl:Ontology>
  <owl:Class rdf:about="http://example.org/onto#A"/>
</rdf:RDF>
"""

SOURCE_WITHOUT_IMPORTS = SOURCE_WITH_IMPORTS.replace(
    '    <owl:imports rdf:resource="https://example.org/part-one"/>\n', ""
).replace('    <owl:imports rdf:resource="https://example.org/part-two"/>\n', "")


class Calls:
    """What the faked ROBOT and KGX were asked to do, in order."""

    def __init__(self):
        self.robot = []   # (command, input_path, output_path)
        self.kgx = []     # (input_path, output_stem)


class FullGraphTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "transformed")
        os.makedirs(self.output_dir)

        self.txr = Transformer.__new__(Transformer)
        self.txr.input_dir = self.input_dir
        self.txr.output_dir = self.output_dir
        self.txr.timeout_min = 1
        self.txr.timeout_sec = 60
        self.txr.max_source_mb = 0
        self.txr.max_source_bytes = 0
        self.txr.full_graphs = True
        self.txr.robot_path = "/nonexistent/robot"
        self.txr.robot_env = {}
        self.txr._sources = {}

        self.calls = Calls()
        # Counts the fake KGX writes for each variant: {stem_suffix: (nodes, edges)}
        self.counts = {"": (5, 4), "_full": (50, 40)}
        self.merge_outcome = RobotResult(True)

    def write_source(self, text, acronym="ONTO", filename="onto.owl"):
        path = os.path.join(self.input_dir, acronym, "1", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def fakes(self):
        calls, counts, merge_outcome = self.calls, self.counts, self.merge_outcome

        def robot_step(command):
            def run(**kw):
                calls.robot.append((command, kw["input_path"], kw["output_path"]))
                os.makedirs(os.path.dirname(kw["output_path"]), exist_ok=True)
                with open(kw["input_path"]) as src, open(kw["output_path"], "w") as dst:
                    dst.write(src.read())
                if command == "merge":
                    return merge_outcome
                return RobotResult(True)
            return run

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                stem = output_args["filename"]
                calls.kgx.append((input_args["filename"][0], stem))
                suffix = "_full" if stem.endswith("_full") else ""
                n, e = counts[suffix]
                with open(stem + "_nodes.tsv", "w") as f:
                    f.write("id\n" + "".join(f"n{i}\n" for i in range(n)))
                with open(stem + "_edges.tsv", "w") as f:
                    f.write("id\n" + "".join(f"e{i}\n" for i in range(e)))

        return (
            mock.patch("kg_bioportal.transformer.robot_convert", robot_step("convert")),
            mock.patch("kg_bioportal.transformer.robot_relax", robot_step("relax")),
            mock.patch("kg_bioportal.transformer.robot_merge", robot_step("merge")),
            mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX),
        )

    def run_all(self, compress=True):
        patches = self.fakes()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.txr.transform_all(compress=compress)
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            index = {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}
        with open(os.path.join(self.output_dir, "total_stats.yaml")) as f:
            totals = yaml.safe_load(f)
        return index, totals

    def run_one(self, source, variant, compress=False):
        patches = self.fakes()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return self.txr.transform(source, compress=compress, variant=variant)


class TestWhatEachGraphIsBuiltFrom(FullGraphTestCase):
    def test_base_graph_is_built_from_the_stripped_source(self):
        source = self.write_source(SOURCE_WITH_IMPORTS)
        self.run_one(source, BASE)
        command, input_path, _ = self.calls.robot[0]
        self.assertEqual(command, "convert")
        self.assertTrue(input_path.endswith("_noimports.owl"), input_path)

    def test_full_graph_is_built_from_the_source_with_its_imports_intact(self):
        source = self.write_source(SOURCE_WITH_IMPORTS)
        self.run_one(source, FULL)
        command, input_path, _ = self.calls.robot[0]
        self.assertEqual(command, "merge")
        self.assertEqual(input_path, source)
        with open(input_path) as f:
            self.assertIn("owl:imports", f.read())

    def test_full_graph_files_all_carry_the_suffix(self):
        source = self.write_source(SOURCE_WITH_IMPORTS)
        self.run_one(source, FULL)
        for _, _, output_path in self.calls.robot:
            self.assertIn("ONTO_full", os.path.basename(output_path), output_path)
        _, stem = self.calls.kgx[0]
        self.assertTrue(stem.endswith("ONTO_full"), stem)

    def test_full_graph_kgx_input_is_import_free(self):
        # Merged or not, KGX must never be handed a file with owl:imports in
        # it: it would fetch them (#136). The fake ROBOT copies its input
        # through, so the merged file still carries the declarations, and
        # transform() deletes its intermediates on success, so the path is
        # what is left to assert on.
        source = self.write_source(SOURCE_WITH_IMPORTS)
        self.run_one(source, FULL)
        kgx_input, _ = self.calls.kgx[0]
        self.assertTrue(kgx_input.endswith("_noimports.owl"), kgx_input)

    def test_source_is_unpacked_and_counted_once_for_both_graphs(self):
        source = self.write_source(SOURCE_WITH_IMPORTS)
        with mock.patch.object(self.txr, "decompress", wraps=self.txr.decompress) as dec:
            base = self.run_one(source, BASE)
            full = self.run_one(source, FULL)
        self.assertEqual(dec.call_count, 0, "an uncompressed source is never decompressed")
        self.assertEqual(base.imports, 2)
        self.assertEqual(full.imports, 2)


class TestArtifacts(FullGraphTestCase):
    def test_both_tarballs_are_written_flat_in_the_output_dir(self):
        self.write_source(SOURCE_WITH_IMPORTS)
        self.run_all()
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "ONTO.tar.gz")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "ONTO_full.tar.gz")))

    def test_full_tarball_members_carry_the_suffix(self):
        # So the two graphs never collide when unpacked side by side.
        self.write_source(SOURCE_WITH_IMPORTS)
        self.run_all()
        with tarfile.open(os.path.join(self.output_dir, "ONTO_full.tar.gz")) as tar:
            self.assertEqual(sorted(tar.getnames()), ["ONTO_full_edges.tsv", "ONTO_full_nodes.tsv"])
        with tarfile.open(os.path.join(self.output_dir, "ONTO.tar.gz")) as tar:
            self.assertEqual(sorted(tar.getnames()), ["ONTO_edges.tsv", "ONTO_nodes.tsv"])

    def test_no_owl_intermediates_are_left_behind(self):
        self.write_source(SOURCE_WITH_IMPORTS)
        self.run_all()
        workdir = os.path.join(self.output_dir, "ONTO", "1")
        leftovers = [f for f in os.listdir(workdir) if f.endswith(".owl")]
        self.assertEqual(leftovers, [])


class TestIndexEntries(FullGraphTestCase):
    def test_base_and_full_are_recorded_separately(self):
        self.write_source(SOURCE_WITH_IMPORTS)
        index, _ = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "OK")
        self.assertEqual((entry["nodecount"], entry["edgecount"]), (5, 4))
        self.assertEqual(entry["full_status"], "OK")
        self.assertEqual((entry["full_nodecount"], entry["full_edgecount"]), (50, 40))
        self.assertEqual(entry["imports"], 2)

    def test_no_imports_means_no_full_graph_and_says_so(self):
        self.write_source(SOURCE_WITHOUT_IMPORTS)
        index, totals = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["full_status"], "Skipped")
        self.assertEqual(entry["full_reason"], "no_imports")
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, "ONTO_full.tar.gz")))
        self.assertNotIn("merge", [c for c, _, _ in self.calls.robot])
        self.assertEqual(totals["fullskippedcount"], 1)

    def test_unresolvable_import_fails_the_full_graph_only(self):
        self.merge_outcome = RobotResult(
            False, "UnloadableImportException: Could not load imported ontology: <http://x>",
            "unresolvable_imports")
        self.write_source(SOURCE_WITH_IMPORTS)
        index, totals = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "OK")
        self.assertEqual(entry["full_status"], "Failed")
        self.assertEqual(entry["full_reason"], "unresolvable_imports")
        self.assertIn("Could not load imported ontology", entry["full_detail"])
        self.assertEqual((entry["full_nodecount"], entry["full_edgecount"]), (0, 0))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "ONTO.tar.gz")))
        self.assertFalse(os.path.exists(os.path.join(self.output_dir, "ONTO_full.tar.gz")))
        self.assertEqual(totals["fullfailedcount"], 1)
        self.assertEqual(totals["failedcount"], 0)

    def test_full_graph_is_not_attempted_when_the_base_failed(self):
        self.write_source(SOURCE_WITH_IMPORTS)
        with mock.patch.object(self.txr, "transform",
                               side_effect=lambda *a, **k: TransformOutcome.failed("convert", "boom")):
            index, _ = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "Failed")
        self.assertEqual(entry["reason"], "transform_error_convert")
        self.assertNotIn("full_status", entry)

    def test_a_merge_that_fails_for_another_reason_names_the_merge_stage(self):
        self.merge_outcome = RobotResult(False, "java.lang.OutOfMemoryError: Java heap space")
        self.write_source(SOURCE_WITH_IMPORTS)
        index, _ = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["full_status"], "Failed")
        self.assertEqual(entry["full_reason"], "transform_error_merge")
        self.assertIn("OutOfMemoryError", entry["full_detail"])

    def test_a_merge_that_times_out_is_skipped_as_too_slow(self):
        self.merge_outcome = RobotResult(False, "ROBOT merge timed out after 60s", "too_slow")
        self.write_source(SOURCE_WITH_IMPORTS)
        index, _ = self.run_all()
        self.assertEqual(index["ONTO"]["full_status"], "Skipped")
        self.assertEqual(index["ONTO"]["full_reason"], "too_slow")

    def test_base_only_run_records_no_full_fields(self):
        self.txr.full_graphs = False
        self.write_source(SOURCE_WITH_IMPORTS)
        index, totals = self.run_all()
        self.assertNotIn("full_status", index["ONTO"])
        self.assertEqual(totals["fullcount"], 0)
        self.assertNotIn("merge", [c for c, _, _ in self.calls.robot])

    def test_full_graph_over_the_size_gate_is_skipped_as_too_large(self):
        self.txr.max_source_mb = 0.00001
        self.txr.max_source_bytes = 10  # the merged file is bigger than this
        self.write_source(SOURCE_WITH_IMPORTS)
        # The base graph has to pass its own gate; only the merged output is weighed.
        with mock.patch.object(self.txr, "_prepare_source",
                               return_value=(self.write_source(SOURCE_WITH_IMPORTS), 2)):
            index, _ = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "OK")
        self.assertEqual(entry["full_status"], "Skipped")
        self.assertEqual(entry["full_reason"], "too_large")


class TestImportOnly(FullGraphTestCase):
    def test_header_only_base_graph_is_flagged(self):
        self.counts[""] = (2, 0)  # SWEET: the ontology IRI and its license
        self.write_source(SOURCE_WITH_IMPORTS)
        index, totals = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "OK", "the artifact exists and is honest")
        self.assertEqual(entry["reason"], "import_only")
        self.assertEqual(entry["full_status"], "OK")
        self.assertEqual(totals["importonlycount"], 1)
        self.assertEqual(totals["totalcount"], 1)

    def test_base_artifact_is_still_published(self):
        self.counts[""] = (2, 0)
        self.write_source(SOURCE_WITH_IMPORTS)
        self.run_all()
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "ONTO.tar.gz")))

    def test_a_small_ontology_without_imports_is_not_import_only(self):
        self.counts[""] = (2, 0)
        self.write_source(SOURCE_WITHOUT_IMPORTS)
        index, _ = self.run_all()
        self.assertEqual(index["ONTO"]["reason"], "")

    def test_a_flat_ontology_with_imports_is_not_import_only(self):
        # Hundreds of classes and no subclass edges is a flat list, not a shell.
        self.counts[""] = (500, 0)
        self.write_source(SOURCE_WITH_IMPORTS)
        index, _ = self.run_all()
        self.assertEqual(index["ONTO"]["reason"], "")

    def test_full_graph_is_never_flagged_import_only(self):
        self.counts = {"": (2, 0), "_full": (2, 0)}
        self.write_source(SOURCE_WITH_IMPORTS)
        index, _ = self.run_all()
        self.assertEqual(index["ONTO"]["full_reason"], "")

    def test_rule(self):
        self.assertTrue(is_import_only(imports=1, nodecount=2, edgecount=0))
        self.assertTrue(is_import_only(imports=224, nodecount=1, edgecount=0))
        self.assertFalse(is_import_only(imports=0, nodecount=2, edgecount=0))
        self.assertFalse(is_import_only(imports=1, nodecount=2, edgecount=1))
        self.assertFalse(is_import_only(imports=1, nodecount=500, edgecount=0))


class TestUnloadableImportDetection(TestCase):
    """robot_merge tells a dead import apart from any other ROBOT failure."""

    def test_exception_name(self):
        self.assertTrue(mentions_unloadable_import(
            "java.lang.IllegalArgumentException: org.semanticweb.owlapi.model."
            "UnloadableImportException: Could not load imported ontology: <http://x> Cause: y"))

    def test_message_alone(self):
        self.assertTrue(mentions_unloadable_import(
            "Could not load imported ontology: <http://x> Cause: Connect timed out"))

    def test_other_failures_are_not_mistaken_for_it(self):
        self.assertFalse(mentions_unloadable_import("java.lang.OutOfMemoryError: Java heap space"))


class TestSourceTooLargeStillSkipsTheBase(FullGraphTestCase):
    def test_base_over_the_gate_is_too_large_and_no_full_is_attempted(self):
        self.write_source(SOURCE_WITH_IMPORTS)
        with mock.patch.object(self.txr, "_prepare_source", side_effect=SourceTooLarge("big")):
            index, _ = self.run_all()
        entry = index["ONTO"]
        self.assertEqual(entry["status"], "Skipped")
        self.assertEqual(entry["reason"], "too_large")
        self.assertNotIn("full_status", entry)
