"""Tests for owl:imports removal.

Unresolvable imports are the single largest cause of ROBOT transform failures
(see #138), and the stripper's serialization detection was where it gave up
silently: Turtle, N3 and OBO sources were skipped outright, and RDF/XML behind a
DOCTYPE entity block was not recognized as XML. These tests pin down what it
handles, that what it rewrites still parses, and the narrow cases where it still
declines on purpose.
"""

import os
import re
import tempfile
from unittest import TestCase

from rdflib import Graph
from rdflib.namespace import OWL

from kg_bioportal.transformer import strip_imports

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/onto">
    <owl:imports rdf:resource="http://example.org/dead"/>
  </owl:Ontology>
</rdf:RDF>
"""

OWLXML = """<?xml version="1.0"?>
<Ontology xmlns="http://www.w3.org/2002/07/owl#" ontologyIRI="http://example.org/o">
  <Import>http://example.org/dead</Import>
  <Declaration><Class IRI="#A"/></Declaration>
</Ontology>
"""

TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/onto> a owl:Ontology ;
    owl:imports <http://example.org/dead> ;
    rdfs:label "An ontology" .
"""

OBO = """format-version: 1.2
ontology: onto
import: http://example.org/dead

[Term]
id: X:1
name: a term
"""


class StripImportsTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text, encoding="utf-8"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding=encoding) as f:
            f.write(text)
        return path


class TestStripImportsHandled(StripImportsTestCase):
    """Serializations the stripper is supposed to clean."""

    def test_rdfxml_import_is_removed(self):
        path = self.write("onto.owl", RDFXML)
        out = strip_imports(path)
        self.assertNotEqual(out, path, "should return a cleaned sibling file")
        self.assertNotIn("owl:imports", open(out).read())

    def test_rdfxml_keeps_the_rest_of_the_ontology(self):
        out = strip_imports(self.write("onto.owl", RDFXML))
        text = open(out).read()
        self.assertIn("owl:Ontology", text)
        self.assertIn("http://example.org/onto", text)

    def test_owlxml_import_element_is_removed(self):
        out = strip_imports(self.write("onto.owx", OWLXML))
        text = open(out).read()
        self.assertNotIn("<Import>", text)
        self.assertIn("<Declaration>", text)

    def test_multiline_import_element_is_removed(self):
        path = self.write("onto.owl", RDFXML.replace(
            '<owl:imports rdf:resource="http://example.org/dead"/>',
            '<owl:imports\n      rdf:resource="http://example.org/dead"/>',
        ))
        self.assertNotIn("owl:imports", open(strip_imports(path)).read())

    def test_every_import_is_removed_not_just_the_first(self):
        path = self.write("onto.owl", RDFXML.replace(
            '<owl:imports rdf:resource="http://example.org/dead"/>',
            '<owl:imports rdf:resource="http://example.org/a"/>\n'
            '    <owl:imports rdf:resource="http://example.org/b"/>\n'
            '    <owl:imports rdf:resource="http://example.org/c"/>',
        ))
        self.assertNotIn("owl:imports", open(strip_imports(path)).read())

    def test_file_without_imports_is_left_alone(self):
        path = self.write("onto.owl", RDFXML.replace(
            '<owl:imports rdf:resource="http://example.org/dead"/>', ""))
        self.assertEqual(strip_imports(path), path)

    def test_original_file_is_not_modified(self):
        path = self.write("onto.owl", RDFXML)
        strip_imports(path)
        self.assertIn("owl:imports", open(path).read())

    def test_unreadable_path_returns_the_input(self):
        missing = os.path.join(self._tmp.name, "nope.owl")
        self.assertEqual(strip_imports(missing), missing)

    def test_utf8_bom_does_not_defeat_detection(self):
        # str.lstrip() does not strip U+FEFF, so startswith("<?xml") is False --
        # but the "<rdf:rdf" substring check rescues it. Pinned because a BOM is
        # an obvious-looking culprit that turns out not to be one.
        out = strip_imports(self.write("onto.owl", "﻿" + RDFXML))
        self.assertNotIn("owl:imports", open(out).read())


class TestStripImportsTurtle(StripImportsTestCase):
    """Turtle and N3, which the stripper used to skip outright.

    Ten of the sixteen ontologies in #138 -- ARCRC, MEO, MSV, MATERIALSMINE,
    ISO19115MI, ISO19115SRS, MEDRED among them -- were lost here.
    """

    def clean(self, name, text):
        out = strip_imports(self.write(name, text))
        with open(out, encoding="utf-8") as f:
            return out, f.read()

    def assert_clean_turtle(self, text, fmt="turtle"):
        """No imports left, still parseable, and no orphaned syntax."""
        graph = Graph()
        graph.parse(data=text, format=fmt)
        self.assertEqual(
            list(graph.triples((None, OWL.imports, None))), [],
            "an owl:imports triple survived",
        )
        # rdflib accepts a subject with no predicates and a ';' left hanging
        # before the terminator; ROBOT's parser is not promised to be as
        # forgiving, so neither is allowed out of a cut. Literals are masked
        # first -- what is inside them is not syntax.
        bare = re.sub(r'"""[\s\S]*?"""|"[^"\n]*"', '""', text)
        self.assertIsNone(
            re.search(r";\s*[.\]}]", bare), "a separator was left dangling")
        self.assertIsNone(
            re.search(r"(?:^|\.)\s*(?:<[^>]*>|[\w.\-]*:[\w.\-]*)\s*\.", bare),
            "a subject was left with no predicate",
        )
        return graph

    def test_turtle_import_is_removed(self):
        out, text = self.clean("onto.ttl", TURTLE)
        self.assertTrue(out.endswith("_noimports.ttl"), out)
        self.assert_clean_turtle(text)

    def test_turtle_keeps_the_rest_of_the_ontology(self):
        graph = self.assert_clean_turtle(self.clean("onto.ttl", TURTLE)[1])
        self.assertEqual(len(graph), 2, "only the imports triple should be gone")
        self.assertIn("An ontology", self.clean("onto.ttl", TURTLE)[1])

    def test_n3_import_is_removed(self):
        # e.g. MEDRED, served as 2017-05-08.n3
        _, text = self.clean("onto.n3", TURTLE)
        self.assert_clean_turtle(text, fmt="n3")

    def test_imports_as_the_last_predicate_is_removed(self):
        # No trailing ';' to take, so the leading one has to go instead.
        _, text = self.clean("onto.ttl", TURTLE.replace(
            '    owl:imports <http://example.org/dead> ;\n    rdfs:label "An ontology" .',
            '    rdfs:label "An ontology" ;\n    owl:imports <http://example.org/dead> .',
        ))
        self.assertEqual(len(self.assert_clean_turtle(text)), 2)

    def test_imports_as_the_only_predicate_removes_the_statement(self):
        # A subject left with no predicates is a parse error, so the subject and
        # the terminating '.' go with it.
        _, text = self.clean("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> owl:imports <http://example.org/dead> .
<http://example.org/onto> a owl:Ontology .
""")
        self.assertEqual(len(self.assert_clean_turtle(text)), 1)

    def test_single_line_statement_is_removed(self):
        _, text = self.clean("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> a owl:Ontology ; owl:imports <http://example.org/dead> .
""")
        self.assertEqual(len(self.assert_clean_turtle(text)), 1)

    def test_every_object_of_a_comma_list_goes(self):
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "<http://example.org/dead>",
            "<http://example.org/a>, <http://example.org/b>, <http://example.org/c>",
        ))
        self.assert_clean_turtle(text)
        self.assertNotIn("example.org/b", text)

    def test_consecutive_imports_all_go(self):
        # Each shares a ';' with the next, so a cut can find a separator the one
        # before it already took.
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "    owl:imports <http://example.org/dead> ;\n",
            "    owl:imports <http://example.org/a> ;\n"
            "    owl:imports <http://example.org/b> ;\n"
            "    owl:imports <http://example.org/c> ;\n",
        ))
        self.assertEqual(len(self.assert_clean_turtle(text)), 2)

    def test_consecutive_imports_ending_the_statement_all_go(self):
        _, text = self.clean("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> a owl:Ontology ;
    owl:imports <http://example.org/a> ;
    owl:imports <http://example.org/b> .
""")
        self.assertEqual(len(self.assert_clean_turtle(text)), 1)

    def test_consecutive_imports_as_the_whole_statement_take_the_subject(self):
        _, text = self.clean("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> owl:imports <http://example.org/a> ;
    owl:imports <http://example.org/b> .
<http://example.org/onto> a owl:Ontology .
""")
        self.assertEqual(len(self.assert_clean_turtle(text)), 1)

    def test_several_import_statements_all_go(self):
        _, text = self.clean("onto.ttl", TURTLE + """
<http://example.org/other> a owl:Ontology ;
    owl:imports <http://example.org/dead2> .
""")
        self.assert_clean_turtle(text)

    def test_full_iri_predicate_is_recognized(self):
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "owl:imports", "<http://www.w3.org/2002/07/owl#imports>"))
        self.assert_clean_turtle(text)

    def test_owl_bound_to_another_prefix_is_recognized(self):
        # Nothing requires the OWL namespace to be bound to "owl:".
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "@prefix owl:", "@prefix o2:").replace("owl:", "o2:"))
        self.assert_clean_turtle(text)

    def test_import_inside_a_blank_node_leaves_the_node(self):
        _, text = self.clean("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/onto> rdfs:seeAlso [
    owl:imports <http://example.org/dead>
] .
""")
        self.assert_clean_turtle(text)

    def test_a_trailing_comment_does_not_confuse_the_cut(self):
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "a owl:Ontology ;", "a owl:Ontology ;  # the ontology"))
        self.assert_clean_turtle(text)

    def test_another_predicate_ending_in_imports_is_kept(self):
        _, text = self.clean("onto.ttl", TURTLE.replace(
            "@prefix rdfs:", "@prefix ex: <http://example.org/ns#> .\n@prefix rdfs:",
        ).replace("owl:imports", "ex:imports"))
        # Nothing to strip, so the file is passed through as-is.
        self.assertIn("ex:imports", text)

    def test_extensionless_source_gets_a_usable_name(self):
        # HASCO is served as "hasco", with no extension: ROBOT infers the format
        # from the filename, so the cleaned copy has to carry one.
        out, text = self.clean("hasco", TURTLE)
        self.assertTrue(out.endswith("_noimports.ttl"), out)
        self.assert_clean_turtle(text)

    def test_turtle_without_imports_is_left_alone(self):
        path = self.write("onto.ttl", TURTLE.replace(
            "    owl:imports <http://example.org/dead> ;\n", ""))
        self.assertEqual(strip_imports(path), path)


class TestStripImportsObo(StripImportsTestCase):
    """OBO, another serialization the stripper used to skip (PECO, SEP)."""

    def clean(self, text):
        out = strip_imports(self.write("onto.obo", text))
        with open(out, encoding="utf-8") as f:
            return out, f.read()

    def test_import_header_line_is_removed(self):
        out, text = self.clean(OBO)
        self.assertTrue(out.endswith("_noimports.obo"), out)
        self.assertNotIn("import:", text)

    def test_the_rest_of_the_header_survives(self):
        _, text = self.clean(OBO)
        self.assertIn("format-version: 1.2", text)
        self.assertIn("ontology: onto", text)

    def test_the_stanzas_survive(self):
        _, text = self.clean(OBO)
        self.assertIn("[Term]", text)
        self.assertIn("id: X:1", text)
        self.assertIn("name: a term", text)

    def test_every_import_line_goes(self):
        _, text = self.clean(OBO.replace(
            "import: http://example.org/dead",
            "import: http://example.org/a\nimport: http://example.org/b",
        ))
        self.assertNotIn("import:", text)

    def test_text_inside_a_stanza_is_not_touched(self):
        # "import:" is a header tag; below the first stanza it is just text.
        _, text = self.clean(OBO + 'def: "how to import: carefully" []\n')
        self.assertIn("how to import: carefully", text)

    def test_obo_without_imports_is_left_alone(self):
        path = self.write("onto.obo", OBO.replace(
            "import: http://example.org/dead\n", ""))
        self.assertEqual(strip_imports(path), path)


class TestXmlDetection(StripImportsTestCase):
    """RDF/XML that the old 400-character sniff window did not see."""

    def test_rdfxml_behind_a_doctype_block_is_handled(self):
        # A leading <!DOCTYPE ... [ ... ]> entity block with no XML declaration
        # pushes <rdf:RDF past the old window. The six .owl files in #138 --
        # BCS7, BCS8, HELIFIT, ONTOSIM, ONTOSINASC, ONTOSPM -- are all RDF/XML
        # the stripper declined despite the OWL API loading them happily.
        entities = "\n".join(
            f'  <!ENTITY ns{i} "http://example.org/ns/{i}#">' for i in range(20))
        doctype = f"<!DOCTYPE rdf:RDF [\n{entities}\n]>\n"
        self.assertGreater(len(doctype), 400, "fixture must exceed the old window")
        out = strip_imports(self.write("onto.owl", doctype + RDFXML.split("\n", 1)[1]))
        text = open(out).read()
        self.assertNotIn("owl:imports", text)
        self.assertIn("<!ENTITY ns0", text, "the entity block must survive")

    def test_import_pointing_at_an_entity_is_removed(self):
        out = strip_imports(self.write("onto.owl", RDFXML.replace(
            'rdf:resource="http://example.org/dead"', 'rdf:resource="&ns0;dead"')))
        self.assertNotIn("owl:imports", open(out).read())

    def test_owl_bound_to_another_prefix_is_recognized(self):
        # Nothing requires the OWL namespace to be bound to "owl:".
        rebound = RDFXML.replace("owl:", "o2:").replace("xmlns:owl=", "xmlns:o2=")
        out = strip_imports(self.write("onto.owl", rebound))
        self.assertNotIn(":imports", open(out).read())

    def test_leading_comment_before_the_root_is_handled(self):
        out = strip_imports(self.write("onto.owl", "<!-- a header comment -->\n" + RDFXML))
        self.assertNotIn("owl:imports", open(out).read())


class TestStripImportsDeclined(StripImportsTestCase):
    """What the stripper still passes through, and why that is the right call.

    A file it cannot rewrite safely fails the way it does today; one mangled
    into unparseable syntax would fail in a new and worse way.
    """

    def _assert_untouched(self, path):
        self.assertEqual(strip_imports(path), path)

    def test_unrecognized_serialization_is_passed_through(self):
        self._assert_untouched(self.write(
            "onto.json", '{"imports": ["http://example.org/dead"]}\n'))

    def test_owl_imports_inside_a_turtle_literal_is_kept(self):
        # Cutting here would corrupt a literal rather than remove a statement.
        path = self.write("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/onto> a owl:Ontology ;
    rdfs:comment "use owl:imports <http://example.org/dead> ." .
""")
        self._assert_untouched(path)

    def test_owl_imports_inside_a_turtle_comment_is_kept(self):
        path = self.write("onto.ttl", """@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/onto> a owl:Ontology .
# was: owl:imports <http://example.org/dead> .
""")
        self._assert_untouched(path)
