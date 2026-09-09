"""Tests for the site generator's handling of transform stats.

Covers the pure rendering functions only -- no network, no Jekyll. The point is
that a change to the stats schema (a new reason, a new count) cannot silently
stop being surfaced, and that download links come from the index rather than the
`releases/latest/download/` pattern that #147 shows to be unreliable.
"""

import re
from unittest import TestCase

from tests.helpers import BUILD_SITE, load_script

bs = load_script(BUILD_SITE, "build_site_under_test")

DATE = "2026-08-10"


def item(oid, status, reason="", **kw):
    o = {"id": oid, "status": status, "reason": reason, "name": kw.pop("name", oid)}
    o.update(kw)
    return bs.onto_to_item(o, DATE)


class TestReasonMessages(TestCase):
    """Every reason the pipeline can emit needs a human-readable explanation."""

    # Kept in step with Downloader/Transformer by hand; a reason missing here
    # renders as a generic "has not been transformed", which tells nobody why.
    REASONS = [
        "too_large", "too_slow", "skiplist", "transform_error",
        "transform_error_decompress", "transform_error_convert",
        "transform_error_relax", "transform_error_kgx", "invalid_source",
        "not_downloadable", "license_restricted", "no_download_file",
        "download_http_error", "no_submission", "metadata_http_error",
        "download_error", "import_only",
    ]
    # Reasons a full graph can be missing (full_reason in the index).
    FULL_REASONS = [
        "no_imports", "unresolvable_imports", "transform_error", "transform_error_merge",
        "transform_error_relax", "transform_error_kgx", "too_slow", "too_large",
    ]

    def test_every_known_reason_has_a_specific_message(self):
        generic = bs.reason_message("something-nobody-defined")
        for reason in self.REASONS:
            self.assertNotEqual(
                bs.reason_message(reason), generic,
                f"{reason} falls back to the generic message",
            )

    def test_unknown_reason_still_returns_a_message(self):
        self.assertTrue(bs.reason_message("brand-new-reason"))

    def test_every_full_reason_has_a_specific_message(self):
        generic = bs.full_reason_message("something-nobody-defined")
        for reason in self.FULL_REASONS:
            self.assertNotEqual(
                bs.full_reason_message(reason), generic,
                f"{reason} falls back to the generic full-graph message",
            )

    def test_unresolvable_imports_message_says_the_base_graph_stands(self):
        msg = bs.full_reason_message("unresolvable_imports").lower()
        self.assertIn("import", msg)
        self.assertIn("base graph is unaffected", msg)

    def test_license_message_says_it_is_not_a_failure(self):
        msg = bs.reason_message("license_restricted").lower()
        self.assertIn("licen", msg)
        self.assertIn("nothing to retry", msg)


class TestOntologyItems(TestCase):
    def test_ok_ontology_is_marked_ok(self):
        it = item("AGRO", "OK", nodecount=5, edgecount=6)
        self.assertTrue(it["ok"])
        self.assertEqual(it["status_label"], "OK")
        self.assertEqual(it["nodes"], 5)

    def test_failed_ontology_shows_its_reason(self):
        it = item("FYPO", "Failed", "transform_error")
        self.assertFalse(it["ok"])
        self.assertIn("transform_error", it["blurb"])

    def test_stage_specific_messages_differ_from_each_other(self):
        # Four stages that fail for four different reasons; one shared message
        # would put us back where #134 started.
        messages = {bs.reason_message(f"transform_error_{stage}")
                    for stage in ("decompress", "convert", "relax", "kgx")}
        self.assertEqual(len(messages), 4)

    def test_licensed_ontology_is_not_called_failed(self):
        it = item("NDDF", "Failed", "license_restricted")
        self.assertEqual(it["status_label"], "Licensed")
        self.assertNotIn("failed", it["blurb"].lower())

    def test_counts_are_suppressed_for_non_ok_entries(self):
        it = item("NDDF", "Failed", "license_restricted", nodecount=0, edgecount=0)
        self.assertIsNone(it["nodes"])
        self.assertIsNone(it["edges"])
        self.assertEqual(it["fmts"], [])


class TestFailureDetail(TestCase):
    """A failed ontology's page should say what actually went wrong."""

    def test_detail_is_carried_onto_the_item(self):
        it = item("FYPO", "Failed", "transform_error_kgx",
                  detail="TypeError: '<' not supported")
        self.assertIn("not supported", it["detail"])

    def test_missing_detail_is_empty_not_absent(self):
        # Entries seeded from an index written before #134 have no detail field.
        self.assertEqual(item("FYPO", "Failed", "transform_error")["detail"], "")

    def test_detail_is_rendered_on_the_resource_page(self):
        html = bs.render_ontology_resource(item(
            "FYPO", "Failed", "transform_error_kgx", detail="TypeError: bad sort"))
        self.assertIn("Detail", html)
        self.assertIn("TypeError: bad sort", html)

    def test_detail_is_escaped_not_injected(self):
        # ROBOT errors carry angle brackets and quotes straight from Java.
        html = bs.render_ontology_resource(item(
            "FYPO", "Failed", "transform_error_convert",
            detail='could not load <http://x/y> "z"'))
        self.assertNotIn("<http://x/y>", html)
        self.assertIn("&lt;http://x/y&gt;", html)

    def test_malformed_literal_counts_are_shown(self):
        html = bs.render_ontology_resource(item(
            "BDPM", "OK", nodecount=41274, edgecount=253806,
            malformed_literals=36710))
        self.assertIn("Malformed literals", html)
        self.assertIn("36,710", html)

    def test_the_literal_count_is_not_presented_as_a_failure(self):
        # The graph is fine; the values are kept as written.
        html = bs.render_ontology_resource(item(
            "BDPM", "OK", nodecount=1, edgecount=1, malformed_literals=5))
        self.assertIn("kept as written", html)

    def test_an_ontology_with_no_bad_literals_shows_no_such_row(self):
        html = bs.render_ontology_resource(item("AGRO", "OK", nodecount=5, edgecount=6))
        self.assertNotIn("Malformed literals", html)

    def test_an_ok_ontology_shows_no_detail_row(self):
        html = bs.render_ontology_resource(item("AGRO", "OK", nodecount=5, edgecount=6))
        self.assertNotIn(">Detail<", html)


class TestDownloadLinks(TestCase):
    """Download URLs must come from the index, not from `latest`."""

    INDEX_URL = "https://github.com/ncbo/kg-bioportal/releases/download/data-2026.07/ABD.tar.gz"

    def test_index_download_url_is_used_verbatim(self):
        it = item("ABD", "OK", download_url=self.INDEX_URL)
        self.assertEqual(it["download_url"], self.INDEX_URL)

    def test_index_url_is_preferred_over_the_latest_pattern(self):
        it = item("ABD", "OK", download_url=self.INDEX_URL)
        self.assertNotIn(
            "releases/latest/download", it["download_url"],
            "an entry with a download_url must not fall back to the latest release",
        )

    def test_missing_download_url_is_not_guessed(self):
        # Fixed in #147: `latest` holds only the most recent run's assets, so a
        # `releases/latest/download/<ID>.tar.gz` fallback 404s for nearly every
        # ontology. An entry with no recorded URL must offer none.
        it = item("ABD", "OK")
        self.assertEqual(it["download_url"], "")

    def test_no_rendered_page_links_at_the_latest_download_pattern(self):
        for it in (item("ABD", "OK", download_url=self.INDEX_URL),
                   item("ABD", "OK"),
                   item("NDDF", "Failed", "license_restricted")):
            page = bs.render_ontology_resource(it)
            self.assertNotIn("releases/latest/download", page)

    def test_page_without_a_url_points_at_the_releases_page(self):
        page = bs.render_ontology_resource(item("ABD", "OK"))
        self.assertIn("Artifact location not recorded", page)
        self.assertIn(bs.RELEASES_PAGE, page)

    def test_page_with_a_url_offers_the_download(self):
        page = bs.render_ontology_resource(item("ABD", "OK", download_url=self.INDEX_URL))
        self.assertIn(self.INDEX_URL, page)
        self.assertNotIn("Artifact location not recorded", page)


class TestCategoryCounts(TestCase):
    """The dashboard half of #98: what kinds of node and edge an ontology has.

    Before this, both tabs said the same thing for every ontology -- "look in
    the download". The counts are now in the index, so they can be read here.
    """

    NODE_CATS = {"biolink:NamedThing": 300000, "biolink:Disease": 22000}
    EDGE_CATS = {"biolink:Association": 268909}

    def mondo(self, **kw):
        return item("MONDO", "OK", nodecount=300000, edgecount=268909,
                    node_categories=self.NODE_CATS,
                    edge_categories=self.EDGE_CATS, **kw)

    def panel(self, html, which):
        """The Nodes or Edges tab body.

        Sliced between the panel markers rather than matched to a closing tag:
        the panels nest divs, so a non-greedy match stops inside the chart.
        """
        start = html.index(f'data-panel="{which}"')
        rest = html.index('data-panel="edges"', start + 1) if which == "nodes" else len(html)
        return html[start:rest]

    def test_the_tallies_are_carried_onto_the_item(self):
        it = self.mondo()
        self.assertEqual(it["node_categories"], self.NODE_CATS)
        self.assertEqual(it["edge_categories"], self.EDGE_CATS)

    def test_an_entry_without_them_gets_empty_dicts_not_none(self):
        # Entries seeded from a release built before the counts existed.
        it = item("BFO", "OK", nodecount=36, edgecount=115)
        self.assertEqual(it["node_categories"], {})
        self.assertEqual(it["edge_categories"], {})

    def test_node_categories_are_named_on_the_page(self):
        html = bs.render_ontology_resource(self.mondo())
        self.assertIn("Disease", self.panel(html, "nodes"))

    def test_node_category_counts_are_shown(self):
        html = bs.render_ontology_resource(self.mondo())
        self.assertIn("22,000", self.panel(html, "nodes"))

    def test_edge_categories_are_named_on_the_page(self):
        html = bs.render_ontology_resource(self.mondo())
        edges = self.panel(html, "edges")
        self.assertIn("Association", edges)
        self.assertIn("268,909", edges)

    def test_the_biggest_category_leads(self):
        html = self.panel(bs.render_ontology_resource(self.mondo()), "nodes")
        self.assertLess(html.index("NamedThing"), html.index("Disease"))

    def test_bar_widths_are_relative_to_the_biggest(self):
        html = bs.render_ontology_resource(self.mondo())
        widths = [float(w) for w in
                  re.findall(r'bar-fill node" style="width:([\d.]+)%', html)]
        self.assertEqual(widths[0], 100.0)
        self.assertTrue(all(w <= 100.0 for w in widths))

    def test_the_multi_category_caveat_is_stated(self):
        # A node counted under two categories makes the tally exceed the node
        # count; a reader who does not know that reads it as an error.
        html = bs.render_ontology_resource(self.mondo())
        self.assertIn("counted under each", self.panel(html, "nodes"))

    def test_an_ontology_without_a_tally_keeps_the_old_explanation(self):
        html = bs.render_ontology_resource(item("BFO", "OK", nodecount=36, edgecount=115))
        self.assertIn("aren't recorded in the index", self.panel(html, "nodes"))

    def test_a_failed_ontology_renders_without_one(self):
        html = bs.render_ontology_resource(item("FYPO", "Failed", "transform_error_kgx"))
        self.assertIn("aren't recorded in the index", self.panel(html, "edges"))

    def test_category_names_are_escaped(self):
        # The tally's keys come from the transform, not from a fixed list.
        # Checked on the panel, not the page: the page carries its own <script>.
        panel = self.panel(bs.render_ontology_resource(item(
            "X", "OK", nodecount=1, edgecount=1,
            node_categories={"<script>alert(1)</script>": 1})), "nodes")
        self.assertNotIn("<script>", panel)
        self.assertIn("&lt;script&gt;", panel)

    def test_the_collection_wide_tally_is_summed_over_ontologies(self):
        html = bs.render_summary(
            {"totalcount": 2, "transform_date": DATE},
            0,
            [self.mondo(), item("DOID", "OK", nodecount=10, edgecount=10,
                                node_categories={"biolink:Disease": 8000})],
        )
        self.assertIn("Node categories across the collection", html)
        self.assertIn("30,000", html)  # 22,000 + 8,000

    def test_the_collection_wide_tally_says_how_many_ontologies_it_covers(self):
        # Not every entry has one, so "2 of 3" is the difference between a
        # partial picture and a wrong one.
        html = bs.render_summary(
            {"totalcount": 3, "transform_date": DATE},
            0,
            [self.mondo(), item("DOID", "OK", nodecount=10, edgecount=10,
                                node_categories={"biolink:Disease": 8000}),
             item("BFO", "OK", nodecount=36, edgecount=115)],
        )
        head = re.search(r"Node categories across the collection.*?</p>", html, re.S).group(0)
        self.assertIn("2 of", head)
        self.assertIn("3 ontologies", head)

    def test_the_collection_wide_tally_is_omitted_when_nothing_records_one(self):
        html = bs.render_summary({"totalcount": 1}, 0,
                                 [item("BFO", "OK", nodecount=36, edgecount=115)])
        self.assertNotIn("Node categories across the collection", html)


class TestSummaryCounts(TestCase):
    TOTALS = {
        "totalcount": 1108, "skippedcount": 43, "failedcount": 133,
        "licensedcount": 8, "totalnodecount": 4318491, "totaledgecount": 8112853,
        "transform_date": DATE,
    }

    def render(self, totals, items=None):
        items = items or [item("AGRO", "OK", nodecount=5, edgecount=6)]
        return bs.render_summary(totals, 12, items)

    def keys_block(self, html):
        return re.search(r'<div class="keys">.*?</div>', html, re.S).group(0)

    def test_licensed_key_is_rendered(self):
        keys = self.keys_block(self.render(self.TOTALS))
        self.assertIn("Licensed", keys)
        self.assertIn("8", keys)

    def test_all_status_keys_are_rendered(self):
        keys = self.keys_block(self.render(self.TOTALS))
        for label in ("Transformed", "Failed", "Skipped", "Licensed"):
            self.assertIn(label, keys)

    def test_stats_without_licensedcount_still_render(self):
        # Older published stats predate the field; the page must not break or
        # show an empty key.
        totals = {k: v for k, v in self.TOTALS.items() if k != "licensedcount"}
        keys = self.keys_block(self.render(totals))
        self.assertNotIn("Licensed", keys)

    def test_zero_licensed_hides_the_key(self):
        totals = dict(self.TOTALS, licensedcount=0)
        self.assertNotIn("Licensed", self.keys_block(self.render(totals)))

    def bars(self, html):
        """Each <div class="stack"> as a list of its segment widths."""
        return [
            [float(w) for w in re.findall(r'class="seg [^"]*" style="width:([\d.]+)%', stack)]
            for stack in re.findall(r'<div class="stack">.*?</div>', html, re.S)
        ]

    def test_segment_widths_do_not_exceed_the_bar(self):
        html = self.render(self.TOTALS)
        bars = self.bars(html)
        self.assertEqual(len(bars), 2, "one bar for transform status, one for full graphs")
        for widths in bars:
            self.assertAlmostEqual(sum(widths), 100.0, delta=1.0)


class TestFullGraphItems(TestCase):
    """The full graph is a second product with its own status (#177)."""

    BASE_URL = "https://github.com/ncbo/kg-bioportal/releases/download/data-2026.09/OBOE.tar.gz"
    FULL_URL = "https://github.com/ncbo/kg-bioportal/releases/download/data-2026.09/OBOE_full.tar.gz"

    def both(self, **kw):
        return item("OBOE", "OK", nodecount=1, edgecount=0, imports=3, download_url=self.BASE_URL,
                    full_status="OK", full_nodecount=478, full_edgecount=900,
                    full_download_url=self.FULL_URL, **kw)

    def test_full_fields_are_carried(self):
        it = self.both()
        self.assertTrue(it["full_ok"])
        self.assertEqual(it["full_nodes"], 478)
        self.assertEqual(it["full_download_url"], self.FULL_URL)
        self.assertEqual(it["imports"], 3)

    def test_full_chip_only_when_a_full_graph_exists(self):
        self.assertIn("full", self.both()["fmts"])
        self.assertNotIn("full", item("AGRO", "OK", full_status="Skipped", full_reason="no_imports")["fmts"])
        self.assertNotIn("full", item("AGRO", "OK")["fmts"])

    def test_full_counts_are_suppressed_unless_full_is_ok(self):
        it = item("X", "OK", full_status="Failed", full_reason="unresolvable_imports",
                  full_nodecount=0, full_edgecount=0)
        self.assertIsNone(it["full_nodes"])
        self.assertFalse(it["full_ok"])

    def test_entry_predating_full_graphs_is_not_called_failed(self):
        it = item("OLD", "OK", nodecount=5, edgecount=6,
                  download_url="https://github.com/ncbo/kg-bioportal/releases/download/t/OLD.tar.gz")
        self.assertEqual(it["full_status"], "")
        page = bs.render_ontology_resource(it)
        self.assertIn("No full graph yet", page)
        self.assertNotIn("Full graph not built", page)


class TestImportOnlyItems(TestCase):
    def sweet(self, **kw):
        base = dict(nodecount=2, edgecount=0, imports=1,
                    download_url="https://github.com/ncbo/kg-bioportal/releases/download/t/SWEET.tar.gz")
        base.update(kw)
        return item("SWEET", "OK", "import_only", **base)

    def test_import_only_is_still_ok_but_labelled(self):
        it = self.sweet()
        self.assertTrue(it["ok"])
        self.assertTrue(it["import_only"])
        self.assertEqual(it["status_label"], "Import-only")
        self.assertNotEqual(it["status_cls"], "ok", "must not look like a healthy graph")

    def test_import_only_blurb_says_so(self):
        self.assertIn("import-only", self.sweet()["blurb"].lower())

    def test_page_carries_the_import_only_notice(self):
        page = bs.render_ontology_resource(self.sweet())
        self.assertIn("Import-only ontology", page)
        self.assertIn(bs.reason_message("import_only"), page.replace("&#x27;", "'"))

    def test_page_leads_with_the_full_graph_when_there_is_one(self):
        full = "https://github.com/ncbo/kg-bioportal/releases/download/t/SWEET_full.tar.gz"
        page = bs.render_ontology_resource(self.sweet(
            full_status="OK", full_nodecount=10240, full_edgecount=20000, full_download_url=full))
        self.assertIn(full, page)
        primary = re.search(r'<a class="btn btn-primary" href="([^"]+)"', page).group(1)
        self.assertEqual(primary, full, "the primary download must be the full graph")

    def test_ordinary_ontology_leads_with_the_base_graph(self):
        base = "https://github.com/ncbo/kg-bioportal/releases/download/t/AGRO.tar.gz"
        full = "https://github.com/ncbo/kg-bioportal/releases/download/t/AGRO_full.tar.gz"
        page = bs.render_ontology_resource(item(
            "AGRO", "OK", nodecount=5000, edgecount=8000, imports=2, download_url=base,
            full_status="OK", full_nodecount=90000, full_edgecount=150000, full_download_url=full))
        primary = re.search(r'<a class="btn btn-primary" href="([^"]+)"', page).group(1)
        self.assertEqual(primary, base)
        self.assertIn(full, page)


class TestFullGraphPages(TestCase):
    """Whatever became of the full graph, the page says so in words."""

    def page(self, **kw):
        return bs.render_ontology_resource(item(
            "X", "OK", nodecount=5, edgecount=6, imports=2,
            download_url="https://github.com/ncbo/kg-bioportal/releases/download/t/X.tar.gz", **kw))

    def test_unresolvable_imports_are_explained(self):
        page = self.page(full_status="Failed", full_reason="unresolvable_imports")
        self.assertIn("Full graph not built (unresolvable_imports)", page)
        self.assertIn("could not be fetched", page)

    def test_no_imports_is_not_presented_as_a_failure(self):
        page = self.page(full_status="Skipped", full_reason="no_imports")
        self.assertIn("Base graph is the full graph", page)
        self.assertNotIn("not built", page)

    def test_an_ontology_without_imports_speaks_of_one_graph(self):
        # The base/full distinction answers a question this ontology never
        # raises; the page keeps the one notice and otherwise says "graph".
        page = self.page(full_status="Skipped", full_reason="no_imports")
        self.assertIn("Download graph", page)
        self.assertNotIn("Download base graph", page)
        self.assertNotIn("imports stripped", page)
        self.assertNotIn("where built", page)
        self.assertIn("Graph at a glance", page)
        self.assertIn("The graph contains", page)
        self.assertIn("Same as the base graph (no imports)", page)
        self.assertIn("Base graph is the full graph", page)

    def test_an_ontology_with_imports_keeps_the_base_wording(self):
        page = self.page(full_status="Failed", full_reason="unresolvable_imports")
        self.assertIn("Download base graph", page)
        self.assertIn("Base graph at a glance", page)
        self.assertIn("imports stripped", page)

    def test_too_slow_full_graph_is_explained(self):
        page = self.page(full_status="Skipped", full_reason="too_slow")
        self.assertIn("time limit", page)

    def test_built_full_graph_is_listed_as_a_product(self):
        full = "https://github.com/ncbo/kg-bioportal/releases/download/t/X_full.tar.gz"
        page = self.page(full_status="OK", full_nodecount=70, full_edgecount=80, full_download_url=full)
        self.assertIn("X_full.tar.gz", page)
        self.assertIn("X_full_nodes.tsv", page)
        self.assertIn(full, page)

    def test_no_full_page_links_at_the_latest_download_pattern(self):
        for kw in (dict(full_status="OK", full_nodecount=1, full_edgecount=1),
                   dict(full_status="Failed", full_reason="transform_error")):
            self.assertNotIn("releases/latest/download", self.page(**kw))


class TestSummaryFullGraphs(TestCase):
    def render(self, items):
        return bs.render_summary(TestSummaryCounts.TOTALS, 3, items)

    def test_import_only_ontologies_are_listed_by_name(self):
        items = [item("SWEET", "OK", "import_only", nodecount=2, edgecount=0, imports=1),
                 item("AGRO", "OK", nodecount=5, edgecount=6)]
        html = self.render(items)
        self.assertIn("import-only", html)
        self.assertIn('href="../resource/SWEET/"', html)

    def test_full_graph_keys_are_rendered(self):
        items = [item("A", "OK", nodecount=1, edgecount=1, full_status="OK", full_nodecount=2, full_edgecount=2),
                 item("B", "OK", nodecount=1, edgecount=1, full_status="Skipped", full_reason="no_imports"),
                 item("C", "OK", nodecount=1, edgecount=1, full_status="Failed", full_reason="unresolvable_imports"),
                 item("D", "OK", nodecount=1, edgecount=1)]
        html = self.render(items)
        for label in ("Built", "Same as base", "Failed", "Not yet attempted"):
            self.assertIn(label, html)


class TestImportResolution(TestCase):
    """Each import is named, and linked as far as it can be placed (#185)."""

    def items(self):
        return [
            item("RO", "OK", nodecount=1, edgecount=1,
                 ontology_iri="http://purl.obolibrary.org/obo/ro.owl", name="Relations Ontology"),
            item("UBERON", "OK", nodecount=1, edgecount=1,
                 ontology_iri="http://purl.obolibrary.org/obo/uberon.owl", name="Uberon"),
            item("OBOE", "OK", "import_only", nodecount=1, edgecount=0,
                 ontology_iri="http://ecoinformatics.org/oboe/oboe.1.2/oboe.owl"),
            item("GONE", "Failed", "no_download_file", ontology_iri="http://example.org/gone"),
        ]

    def resolve(self, iri):
        return bs.build_import_resolver(self.items())(iri)

    def test_an_import_that_is_one_of_ours_links_to_its_page(self):
        r = self.resolve("http://purl.obolibrary.org/obo/ro.owl")
        self.assertEqual((r["kind"], r["href"]), ("kgbp", "../RO/"))
        self.assertEqual(r["name"], "Relations Ontology")

    def test_spelling_differences_still_match(self):
        for iri in ("https://purl.obolibrary.org/obo/ro.owl", "http://purl.obolibrary.org/obo/ro",
                    "http://purl.obolibrary.org/obo/RO.owl/"):
            self.assertEqual(self.resolve(iri)["kind"], "kgbp", iri)

    def test_an_obo_module_links_to_the_ontology_it_belongs_to(self):
        r = self.resolve("http://purl.obolibrary.org/obo/uberon/bridge/uberon-bridge-to-zfa.owl")
        self.assertEqual((r["kind"], r["href"]), ("module", "../UBERON/"))
        self.assertIn("bridge/uberon-bridge-to-zfa.owl", r["label"])

    def test_an_obo_purl_we_do_not_hold_is_external(self):
        r = self.resolve("http://purl.obolibrary.org/obo/nothere.owl")
        self.assertEqual((r["kind"], r["href"]), ("external", "http://purl.obolibrary.org/obo/nothere.owl"))

    def test_an_acronym_alone_never_resolves_an_obo_purl(self):
        # BioPortal's RO is the Radiomics Ontology; the Relations Ontology is
        # OBOREL. Only an ontology's own recorded IRI can claim a PURL.
        radiomics = item("RO", "OK", nodecount=1, edgecount=1, name="Radiomics Ontology")
        resolve = bs.build_import_resolver([radiomics])
        self.assertEqual(resolve("http://purl.obolibrary.org/obo/ro.owl")["kind"], "external")
        self.assertEqual(resolve("http://purl.obolibrary.org/obo/ro/imports/x.owl")["kind"], "external")

    def test_a_purl_resolves_to_whoever_calls_itself_that(self):
        oborel = item("OBOREL", "OK", nodecount=1, edgecount=1, name="Relations Ontology",
                      ontology_iri="http://purl.obolibrary.org/obo/ro.owl")
        r = bs.build_import_resolver([oborel])("http://purl.obolibrary.org/obo/ro.owl")
        self.assertEqual((r["kind"], r["href"]), ("kgbp", "../OBOREL/"))

    def test_a_web_address_is_external_and_named_by_its_path(self):
        r = self.resolve("http://sweetontology.net/human")
        self.assertEqual(r["kind"], "external")
        self.assertEqual(r["label"], "sweetontology.net/human")
        self.assertEqual(r["href"], "http://sweetontology.net/human")

    def test_a_non_web_iri_is_named_only(self):
        r = self.resolve("urn:example:thing")
        self.assertEqual((r["kind"], r["href"]), ("name", ""))
        self.assertEqual(r["label"], "urn:example:thing")

    def test_an_ontology_we_hold_but_did_not_transform_still_resolves(self):
        r = self.resolve("http://example.org/gone")
        self.assertEqual(r["kind"], "kgbp")
        self.assertFalse(r["ok"])


class TestImportsSection(TestCase):
    def page(self, iris, imports=None, items=()):
        it = item("X", "OK", nodecount=5, edgecount=6, imports=len(iris) if imports is None else imports,
                  import_iris=iris, download_url="https://github.com/ncbo/kg-bioportal/releases/download/t/X.tar.gz",
                  full_status="Failed", full_reason="unresolvable_imports")
        return bs.render_ontology_resource(it, bs.build_import_resolver(list(items) + [it]))

    def test_imports_are_listed_by_name(self):
        page = self.page(["http://sweetontology.net/human", "urn:x:y"])
        self.assertIn("sweetontology.net/human", page)
        self.assertIn('href="http://sweetontology.net/human"', page)
        self.assertIn("urn:x:y", page)

    def test_ours_link_to_our_pages_and_come_first(self):
        ro = item("RO", "OK", nodecount=1, edgecount=1, ontology_iri="http://purl.obolibrary.org/obo/ro.owl")
        page = self.page(["http://sweetontology.net/human", "http://purl.obolibrary.org/obo/ro.owl"], items=[ro])
        self.assertIn('href="../RO/"', page)
        self.assertLess(page.index('href="../RO/"'), page.index("sweetontology.net/human"))

    def test_long_lists_fold(self):
        iris = [f"http://sweetontology.net/part{i}" for i in range(30)]
        page = self.page(iris)
        self.assertIn("Show all 30 imports", page)
        self.assertIn("<details", page)

    def test_short_lists_do_not_fold(self):
        self.assertNotIn("<details", self.page(["http://e/a", "http://e/b"]))

    def test_count_without_targets_says_so(self):
        page = self.page([], imports=7)
        self.assertIn("declares 7 imports", page)
        self.assertIn("last transformed before import targets were kept", page)

    def test_no_imports_means_no_section(self):
        page = self.page([], imports=0)
        self.assertNotIn('Imports <span class="eb-count">', page)

    def test_import_iris_survive_item_normalisation(self):
        it = item("X", "OK", import_iris=["http://e/a"], ontology_iri="http://e/x")
        self.assertEqual(it["import_iris"], ["http://e/a"])
        self.assertEqual(it["ontology_iri"], "http://e/x")
