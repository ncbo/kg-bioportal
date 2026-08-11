"""Tests for archive handling on downloaded sources.

Six ontologies were lost to this in the published stats (#137): plain gzip files
opened as tarballs, and zips with more than one member refused outright.
"""

import gzip
import os
import tarfile
import tempfile
import zipfile
from unittest import TestCase

from kg_bioportal.transformer import SourceTooLarge, Transformer, pick_ontology_member

ONTOLOGY = b'<?xml version="1.0"?>\n<rdf:RDF/>\n'


def make_transformer(input_dir):
    """A Transformer without __init__.

    Transformer.__init__ downloads and initialises ROBOT, which decompression
    does not need. decompress() only reads self.input_dir.
    """
    txr = Transformer.__new__(Transformer)
    txr.input_dir = input_dir
    return txr


class DecompressTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input_dir = self._tmp.name
        self.txr = make_transformer(self.input_dir)

    def path(self, name):
        return os.path.join(self.input_dir, name)

    def make_zip(self, members, name="ONTO.zip"):
        """members: {archive path: bytes}."""
        archive = self.path(name)
        with zipfile.ZipFile(archive, "w") as z:
            for member, data in members.items():
                z.writestr(member, data)
        return archive

    def make_targz(self, members, name="ONTO.tar.gz"):
        archive = self.path(name)
        staging = os.path.join(self.input_dir, "_staging")
        os.makedirs(staging, exist_ok=True)
        with tarfile.open(archive, "w:gz") as tar:
            for member, data in members.items():
                staged = os.path.join(staging, os.path.basename(member))
                with open(staged, "wb") as f:
                    f.write(data)
                tar.add(staged, arcname=member)
        return archive

    def make_gzip(self, name="onto.owl.gz", data=ONTOLOGY):
        archive = self.path(name)
        with gzip.open(archive, "wb") as f:
            f.write(data)
        return archive

    def assert_extracted(self, out, archive, expected=ONTOLOGY):
        self.assertNotEqual(out, archive, "should return the extracted file, not the archive")
        self.assertTrue(os.path.exists(out), f"{out} does not exist")
        self.assertEqual(open(out, "rb").read(), expected)


class TestTarGz(DecompressTestCase):
    def test_single_member_tarball_is_extracted(self):
        archive = self.make_targz({"onto.owl": ONTOLOGY})
        self.assert_extracted(self.txr.decompress(archive, "ONTO"), archive)

    def test_tarball_is_detected_by_content_not_extension(self):
        # BioPortal names sources inconsistently; a tarball called .gz is common.
        archive = self.make_targz({"onto.owl": ONTOLOGY}, name="ONTO.gz")
        self.assert_extracted(self.txr.decompress(archive, "ONTO"), archive)

    def test_multi_member_tarball_picks_the_ontology(self):
        archive = self.make_targz({"README.txt": b"hi", "onto.owl": ONTOLOGY})
        self.assert_extracted(self.txr.decompress(archive, "ONTO"), archive)


class TestZip(DecompressTestCase):
    def test_single_member_zip_is_extracted(self):
        archive = self.make_zip({"onto.owl": ONTOLOGY})
        self.assert_extracted(self.txr.decompress(archive, "ONTO"), archive)

    def test_multi_member_zip_is_no_longer_refused(self):
        # Fixed in #137: CTX (3 members), ICPS (25), OCDARWN (2), OCRE (6) were
        # all lost because the code insisted on exactly one member.
        archive = self.make_zip({"onto.owl": ONTOLOGY, "imports/other.owl": b"<rdf:RDF/>"})
        out = self.txr.decompress(archive, "ONTO")
        self.assertNotEqual(out, archive)
        self.assertTrue(out.endswith("onto.owl"))

    def test_member_named_after_the_acronym_wins(self):
        archive = self.make_zip({
            "imports/big-import.owl": b"x" * 5000,   # larger, but not the subject
            "OCRe.owl": ONTOLOGY,
        })
        out = self.txr.decompress(archive, "OCRE")
        self.assertTrue(out.endswith("OCRe.owl"), out)

    def test_member_named_after_the_archive_wins(self):
        # ICPS: PatientSafetyIncident.zip ships a 340 kB Countries.owl next to
        # the 126 kB PatientSafetyIncident.owl that is actually the ontology.
        archive = self.make_zip({
            "Countries.owl": b"x" * 5000,
            "PatientSafetyIncident.owl": ONTOLOGY,
        }, name="PatientSafetyIncident.zip")
        out = self.txr.decompress(archive, "ICPS")
        self.assertTrue(out.endswith("PatientSafetyIncident.owl"), out)

    def test_macos_metadata_is_ignored(self):
        archive = self.make_zip({
            "__MACOSX/._onto.owl": b"junk" * 500,
            "onto.owl": ONTOLOGY,
        })
        out = self.txr.decompress(archive, "ONTO")
        self.assert_extracted(out, archive)

    def test_empty_archive_is_a_failure(self):
        archive = self.make_zip({})
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)


class TestPlainGzip(DecompressTestCase):
    """A .gz that is not a tarball — ROR and HGNC-NR in the published stats."""

    def test_plain_gzip_is_decompressed(self):
        # Fixed in #137: every .gz used to go through tarfile.open(..., "r:gz"),
        # which needs a tar inside and raised ReadError: invalid header.
        archive = self.make_gzip()
        out = self.txr.decompress(archive, "ONTO")
        self.assert_extracted(out, archive)

    def test_gz_suffix_is_stripped_from_the_output_name(self):
        out = self.txr.decompress(self.make_gzip(name="ror.owl.gz"), "ROR")
        self.assertTrue(out.endswith("ror.owl"), out)

    def test_extensionless_gzip_still_produces_a_file(self):
        out = self.txr.decompress(self.make_gzip(name="ONTO.gz"), "ONTO")
        self.assert_extracted(out, self.path("ONTO.gz"))


class TestBadArchives(DecompressTestCase):
    """A broken archive is one ontology's failure, never the run's."""

    def test_corrupt_gzip_does_not_raise(self):
        archive = self.path("onto.owl.gz")
        with open(archive, "wb") as f:
            f.write(b"this is not gzip data at all")
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)

    def test_corrupt_zip_does_not_raise(self):
        archive = self.path("onto.zip")
        with open(archive, "wb") as f:
            f.write(b"PK\x03\x04 and then nonsense")
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)

    def test_truncated_gzip_does_not_raise(self):
        archive = self.make_gzip(data=ONTOLOGY * 100)
        with open(archive, "r+b") as f:
            f.truncate(20)
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)

    def test_unrecognised_extension_is_a_failure(self):
        archive = self.path("onto.owl")
        with open(archive, "wb") as f:
            f.write(ONTOLOGY)
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)


class TestPickOntologyMember(TestCase):
    """Selection rules, independent of any real archive."""

    def test_single_member_is_chosen(self):
        self.assertEqual(pick_ontology_member([("a.owl", 10)], "ONTO"), "a.owl")

    def test_acronym_match_beats_size(self):
        members = [("huge.owl", 10_000), ("OCRe.owl", 10)]
        self.assertEqual(pick_ontology_member(members, "OCRE"), "OCRe.owl")

    def test_acronym_match_is_case_insensitive(self):
        self.assertEqual(
            pick_ontology_member([("x.owl", 99), ("ctx.ttl", 1)], "CTX"), "ctx.ttl"
        )

    def test_largest_ontology_file_otherwise(self):
        members = [("small.owl", 10), ("big.ttl", 900), ("readme.txt", 100_000)]
        self.assertEqual(pick_ontology_member(members, "ONTO"), "big.ttl")

    def test_falls_back_to_largest_file_when_no_extension_matches(self):
        members = [("notes", 10), ("source", 900)]
        self.assertEqual(pick_ontology_member(members, "ONTO"), "source")

    def test_junk_is_skipped(self):
        members = [("__MACOSX/._onto.owl", 9999), ("onto.owl", 10)]
        self.assertEqual(pick_ontology_member(members, "ONTO"), "onto.owl")

    def test_no_members_returns_none(self):
        self.assertIsNone(pick_ontology_member([], "ONTO"))

    def test_only_junk_returns_none(self):
        self.assertIsNone(pick_ontology_member([("__MACOSX/._x", 5)], "ONTO"))

    def test_choice_is_deterministic_on_ties(self):
        members = [("b.owl", 100), ("a.owl", 100)]
        self.assertEqual(pick_ontology_member(members, "ONTO"), "a.owl")

    def test_archive_name_beats_acronym_and_size(self):
        members = [("Countries.owl", 340_000), ("PatientSafetyIncident.owl", 126_000)]
        self.assertEqual(
            pick_ontology_member(members, "ICPS", "data/raw/ICPS/7/PatientSafetyIncident.zip"),
            "PatientSafetyIncident.owl",
        )

    def test_archive_name_rule_handles_tar_gz(self):
        members = [("other.owl", 900), ("onto.owl", 10)]
        self.assertEqual(
            pick_ontology_member(members, "X", "/tmp/onto.tar.gz"), "onto.owl"
        )

    def test_acronym_still_wins_when_archive_name_matches_nothing(self):
        members = [("big.owl", 900), ("OCRe.owl", 10)]
        self.assertEqual(
            pick_ontology_member(members, "OCRE", "/tmp/submission-23.zip"), "OCRe.owl"
        )


class TestDecompressedSizeGate(DecompressTestCase):
    """The downloader's gate weighs the compressed file, which understates it.

    ROR is 14 MB gzipped and 141 MB unpacked; HGNC-NR 7.8 MB and 170 MB. Both
    are past the limit that keeps the runner alive, and neither was visible
    until #137 made them decompress at all.
    """

    def setUp(self):
        super().setUp()
        self.txr.max_source_mb = 1
        self.txr.max_source_bytes = 1024 * 1024
        # transform() reaches the gate before it needs ROBOT, but it does name
        # an output directory on the way there.
        self.txr.output_dir = os.path.join(self.input_dir, "_out")

    def transform_archive(self, archive):
        """Drive transform() far enough to hit the gate, without ROBOT."""
        return self.txr.transform(archive, compress=False)

    def test_oversized_unpacked_source_raises(self):
        archive = self.make_gzip(name="big.owl.gz", data=b"<rdf:RDF/>" + b"x" * (2 * 1024 * 1024))
        os.makedirs(os.path.join(self.input_dir, "BIG", "1"), exist_ok=True)
        moved = os.path.join(self.input_dir, "BIG", "1", "big.owl.gz")
        os.replace(archive, moved)
        with self.assertRaises(SourceTooLarge):
            self.transform_archive(moved)

    def test_gate_is_not_applied_below_the_limit(self):
        # Under the limit it must get past the gate; it then fails in ROBOT,
        # which is not what this test is about -- only that SourceTooLarge
        # is not what stopped it.
        archive = self.make_gzip(name="small.owl.gz")
        os.makedirs(os.path.join(self.input_dir, "SMALL", "1"), exist_ok=True)
        moved = os.path.join(self.input_dir, "SMALL", "1", "small.owl.gz")
        os.replace(archive, moved)
        try:
            self.transform_archive(moved)
        except SourceTooLarge:
            self.fail("a source under the limit must not trip the size gate")
        except Exception:
            pass  # ROBOT isn't set up here; anything else is fine

    def test_gate_can_be_disabled(self):
        self.txr.max_source_bytes = 0
        archive = self.make_gzip(name="big.owl.gz", data=b"x" * (2 * 1024 * 1024))
        os.makedirs(os.path.join(self.input_dir, "BIG", "1"), exist_ok=True)
        moved = os.path.join(self.input_dir, "BIG", "1", "big.owl.gz")
        os.replace(archive, moved)
        try:
            self.transform_archive(moved)
        except SourceTooLarge:
            self.fail("max_source_bytes=0 must disable the gate")
        except Exception:
            pass
