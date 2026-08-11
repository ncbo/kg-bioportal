"""The KGX step must not reach the network.

ROBOT keeps owl:imports in what it writes, and KGX's OwlSource dereferences
every one of them while parsing (#136). Stripping the raw download is not
enough: what KGX is handed has to be import-free too, or a transform can still
die on a remote server's response, and one that succeeds absorbs whatever those
URLs served that day.
"""

import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal.transformer import Transformer

RELAXED_WITH_IMPORTS = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto">
    <owl:imports rdf:resource="https://example.org/dead-remote"/>
    <owl:imports rdf:resource="https://example.org/slow-remote"/>
  </owl:Ontology>
</rdf:RDF>
"""

RELAXED_WITHOUT_IMPORTS = RELAXED_WITH_IMPORTS.replace(
    '    <owl:imports rdf:resource="https://example.org/dead-remote"/>\n', ""
).replace('    <owl:imports rdf:resource="https://example.org/slow-remote"/>\n', "")


class FakeKGXTransformer:
    """Records what KGX was pointed at, and writes the TSVs it would have.

    The content is captured at call time because transform() deletes its OWL
    intermediates once it succeeds -- which is itself the behaviour asserted by
    TestIntermediateCleanup.
    """

    last_input_path = None
    last_input_content = None

    def __init__(self, *args, **kwargs):
        pass

    def transform(self, input_args, output_args):
        path = input_args["filename"][0]
        type(self).last_input_path = path
        with open(path, encoding="utf-8") as f:
            type(self).last_input_content = f.read()
        for suffix in ("_nodes.tsv", "_edges.tsv"):
            with open(output_args["filename"] + suffix, "w") as f:
                f.write("id\n")


class TransformImportsTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "transformed")

        self.txr = Transformer.__new__(Transformer)
        self.txr.input_dir = self.input_dir
        self.txr.output_dir = self.output_dir
        self.txr.timeout_sec = 60
        self.txr.max_source_bytes = 0
        self.txr.robot_path = "/nonexistent/robot"
        self.txr.robot_env = {}

        # data/raw/<ACRONYM>/<submission>/<file> is what transform() expects.
        self.source = os.path.join(self.input_dir, "ONTO", "1", "onto.owl")
        os.makedirs(os.path.dirname(self.source), exist_ok=True)
        with open(self.source, "w") as f:
            f.write(RELAXED_WITHOUT_IMPORTS)

        FakeKGXTransformer.last_input_path = None
        FakeKGXTransformer.last_input_content = None

    def run_transform(self, relaxed_content):
        """Drive transform() with ROBOT and KGX faked out.

        ROBOT is replaced by writers that produce the file each step would;
        the relaxed output is the one that matters here.
        """
        def write_output(**kwargs):
            # ROBOT creates the output directory on the way; so must the fake.
            os.makedirs(os.path.dirname(kwargs["output_path"]), exist_ok=True)
            with open(kwargs["output_path"], "w") as f:
                f.write(relaxed_content)
            return True

        fake_convert = fake_relax = write_output

        with mock.patch("kg_bioportal.transformer.robot_convert", fake_convert), \
             mock.patch("kg_bioportal.transformer.robot_relax", fake_relax), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGXTransformer):
            return self.txr.transform(self.source, compress=False)

    def kgx_saw(self):
        self.assertIsNotNone(FakeKGXTransformer.last_input_path, "KGX was never called")
        return FakeKGXTransformer.last_input_path, FakeKGXTransformer.last_input_content


class TestKGXInputIsImportFree(TransformImportsTestCase):
    def test_imports_are_stripped_before_kgx_parses(self):
        self.run_transform(RELAXED_WITH_IMPORTS)
        _, content = self.kgx_saw()
        self.assertNotIn("owl:imports", content)

    def test_no_remote_url_survives_into_the_kgx_input(self):
        self.run_transform(RELAXED_WITH_IMPORTS)
        _, content = self.kgx_saw()
        self.assertNotIn("dead-remote", content)
        self.assertNotIn("slow-remote", content)

    def test_the_rest_of_the_ontology_survives(self):
        self.run_transform(RELAXED_WITH_IMPORTS)
        _, content = self.kgx_saw()
        self.assertIn("http://example.org/onto", content)

    def test_kgx_is_given_the_cleaned_file_not_the_original(self):
        self.run_transform(RELAXED_WITH_IMPORTS)
        path, _ = self.kgx_saw()
        self.assertTrue(path.endswith("_noimports.owl"), path)

    def test_import_free_output_is_passed_through_untouched(self):
        # No imports means no rewrite, so ontologies that were already hermetic
        # are handed exactly the file ROBOT wrote -- the common case, and the
        # reason this change does not perturb the graphs that build today.
        self.run_transform(RELAXED_WITHOUT_IMPORTS)
        path, _ = self.kgx_saw()
        self.assertTrue(path.endswith("ONTO_relaxed.owl"), path)

    def test_transform_still_succeeds(self):
        success, _, _ = self.run_transform(RELAXED_WITH_IMPORTS)
        self.assertTrue(success)


class TestIntermediateCleanup(TransformImportsTestCase):
    def test_the_stripped_intermediate_is_removed(self):
        self.run_transform(RELAXED_WITH_IMPORTS)
        workdir = os.path.join(self.output_dir, "ONTO", "1")
        leftovers = [f for f in os.listdir(workdir) if f.endswith(".owl")]
        self.assertEqual(leftovers, [], f"OWL intermediates left behind: {leftovers}")
