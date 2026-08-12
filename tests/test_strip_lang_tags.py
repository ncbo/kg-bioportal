"""Tests for invalid xml:lang removal.

rdflib raises on a language tag it doesn't recognize instead of warning, so one
bogus xml:lang attribute anywhere in a source file aborts the whole KGX parse
and loses the ontology (#140). These tests pin down what counts as bogus --
which is deliberately rdflib's rule and not the stricter BCP 47 shape, so that
ontologies building today are not perturbed.
"""

import os
import tempfile
from unittest import TestCase

from rdflib.term import Literal

from kg_bioportal.transformer import strip_invalid_lang_tags
from tests.test_transform_imports import RELAXED_WITH_IMPORTS, TransformImportsTestCase

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Class rdf:about="http://example.org/onto#A">
    <rdfs:label xml:lang="en">alpha</rdfs:label>
    <rdfs:comment xml:lang="{tag}">contact the author</rdfs:comment>
  </owl:Class>
</rdf:RDF>
"""

# The two values that actually took an ontology down, from #140.
DRMO_TAG = "gmail.com"
PEO_TAG = "mansoorsyed05/encoders-and-decoders-in-generative-ai-3a717d50fced"


class LangTagTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def clean(self, tag, name="ONTO"):
        """Sanitize a fixture carrying `tag`, returning (path, text)."""
        path = self.write("onto.owl", RDFXML.format(tag=tag))
        out = strip_invalid_lang_tags(path, name)
        with open(out, encoding="utf-8") as f:
            return out, f.read()


class TestInvalidTagsAreRemoved(LangTagTestCase):
    def test_email_domain_tag_is_removed(self):
        _, text = self.clean(DRMO_TAG)
        self.assertNotIn(DRMO_TAG, text)

    def test_article_slug_tag_is_removed(self):
        _, text = self.clean(PEO_TAG)
        self.assertNotIn(PEO_TAG, text)

    def test_the_literal_survives_without_its_tag(self):
        # The point of dropping the attribute rather than the element: the text
        # still reaches the output TSVs, minus the language it was never in.
        _, text = self.clean(DRMO_TAG)
        self.assertIn("<rdfs:comment>contact the author</rdfs:comment>", text)

    def test_valid_tags_on_other_literals_are_kept(self):
        _, text = self.clean(DRMO_TAG)
        self.assertIn('xml:lang="en"', text)

    def test_a_cleaned_sibling_is_written(self):
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG))
        out = strip_invalid_lang_tags(path, "ONTO")
        self.assertNotEqual(out, path, "should return a cleaned sibling file")
        self.assertTrue(out.endswith("_langfix.owl"), out)

    def test_the_original_file_is_not_modified(self):
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG))
        strip_invalid_lang_tags(path, "ONTO")
        with open(path, encoding="utf-8") as f:
            self.assertIn(DRMO_TAG, f.read())

    def test_every_occurrence_is_removed_not_just_the_first(self):
        body = "\n".join(
            f'    <rdfs:comment xml:lang="{DRMO_TAG}">note {i}</rdfs:comment>'
            for i in range(5)
        )
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG).replace(
            f'    <rdfs:comment xml:lang="{DRMO_TAG}">contact the author</rdfs:comment>',
            body,
        ))
        with open(strip_invalid_lang_tags(path, "ONTO"), encoding="utf-8") as f:
            self.assertNotIn("xml:lang=\"" + DRMO_TAG, f.read())

    def test_single_quoted_attributes_are_handled(self):
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG).replace(
            f'xml:lang="{DRMO_TAG}"', f"xml:lang='{DRMO_TAG}'"))
        with open(strip_invalid_lang_tags(path, "ONTO"), encoding="utf-8") as f:
            self.assertNotIn(DRMO_TAG, f.read())

    def test_owlxml_literals_are_handled_too(self):
        # ROBOT writes RDF/XML for the .owl it hands us, but the attribute is
        # spelled identically in OWL/XML and the pass is serialization-agnostic.
        path = self.write("onto.owx", (
            '<?xml version="1.0"?>\n<Ontology xmlns="http://www.w3.org/2002/07/owl#">\n'
            f'  <Literal xml:lang="{DRMO_TAG}">contact the author</Literal>\n</Ontology>\n'
        ))
        with open(strip_invalid_lang_tags(path, "ONTO"), encoding="utf-8") as f:
            self.assertNotIn(DRMO_TAG, f.read())

    def test_each_distinct_tag_is_logged_with_the_acronym(self):
        # The log is how we tell an ontology's maintainers what is wrong with
        # their file rather than silently papering over it.
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG))
        with self.assertLogs(level="WARNING") as captured:
            strip_invalid_lang_tags(path, "DRMO")
        joined = "\n".join(captured.output)
        self.assertIn("DRMO", joined)
        self.assertIn(DRMO_TAG, joined)

    def test_repeated_tags_are_logged_once_with_a_count(self):
        body = "\n".join(
            f'    <rdfs:comment xml:lang="{DRMO_TAG}">note {i}</rdfs:comment>'
            for i in range(3)
        )
        path = self.write("onto.owl", RDFXML.format(tag=DRMO_TAG).replace(
            f'    <rdfs:comment xml:lang="{DRMO_TAG}">contact the author</rdfs:comment>',
            body,
        ))
        with self.assertLogs(level="WARNING") as captured:
            strip_invalid_lang_tags(path, "DRMO")
        self.assertEqual(len(captured.output), 1, captured.output)
        self.assertIn("3 occurrence", captured.output[0])


class TestValidFilesAreUntouched(LangTagTestCase):
    """The common case: nothing to fix, so nothing is rewritten."""

    def _assert_untouched(self, tag):
        path = self.write("onto.owl", RDFXML.format(tag=tag))
        self.assertEqual(
            strip_invalid_lang_tags(path, "ONTO"), path,
            f"xml:lang={tag!r} is accepted by rdflib and must be left alone",
        )

    def test_simple_tag(self):
        self._assert_untouched("fr")

    def test_region_subtag(self):
        self._assert_untouched("en-GB")

    def test_script_and_region_subtags(self):
        self._assert_untouched("zh-Hans-CN")

    def test_overlong_subtag_rdflib_still_accepts(self):
        # Not BCP 47 -- subtags cap at eight characters -- but rdflib takes it,
        # so stripping it would perturb an ontology that builds today.
        self._assert_untouched("portuguese")

    def test_empty_tag_resets_inherited_language(self):
        # xml:lang="" is XML's way of clearing an ancestor's language, and
        # rdflib reads it as no tag. Removing it would change what descendant
        # literals are tagged with.
        self._assert_untouched("")

    def test_file_with_no_language_tags_at_all(self):
        path = self.write("onto.owl", RDFXML.format(tag="en").replace(
            ' xml:lang="en"', ""))
        self.assertEqual(strip_invalid_lang_tags(path, "ONTO"), path)

    def test_unreadable_path_returns_the_input(self):
        missing = os.path.join(self._tmp.name, "nope.owl")
        self.assertEqual(strip_invalid_lang_tags(missing, "ONTO"), missing)


class TestAgreesWithRdflib(LangTagTestCase):
    """The criterion is exactly 'would rdflib raise on this?'.

    Anything the pass keeps must construct a Literal without raising, and
    anything it drops must be a value that raises -- otherwise we either fail to
    fix an ontology or damage one that was fine.
    """

    CASES = [
        "en", "en-GB", "zh-Hans-CN", "portuguese", "x-custom", "i-klingon",
        DRMO_TAG, PEO_TAG, "en_US", "en GB", "3", "en-", "-en", "en--GB",
    ]

    def test_kept_iff_rdflib_accepts(self):
        for tag in self.CASES:
            with self.subTest(tag=tag):
                try:
                    Literal("x", lang=tag)
                except ValueError:
                    rdflib_accepts = False
                else:
                    rdflib_accepts = True

                path = self.write("onto.owl", RDFXML.format(tag=tag))
                kept = strip_invalid_lang_tags(path, "ONTO") == path
                self.assertEqual(
                    kept, rdflib_accepts,
                    f"xml:lang={tag!r}: rdflib accepts={rdflib_accepts}, kept={kept}",
                )


class TestKGXInputHasParseableLangTags(TransformImportsTestCase):
    """The sanitized file is what transform() actually hands KGX.

    Reuses the #136 harness: ROBOT and KGX are faked, and what matters is the
    content of the file KGX is pointed at.
    """

    BAD = f'    <rdfs:comment xml:lang="{DRMO_TAG}">contact the author</rdfs:comment>\n'
    RELAXED_WITH_BAD_TAG = RELAXED_WITH_IMPORTS.replace(
        "  </owl:Ontology>", f"  </owl:Ontology>\n{BAD}")

    def test_invalid_tag_is_gone_before_kgx_parses(self):
        self.run_transform(self.RELAXED_WITH_BAD_TAG)
        _, content = self.kgx_saw()
        self.assertNotIn(DRMO_TAG, content)

    def test_imports_are_still_stripped_alongside(self):
        # Both passes run, in order, on the same file.
        self.run_transform(self.RELAXED_WITH_BAD_TAG)
        _, content = self.kgx_saw()
        self.assertNotIn("owl:imports", content)
        self.assertIn("contact the author", content)

    def test_transform_still_succeeds(self):
        success, _, _ = self.run_transform(self.RELAXED_WITH_BAD_TAG)
        self.assertTrue(success)

    def test_a_clean_file_is_passed_through_untouched(self):
        # No bogus tags means no rewrite, so the ontologies that build today are
        # handed exactly the file the import strip left them.
        self.run_transform(RELAXED_WITH_IMPORTS)
        path, _ = self.kgx_saw()
        self.assertTrue(path.endswith("_noimports.owl"), path)

    def test_both_intermediates_are_cleaned_up(self):
        self.run_transform(self.RELAXED_WITH_BAD_TAG)
        workdir = os.path.join(self.output_dir, "ONTO", "1")
        leftovers = [f for f in os.listdir(workdir) if f.endswith(".owl")]
        self.assertEqual(leftovers, [], f"OWL intermediates left behind: {leftovers}")
