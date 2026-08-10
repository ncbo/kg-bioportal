"""Tests for owl:imports removal.

Unresolvable imports are the single largest cause of ROBOT transform failures
(see #138), and the stripper's serialization detection is where it currently
gives up silently. These tests pin down both what it handles and what it
declines, so a fix can be seen to widen the first set.
"""

import os
import tempfile
from unittest import TestCase

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
<http://example.org/onto> a owl:Ontology ;
    owl:imports <http://example.org/dead> .
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


class TestStripImportsDeclined(StripImportsTestCase):
    """Inputs the stripper currently passes through untouched.

    Each of these is a live transform failure in the published stats. When #138
    widens the stripper, the corresponding assertion here should flip from
    "returns the input unchanged" to "imports removed" — that inversion is the
    point of these tests, not a claim that the behaviour is correct.
    """

    def _assert_untouched(self, path):
        self.assertEqual(
            strip_imports(path), path,
            "known gap (#138): the stripper declined this input",
        )

    def test_turtle_is_declined(self):
        # e.g. MEO, MSV, MATERIALSMINE, ISO19115MI, ISO19115SRS, ARCRC
        self._assert_untouched(self.write("onto.ttl", TURTLE))

    def test_obo_is_declined(self):
        # e.g. PECO, SEP
        self._assert_untouched(self.write("onto.obo", "import: http://example.org/dead\n\n[Term]\nid: X:1\n"))

    def test_n3_is_declined(self):
        # e.g. MEDRED
        self._assert_untouched(self.write("onto.n3", TURTLE))

    def test_rdfxml_behind_a_doctype_block_is_declined(self):
        # A leading <!DOCTYPE ... [ ... ]> entity block with no XML declaration
        # pushes <rdf:RDF past the 400-character detection window, so none of the
        # three checks match. A candidate explanation for the six .owl files in
        # #138 (BCS7, BCS8, HELIFIT, ONTOSIM, ONTOSINASC, ONTOSPM) that the
        # stripper declined despite being RDF/XML.
        entities = "\n".join(
            f'  <!ENTITY ns{i} "http://example.org/ns/{i}#">' for i in range(20))
        doctype = f"<!DOCTYPE rdf:RDF [\n{entities}\n]>\n"
        path = self.write("onto.owl", doctype + RDFXML.split("\n", 1)[1])
        self.assertGreater(len(doctype), 400, "fixture must exceed the detection window")
        self._assert_untouched(path)
