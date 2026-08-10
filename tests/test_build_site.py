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
        "not_downloadable", "license_restricted", "no_download_file",
        "download_http_error", "no_submission", "metadata_http_error",
        "download_error",
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

    def test_licensed_ontology_is_not_called_failed(self):
        it = item("NDDF", "Failed", "license_restricted")
        self.assertEqual(it["status_label"], "Licensed")
        self.assertNotIn("failed", it["blurb"].lower())

    def test_counts_are_suppressed_for_non_ok_entries(self):
        it = item("NDDF", "Failed", "license_restricted", nodecount=0, edgecount=0)
        self.assertIsNone(it["nodes"])
        self.assertIsNone(it["edges"])
        self.assertEqual(it["fmts"], [])


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

    def test_segment_widths_do_not_exceed_the_bar(self):
        html = self.render(self.TOTALS)
        widths = [float(w) for w in re.findall(r'class="seg [^"]*" style="width:([\d.]+)%', html)]
        self.assertAlmostEqual(sum(widths), 100.0, delta=1.0)
