"""Tests for the cross-release index built by .github/scripts/merge_stats.py.

Releases are incremental: each run holds only the ontologies it transformed, so
the index is the only thing that knows where any given artifact actually lives.
The invariants here are what keep 1100+ graphs reachable after a run that
transforms two of them -- see #147, where the `releases/latest/download/` URL
pattern breaks precisely because it does not consult the index.
"""

import os
import subprocess
import sys
import tempfile
from unittest import TestCase

import yaml

from tests.helpers import MERGE_STATS

PREV_TAG = "data-2026.07"
THIS_TAG = "data-2026.08"


def entry(oid, status="OK", reason="", **kw):
    e = {
        "id": oid, "status": status, "reason": reason, "name": oid, "version": "1",
        "nodecount": 10 if status == "OK" else 0,
        "edgecount": 20 if status == "OK" else 0,
        "submission_id": "1", "source_bytes": 100,
    }
    e.update(kw)
    return e


def asset(tag, oid):
    return f"https://github.com/ncbo/kg-bioportal/releases/download/{tag}/{oid}.tar.gz"


class MergeStatsTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.fragments = os.path.join(self.root, "fragments")
        self.out = os.path.join(self.root, "out")
        os.makedirs(os.path.join(self.fragments, "shard-1"))

    def write_base(self, entries):
        path = os.path.join(self.root, "base.yaml")
        with open(path, "w") as f:
            yaml.dump({"ontologies": entries}, f, sort_keys=False)
        return path

    def write_fragment(self, entries, shard="shard-1"):
        d = os.path.join(self.fragments, shard)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "onto_stats.yaml"), "w") as f:
            yaml.dump({"ontologies": entries}, f, sort_keys=False)

    def run_merge(self, base_path="", tag=THIS_TAG, date="2026-08-01"):
        result = subprocess.run(
            [sys.executable, MERGE_STATS, self.fragments, self.out, date, base_path, tag],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.out, "onto_stats.yaml")) as f:
            index = {o["id"]: o for o in yaml.safe_load(f)["ontologies"]}
        with open(os.path.join(self.out, "total_stats.yaml")) as f:
            totals = yaml.safe_load(f)
        return index, totals

    def read_manifest(self):
        """graph_urls.tsv as {id: url}, asserting the header is intact."""
        with open(os.path.join(self.out, "graph_urls.tsv")) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "id\tdownload_url")
        return dict(line.split("\t") for line in lines[1:])


class TestDownloadUrlInvariants(MergeStatsTestCase):
    """Where each artifact lives must survive a run that didn't rebuild it.

    This is the property that stops a targeted re-run -- which publishes a
    release holding few or no .tar.gz assets -- from orphaning every graph.
    """

    def test_carried_forward_entry_keeps_its_original_release(self):
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("FRESH")])
        index, _ = self.run_merge(base)
        self.assertEqual(index["OLD"]["download_url"], asset(PREV_TAG, "OLD"))

    def test_entry_transformed_in_this_run_points_at_this_release(self):
        self.write_fragment([entry("FRESH")])
        index, _ = self.run_merge()
        self.assertEqual(index["FRESH"]["download_url"], asset(THIS_TAG, "FRESH"))

    def test_a_run_that_transforms_nothing_orphans_no_artifact(self):
        # The #143 refresh: 44 undownloadable ontologies, zero .tar.gz assets.
        # Every previously-OK entry must still say where its artifact is.
        base = self.write_base([
            entry(oid, download_url=asset(PREV_TAG, oid)) for oid in ("A", "B", "C")
        ])
        self.write_fragment([entry("NDDF", status="Failed", reason="license_restricted")])
        index, _ = self.run_merge(base)
        for oid in ("A", "B", "C"):
            self.assertEqual(index[oid]["download_url"], asset(PREV_TAG, oid))

    def test_every_ok_entry_has_a_download_url(self):
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("FRESH")])
        index, _ = self.run_merge(base)
        for oid, o in index.items():
            if o["status"] == "OK":
                self.assertTrue(o.get("download_url"), f"{oid} is OK with no download_url")

    def test_non_ok_entries_carry_no_download_url(self):
        self.write_fragment([entry("BAD", status="Failed", reason="transform_error")])
        index, _ = self.run_merge()
        self.assertNotIn("download_url", index["BAD"])

    def test_an_entry_that_stops_transforming_loses_its_stale_url(self):
        base = self.write_base([entry("WAS_OK", download_url=asset(PREV_TAG, "WAS_OK"))])
        self.write_fragment([entry("WAS_OK", status="Failed", reason="transform_error")])
        index, _ = self.run_merge(base)
        self.assertNotIn(
            "download_url", index["WAS_OK"],
            "a now-failing ontology must not keep pointing at an old artifact",
        )


class TestGraphUrlsManifest(MergeStatsTestCase):
    """The shell-readable resolver published alongside the index (#147).

    `releases/latest/download/<ACRONYM>.tar.gz` cannot work -- no single release
    holds every artifact -- so `latest/download/graph_urls.tsv` is the stable
    entry point that replaces it.
    """

    def test_manifest_covers_every_resolvable_graph(self):
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("FRESH")])
        index, _ = self.run_merge(base)
        manifest = self.read_manifest()
        expected = {oid for oid, o in index.items()
                    if o["status"] == "OK" and o.get("download_url")}
        self.assertEqual(set(manifest), expected)

    def test_manifest_urls_match_the_index(self):
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("FRESH")])
        index, _ = self.run_merge(base)
        for oid, url in self.read_manifest().items():
            self.assertEqual(url, index[oid]["download_url"])

    def test_manifest_spans_releases(self):
        # The whole point: one file resolving artifacts that live in different
        # releases, which is what makes a single stable URL impossible.
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("FRESH")])
        self.run_merge(base)
        manifest = self.read_manifest()
        self.assertEqual(manifest["OLD"], asset(PREV_TAG, "OLD"))
        self.assertEqual(manifest["FRESH"], asset(THIS_TAG, "FRESH"))

    def test_manifest_excludes_non_ok_entries(self):
        self.write_fragment([
            entry("GOOD"),
            entry("BAD", status="Failed", reason="transform_error"),
            entry("LIC", status="Failed", reason="license_restricted"),
            entry("BIG", status="Skipped", reason="too_large"),
        ])
        self.run_merge()
        self.assertEqual(set(self.read_manifest()), {"GOOD"})

    def test_manifest_never_uses_the_latest_download_pattern(self):
        self.write_fragment([entry("FRESH")])
        self.run_merge()
        with open(os.path.join(self.out, "graph_urls.tsv")) as f:
            self.assertNotIn("releases/latest/download", f.read())

    def test_manifest_is_written_even_when_nothing_transformed(self):
        # A run over undownloadable ontologies produces no artifacts, but the
        # manifest must still be published or `latest` loses the resolver.
        base = self.write_base([entry("OLD", download_url=asset(PREV_TAG, "OLD"))])
        self.write_fragment([entry("NDDF", status="Failed", reason="license_restricted")])
        self.run_merge(base)
        self.assertEqual(self.read_manifest(), {"OLD": asset(PREV_TAG, "OLD")})


class TestSeedAndOverlay(MergeStatsTestCase):
    """A targeted re-run updates its own entries and leaves the rest alone."""

    def test_base_entries_are_preserved(self):
        base = self.write_base([entry("KEEP", download_url=asset(PREV_TAG, "KEEP"))])
        self.write_fragment([entry("NEW")])
        index, _ = self.run_merge(base)
        self.assertIn("KEEP", index)
        self.assertIn("NEW", index)

    def test_fragments_win_over_the_base(self):
        base = self.write_base([entry("X", status="Failed", reason="not_downloadable")])
        self.write_fragment([entry("X", status="Failed", reason="license_restricted",
                                   http_status=403)])
        index, _ = self.run_merge(base)
        self.assertEqual(index["X"]["reason"], "license_restricted")
        self.assertEqual(index["X"]["http_status"], 403)

    def test_multiple_shards_are_all_merged(self):
        self.write_fragment([entry("A")], shard="shard-1")
        self.write_fragment([entry("B")], shard="shard-2")
        index, _ = self.run_merge()
        self.assertIn("A", index)
        self.assertIn("B", index)

    def test_skiplisted_giants_are_always_represented(self):
        # They are dropped before sharding, so no fragment reports them.
        self.write_fragment([entry("A")])
        index, _ = self.run_merge()
        self.assertEqual(index["NCBITAXON"]["reason"], "skiplist")
        self.assertEqual(index["NCBITAXON"]["status"], "Skipped")

    def test_entries_are_sorted_by_id(self):
        self.write_fragment([entry("ZZZ"), entry("AAA")])
        index, _ = self.run_merge()
        self.assertEqual(list(index), sorted(index))


class TestTotals(MergeStatsTestCase):
    def setUp(self):
        super().setUp()
        self.write_fragment([
            entry("OK1"), entry("OK2"),
            entry("SKIP", status="Skipped", reason="too_large"),
            entry("FAIL", status="Failed", reason="transform_error"),
            entry("LIC1", status="Failed", reason="license_restricted"),
            entry("LIC2", status="Failed", reason="license_restricted"),
        ])

    def test_licensed_counted_apart_from_failed(self):
        _, totals = self.run_merge()
        self.assertEqual(totals["licensedcount"], 2)
        self.assertEqual(totals["failedcount"], 1)

    def test_skiplisted_giants_are_included_in_skippedcount(self):
        _, totals = self.run_merge()
        # 1 too_large fragment entry + the static skiplist.
        self.assertGreater(totals["skippedcount"], 1)

    def test_node_and_edge_totals(self):
        _, totals = self.run_merge()
        self.assertEqual(totals["totalnodecount"], 20)
        self.assertEqual(totals["totaledgecount"], 40)

    def test_transform_date_is_recorded(self):
        _, totals = self.run_merge(date="2026-08-10")
        self.assertEqual(str(totals["transform_date"]), "2026-08-10")
