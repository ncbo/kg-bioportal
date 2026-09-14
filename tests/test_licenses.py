"""The license each ontology may be reused under, in the index and on the site.

BioPortal records a license IRI on a submission (``hasLicense``) where the
submitter filled it in, which on 2026-09-14 was 157 submissions of 1,261. So
the index takes BioPortal's record first and the ontology header's
``dcterms:license`` where BioPortal has none, and says which of the two it
got. The site shows the result as a chip on the browse rows and a row on each
ontology's page, and says "not recorded" where neither source states one.
"""

import csv
import os
import tempfile
from unittest import TestCase, mock

from kg_bioportal.downloader import DOWNLOAD_REPORT_NAME, Downloader, submission_license
from kg_bioportal.transformer import (
    LICENSE_FROM_BIOPORTAL,
    LICENSE_FROM_ONTOLOGY,
    SourceInfo,
    Transformer,
    describe_source,
    license_fields,
    source_license,
)
from tests.helpers import BUILD_SITE, load_script
from tests.test_download_outcomes import FakeResponse, FakeSession

bs = load_script(BUILD_SITE, "build_site_under_test")

CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"

RDFXML = """<?xml version="1.0"?>
<!DOCTYPE rdf:RDF [ <!ENTITY cc "https://creativecommons.org/licenses/"> ]>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:terms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/agro.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/agro/2026/agro.owl"/>
    <terms:license rdf:resource="&cc;by/4.0/"/>
  </owl:Ontology>
  <owl:Class rdf:about="http://example.org/c">
    <terms:license rdf:resource="http://example.org/not-the-ontologys"/>
  </owl:Class>
</rdf:RDF>
"""

RDFXML_TEXT_LICENSE = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:dcterms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://example.org/o">
    <dcterms:license>  CC BY 4.0 </dcterms:license>
  </owl:Ontology>
</rdf:RDF>
"""

RDFXML_SELF_CLOSING = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:terms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://example.org/o"/>
  <owl:Class rdf:about="http://example.org/c">
    <terms:license rdf:resource="http://example.org/not-the-ontologys"/>
  </owl:Class>
</rdf:RDF>
"""

RDFXML_PROSE_ONLY = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/o">
    <rdfs:comment>This work is licensed under CC BY 3.0, see http://creativecommons.org/licenses/by/3.0/</rdfs:comment>
  </owl:Ontology>
</rdf:RDF>
"""

TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<http://sweetontology.net/sweetAll> a owl:Ontology ;
    dcterms:title "SWEET" ;
    dcterms:license <https://creativecommons.org/publicdomain/zero/1.0/> ;
    owl:imports <http://sweetontology.net/matr> .
"""

TURTLE_PREFIXED_OBJECT = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix terms: <http://purl.org/dc/terms/> .
@prefix cc: <https://creativecommons.org/licenses/> .
<http://example.org/o> a owl:Ontology ; terms:license cc:by/4.0/ .
"""

OBO = """format-version: 1.2
ontology: pato
property_value: http://purl.org/dc/terms/license http://creativecommons.org/licenses/by/3.0/

[Term]
id: PATO:0000001
"""

OBO_QUOTED = """format-version: 1.2
ontology: x
property_value: dcterms:license "CC-BY 4.0" xsd:string
"""


class TestSourceLicense(TestCase):
    """The header's dcterms:license, in each serialization, and nothing else."""

    def test_rdfxml_resource_with_entity(self):
        self.assertEqual(source_license(RDFXML, "xml"), CC_BY_4)

    def test_rdfxml_literal_text(self):
        self.assertEqual(source_license(RDFXML_TEXT_LICENSE, "xml"), "CC BY 4.0")

    def test_rdfxml_self_closing_header_has_none(self):
        # A term's own license annotation is not the ontology's.
        self.assertEqual(source_license(RDFXML_SELF_CLOSING, "xml"), "")

    def test_prose_in_a_comment_is_not_read(self):
        self.assertEqual(source_license(RDFXML_PROSE_ONLY, "xml"), "")

    def test_turtle_iri_object(self):
        self.assertEqual(source_license(TURTLE, "turtle"), CC0)

    def test_turtle_prefixed_object_is_expanded(self):
        self.assertEqual(source_license(TURTLE_PREFIXED_OBJECT, "turtle"), CC_BY_4)

    def test_obo_property_value(self):
        self.assertEqual(source_license(OBO, "obo"), "http://creativecommons.org/licenses/by/3.0/")

    def test_obo_quoted_literal(self):
        self.assertEqual(source_license(OBO_QUOTED, "obo"), "CC-BY 4.0")

    def test_unknown_serialization_is_empty(self):
        self.assertEqual(source_license(RDFXML, None), "")

    def test_describe_source_carries_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "agro.owl")
            with open(path, "w") as f:
                f.write(RDFXML)
            self.assertEqual(describe_source(path).license, CC_BY_4)
        self.assertEqual(SourceInfo("p").license, "")


class TestLicenseFields(TestCase):
    """BioPortal's record first, the header's as fallback, and which it was."""

    def test_bioportal_wins(self):
        self.assertEqual(
            license_fields(CC_BY_4, CC0),
            {"license": CC_BY_4, "license_from": LICENSE_FROM_BIOPORTAL},
        )

    def test_header_when_bioportal_has_none(self):
        self.assertEqual(
            license_fields("", CC0),
            {"license": CC0, "license_from": LICENSE_FROM_ONTOLOGY},
        )

    def test_neither_means_no_fields(self):
        self.assertEqual(license_fields("", ""), {})


class TestDownloaderRecordsBioportalLicense(TestCase):
    """hasLicense on the latest submission reaches the download report."""

    def run_download(self, submission):
        with tempfile.TemporaryDirectory() as tmpdir:
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            response = FakeResponse(
                headers={"Content-Disposition": 'attachment; filename="o.owl"', "Content-Length": "4"},
                chunks=[b"data"],
            )
            dl.requests_session = FakeSession(response, submission_payload=submission)
            results = dl.download(["TESTONTO"])
            with open(os.path.join(tmpdir, DOWNLOAD_REPORT_NAME), newline="") as f:
                report = list(csv.DictReader(f, delimiter="\t"))
        return results[0], report[0]

    def test_license_recorded(self):
        sub = {"submissionId": "3", "version": "1.0", "released": "2026-01-01", "hasLicense": CC_BY_4}
        result, row = self.run_download(sub)
        self.assertEqual(result["license"], CC_BY_4)
        self.assertEqual(row["license"], CC_BY_4)

    def test_no_license_is_empty(self):
        sub = {"submissionId": "3", "version": "1.0", "released": "2026-01-01", "hasLicense": None}
        result, row = self.run_download(sub)
        self.assertEqual((result["license"], row["license"]), ("", ""))

    def test_license_restricted_entry_still_carries_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            sub = {"submissionId": "3", "version": "1.0", "released": "2026-01-01",
                   "hasLicense": "http://example.org/umls-terms"}
            dl.requests_session = FakeSession(FakeResponse(status_code=403), submission_payload=sub)
            result = dl.download(["TESTONTO"])[0]
        self.assertEqual(result["reason"], "license_restricted")
        self.assertEqual(result["license"], "http://example.org/umls-terms")

    def test_downloader_asks_bioportal_for_the_license(self):
        """The default view of a submission omits hasLicense; it has to be asked for.

        The 2026-09-14 rebuild ran without this and recorded 3 BioPortal
        licenses of the 157 BioPortal holds.
        """
        from kg_bioportal.downloader import SUBMISSION_FIELDS
        asked = {}

        class Session(FakeSession):
            def get(self, url, **kwargs):
                if url.endswith("/latest_submission"):
                    asked.update(kwargs.get("params") or {})
                return super().get(url, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            dl = Downloader(output_dir=tmpdir, api_key="fake-key")
            dl.requests_session = Session(FakeResponse(status_code=403))
            dl.download(["TESTONTO"])
        self.assertIn("hasLicense", asked.get("display", "").split(","))
        self.assertIn("hasLicense", SUBMISSION_FIELDS.split(","))
        for field in ("submissionId", "version", "released"):
            self.assertIn(field, SUBMISSION_FIELDS.split(","))

    def test_submission_license_shapes(self):
        self.assertEqual(submission_license({}), "")
        self.assertEqual(submission_license({"hasLicense": None}), "")
        self.assertEqual(submission_license({"hasLicense": [CC0]}), CC0)
        self.assertEqual(submission_license({"hasLicense": "  a  b \n"}), "a b")


class TestIndexCarriesLicense(TestCase):
    """transform_all writes license/license_from, BioPortal's record first."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = os.path.join(self._tmp.name, "raw")
        self.output_dir = os.path.join(self._tmp.name, "out")
        os.makedirs(self.input_dir)
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

    def report(self, rows):
        fields = ["id", "name", "version", "license", "submission_id", "source_bytes",
                  "status", "reason", "http_status", "detail", "path"]
        with open(os.path.join(self.input_dir, DOWNLOAD_REPORT_NAME), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

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

    def test_bioportal_record_wins_over_header(self):
        self.write("AGRO", RDFXML)
        self.report([{"id": "AGRO", "status": "downloaded", "license": CC0}])
        entry = self.run_all()["AGRO"]
        self.assertEqual(entry["license"], CC0)
        self.assertEqual(entry["license_from"], "bioportal")

    def test_header_fills_in_where_bioportal_has_none(self):
        self.write("AGRO", RDFXML)
        self.report([{"id": "AGRO", "status": "downloaded", "license": ""}])
        entry = self.run_all()["AGRO"]
        self.assertEqual(entry["license"], CC_BY_4)
        self.assertEqual(entry["license_from"], "ontology")

    def test_no_report_row_still_reads_the_header(self):
        self.write("AGRO", RDFXML)
        entry = self.run_all()["AGRO"]
        self.assertEqual(entry["license_from"], "ontology")

    def test_neither_means_absent_fields(self):
        self.write("PLAIN", RDFXML_SELF_CLOSING)
        entry = self.run_all()["PLAIN"]
        self.assertNotIn("license", entry)
        self.assertNotIn("license_from", entry)

    def test_undownloaded_entry_keeps_bioportals_record(self):
        self.write("AGRO", RDFXML)
        self.report([
            {"id": "AGRO", "status": "downloaded"},
            {"id": "UMLSY", "status": "error", "reason": "license_restricted",
             "license": "http://example.org/umls-terms", "http_status": "403"},
            {"id": "BIG", "status": "skipped", "reason": "too_large"},
        ])
        entries = self.run_all()
        self.assertEqual(entries["UMLSY"]["license"], "http://example.org/umls-terms")
        self.assertEqual(entries["UMLSY"]["license_from"], "bioportal")
        self.assertNotIn("license", entries["BIG"])


def item(oid, status="OK", **kw):
    o = {"id": oid, "status": status, "reason": kw.pop("reason", ""), "name": kw.pop("name", oid)}
    o.update(kw)
    return bs.onto_to_item(o, "2026-09-14")


class TestLicenseLabel(TestCase):
    """Known IRIs get a short name; anything else is shown as itself."""

    def test_creative_commons_with_version(self):
        self.assertEqual(bs.license_label("https://creativecommons.org/licenses/by/4.0/"), "CC BY 4.0")
        self.assertEqual(bs.license_label("http://creativecommons.org/licenses/by/3.0"), "CC BY 3.0")
        self.assertEqual(bs.license_label("https://creativecommons.org/licenses/by-nc-sa/4.0/"), "CC BY-NC-SA 4.0")
        self.assertEqual(bs.license_label("https://creativecommons.org/licenses/by-sa/4.0"), "CC BY-SA 4.0")

    def test_cc0_and_others(self):
        self.assertEqual(bs.license_label("https://creativecommons.org/publicdomain/zero/1.0/"), "CC0 1.0")
        self.assertEqual(bs.license_label("http://creativecommons.org/publicdomain/zero/1.0/"), "CC0 1.0")
        self.assertEqual(bs.license_label("http://www.gnu.org/licenses/gpl-3.0"), "GPL 3.0")
        self.assertEqual(bs.license_label("https://opensource.org/licenses/MIT"), "MIT")
        self.assertEqual(bs.license_label("http://www.apache.org/licenses/LICENSE-2.0"), "Apache 2.0")
        self.assertEqual(bs.license_label("http://spdx.org/licenses/CC-BY-4.0"), "CC BY 4.0")

    def test_unknown_iri_is_shown_trimmed(self):
        self.assertEqual(bs.license_label("https://forge.etsi.org/etsi-software-license"),
                         "forge.etsi.org/etsi-software-license")

    def test_phrase_is_shown_as_written(self):
        self.assertEqual(bs.license_label("Copyright the authors"), "Copyright the authors")
        self.assertEqual(bs.license_label(""), "")
        self.assertEqual(bs.license_label(None), "")


class TestLicenseOnThePage(TestCase):
    """A chip in the browse table and a row on the page, or "not recorded"."""

    def test_page_links_the_license_and_says_where_it_came_from(self):
        it = item("AGRO", nodecount=1, edgecount=1, license=CC_BY_4, license_from="bioportal")
        html = bs.render_ontology_resource(it)
        self.assertIn(f'<a href="{CC_BY_4}"', html)
        self.assertIn("CC BY 4.0", html)
        self.assertIn("as recorded on BioPortal", html)

    def test_page_says_when_the_header_supplied_it(self):
        it = item("SWEET", nodecount=1, edgecount=1, license=CC0, license_from="ontology")
        html = bs.render_ontology_resource(it)
        self.assertIn("CC0 1.0", html)
        self.assertIn("ontology&#x27;s own header", html)

    def test_phrase_license_is_not_linked(self):
        it = item("ABD", nodecount=1, edgecount=1, license="All rights reserved", license_from="bioportal")
        html = bs.render_ontology_resource(it)
        self.assertIn("All rights reserved", html)
        self.assertNotIn('<a href="All rights reserved"', html)

    def test_page_says_not_recorded(self):
        html = bs.render_ontology_resource(item("PLAIN", nodecount=1, edgecount=1))
        self.assertIn("Not recorded", html)
        self.assertIn("neither BioPortal nor the ontology header", html)

    def test_undownloaded_page_does_not_blame_the_header(self):
        html = bs.render_ontology_resource(item("BIG", "Skipped", reason="skiplist"))
        self.assertIn("Not recorded", html)
        self.assertIn("the source was not read", html)
        self.assertNotIn("neither BioPortal nor the ontology header", html)

    def test_browse_row_carries_a_chip_and_is_searchable(self):
        items = [item("AGRO", nodecount=1, edgecount=1, license=CC_BY_4, license_from="bioportal"),
                 item("PLAIN", nodecount=1, edgecount=1)]
        html = bs.render_browse(items, 0, 2)
        self.assertEqual(html.count('class="chip sm lic"'), 1)
        self.assertIn(f'title="{CC_BY_4}">CC BY 4.0</span>', html)
        self.assertRegex(html, r'data-search="[^"]*cc by 4\.0')


class _Listing:
    """A response for the submissions listing, with a payload and no error."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestBackfill(TestCase):
    """The backfill writes BioPortal's record onto an existing index, same precedence."""

    def test_fills_missing_replaces_header_leaves_the_rest(self):
        from kg_bioportal.transformer import backfill_licenses
        entries = [
            {"id": "NEW", "status": "OK"},
            {"id": "HDR", "status": "OK", "license": CC0, "license_from": "ontology"},
            {"id": "SAME", "status": "OK", "license": CC_BY_4, "license_from": "bioportal"},
            {"id": "NONE", "status": "OK", "license": CC0, "license_from": "ontology"},
            {"id": "BARE", "status": "Skipped", "reason": "skiplist"},
        ]
        changed = backfill_licenses(entries, {"NEW": CC_BY_4, "HDR": CC_BY_4, "SAME": CC_BY_4,
                                              "ELSEWHERE": CC0})
        self.assertEqual(changed, 2)
        by_id = {e["id"]: e for e in entries}
        self.assertEqual(by_id["NEW"], {"id": "NEW", "status": "OK", "license": CC_BY_4,
                                        "license_from": "bioportal"})
        self.assertEqual(by_id["HDR"]["license_from"], "bioportal")
        self.assertEqual(by_id["NONE"]["license_from"], "ontology")
        self.assertNotIn("license", by_id["BARE"])

    def test_bioportal_licenses_reads_the_submissions_listing(self):
        from kg_bioportal.downloader import bioportal_licenses

        class Session:
            def get(self, url, **kw):
                assert url.endswith("/submissions")
                assert kw["params"]["display"].startswith("hasLicense")
                return _Listing([
                    {"ontology": {"acronym": "A"}, "hasLicense": CC_BY_4},
                    {"ontology": {"acronym": "B"}, "hasLicense": None},
                    {"ontology": {}, "hasLicense": CC0},
                ])

        self.assertEqual(bioportal_licenses("k", session=Session()), {"A": CC_BY_4})
