"""The imports an ontology declares, by IRI, and the IRI it gives itself (#185).

The count alone (#177) says how many; the site wants to say which, and to
tell when one is another ontology KG-Bioportal holds. So the transformer reads
the targets out of the declarations, in every serialization the strippers
know, and records them beside the count.
"""

import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal.transformer import (
    SourceInfo,
    Transformer,
    describe_source,
    list_imports,
    ontology_iri,
)

RDFXML = """<?xml version="1.0"?>
<!DOCTYPE rdf:RDF [ <!ENTITY oboe-base "http://ecoinformatics.org/oboe/oboe.1.2/"> ]>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#" xml:base="http://example.org/base">
  <owl:Ontology rdf:about="&oboe-base;oboe.owl">
    <owl:imports rdf:resource="&oboe-base;oboe-core.owl"/>
    <owl:imports rdf:resource="http://purl.obolibrary.org/obo/ro.owl"/>
    <owl:imports><rdf:Description rdf:about="http://example.org/nested"/></owl:imports>
  </owl:Ontology>
</rdf:RDF>
"""

RDFXML_EMPTY_ABOUT = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#" xml:base="http://example.org/from-base">
  <owl:Ontology rdf:about=""/>
</rdf:RDF>
"""

OWLXML = """<?xml version="1.0"?>
<Ontology xmlns="http://www.w3.org/2002/07/owl#" ontologyIRI="http://example.org/o">
  <Import>http://example.org/a</Import>
  <Import> http://example.org/b </Import>
</Ontology>
"""

TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix sweet: <http://sweetontology.net/> .
@base <http://sweetontology.net/sweetAll> .
<http://sweetontology.net/sweetAll> a owl:Ontology ;
    owl:imports <http://sweetontology.net/human> ,
                sweet:humanAgriculture ,
                <http://sweetontology.net/humanCommerce> .
"""

TURTLE_RELATIVE_SELF = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@base <http://example.org/rel> .
<> a owl:Ontology ; owl:imports <http://example.org/x> .
"""

OBO = """format-version: 1.2
ontology: pato
import: http://purl.obolibrary.org/obo/pato/imports/bfo_import.owl
import: http://purl.obolibrary.org/obo/ro.owl

[Term]
id: PATO:1
"""

FUNCTIONAL = """Prefix(:=<http://e/>)
Ontology(<http://e/o>
Import(<http://e/a>)
Import( <http://e/b> )
)
"""

MANCHESTER = """Prefix: : <http://e/>
Ontology: <http://e/o>
Import: <http://e/a>
Class: A
"""


class TestListImports(TestCase):
    def test_rdfxml_resource_nested_and_entity_forms(self):
        self.assertEqual(list_imports(RDFXML, "xml"), [
            "http://ecoinformatics.org/oboe/oboe.1.2/oboe-core.owl",
            "http://purl.obolibrary.org/obo/ro.owl",
            "http://example.org/nested",
        ])

    def test_owlxml(self):
        self.assertEqual(list_imports(OWLXML, "xml"), ["http://example.org/a", "http://example.org/b"])

    def test_turtle_iris_and_prefixed_names(self):
        self.assertEqual(list_imports(TURTLE, "turtle"), [
            "http://sweetontology.net/human",
            "http://sweetontology.net/humanAgriculture",
            "http://sweetontology.net/humanCommerce",
        ])

    def test_obo(self):
        self.assertEqual(list_imports(OBO, "obo"), [
            "http://purl.obolibrary.org/obo/pato/imports/bfo_import.owl",
            "http://purl.obolibrary.org/obo/ro.owl",
        ])

    def test_functional_and_manchester(self):
        self.assertEqual(list_imports(FUNCTIONAL, None), ["http://e/a", "http://e/b"])
        self.assertEqual(list_imports(MANCHESTER, None), ["http://e/a"])

    def test_duplicates_are_listed_once(self):
        twice = TURTLE.replace("<http://sweetontology.net/humanCommerce>", "<http://sweetontology.net/human>")
        self.assertEqual(len(list_imports(twice, "turtle")), 2)

    def test_no_imports_is_empty(self):
        self.assertEqual(list_imports("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://e/o> a owl:Ontology .\n", "turtle"), [])


class TestOntologyIri(TestCase):
    def test_rdfxml_with_entity(self):
        self.assertEqual(ontology_iri(RDFXML, "xml"), "http://ecoinformatics.org/oboe/oboe.1.2/oboe.owl")

    def test_rdfxml_empty_about_falls_back_to_xml_base(self):
        self.assertEqual(ontology_iri(RDFXML_EMPTY_ABOUT, "xml"), "http://example.org/from-base")

    def test_owlxml(self):
        self.assertEqual(ontology_iri(OWLXML, "xml"), "http://example.org/o")

    def test_turtle(self):
        self.assertEqual(ontology_iri(TURTLE, "turtle"), "http://sweetontology.net/sweetAll")

    def test_turtle_relative_self_falls_back_to_base(self):
        self.assertEqual(ontology_iri(TURTLE_RELATIVE_SELF, "turtle"), "http://example.org/rel")

    def test_obo_id_becomes_the_purl(self):
        self.assertEqual(ontology_iri(OBO, "obo"), "http://purl.obolibrary.org/obo/pato.owl")

    def test_functional_and_manchester(self):
        self.assertEqual(ontology_iri(FUNCTIONAL, None), "http://e/o")
        self.assertEqual(ontology_iri(MANCHESTER, None), "http://e/o")

    def test_nothing_is_empty(self):
        self.assertEqual(ontology_iri("[Term]\nid: X:1\n", "obo"), "")


class TestDescribeSource(TestCase):
    def test_reads_count_iris_and_self_in_one_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "oboe.owl")
            with open(path, "w") as f:
                f.write(RDFXML)
            info = describe_source(path)
        self.assertEqual(info.path, path)
        self.assertEqual(info.imports, 3)
        self.assertEqual(len(info.import_iris), 3)
        self.assertTrue(info.ontology_iri.endswith("/oboe.owl"))

    def test_unreadable_source_is_empty_not_fatal(self):
        info = describe_source("/nonexistent/onto.owl")
        self.assertEqual((info.imports, info.import_iris, info.ontology_iri), (0, [], ""))


class TestIndexCarriesThem(TestCase):
    """The entry gets ontology_iri and import_iris, only where there are any."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "out")
        os.makedirs(self.output_dir)
        self.txr = Transformer.__new__(Transformer)
        self.txr.input_dir = self.input_dir
        self.txr.output_dir = self.output_dir
        self.txr.timeout_min = 1
        self.txr.timeout_sec = 60
        self.txr.max_source_mb = 0
        self.txr.max_source_bytes = 0
        self.txr.full_graphs = False
        self.txr.robot_path = "/nonexistent/robot"
        self.txr.robot_env = {}
        self.txr._sources = {}

    def write(self, acronym, text):
        path = os.path.join(self.input_dir, acronym, "1", "onto.owl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write(text)

    def run_all(self):
        import yaml

        def robot(**kw):
            os.makedirs(os.path.dirname(kw["output_path"]), exist_ok=True)
            with open(kw["input_path"]) as src, open(kw["output_path"], "w") as dst:
                dst.write(src.read())
            return True

        class FakeKGX:
            def __init__(self, *a, **k):
                pass

            def transform(self, input_args, output_args):
                for suffix in ("_nodes.tsv", "_edges.tsv"):
                    with open(output_args["filename"] + suffix, "w") as f:
                        f.write("id\n")

        with mock.patch("kg_bioportal.transformer.robot_convert", robot), \
             mock.patch("kg_bioportal.transformer.robot_relax", robot), \
             mock.patch("kg_bioportal.transformer.KGXTransformer", FakeKGX):
            self.txr.transform_all(compress=False)
        with open(os.path.join(self.output_dir, "onto_stats.yaml")) as f:
            return {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}

    def test_entry_lists_its_imports_and_its_own_iri(self):
        self.write("OBOE", RDFXML)
        entry = self.run_all()["OBOE"]
        self.assertEqual(entry["imports"], 3)
        self.assertEqual(entry["import_iris"][1], "http://purl.obolibrary.org/obo/ro.owl")
        self.assertEqual(entry["ontology_iri"], "http://ecoinformatics.org/oboe/oboe.1.2/oboe.owl")

    def test_no_imports_means_no_list(self):
        self.write("PLAIN", RDFXML_EMPTY_ABOUT)
        entry = self.run_all()["PLAIN"]
        self.assertEqual(entry["imports"], 0)
        self.assertNotIn("import_iris", entry)
        self.assertEqual(entry["ontology_iri"], "http://example.org/from-base")

    def test_source_info_shape(self):
        info = SourceInfo("p")
        self.assertEqual((info.imports, info.import_iris, info.ontology_iri), (0, [], ""))
