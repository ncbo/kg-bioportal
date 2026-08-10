"""Tests for archive handling on downloaded sources.

Six ontologies are lost to this in the published stats (#137): plain gzip files
opened as tarballs, and zips with more than one member. These tests pin the
current behaviour so the fix is visible as an inversion.
"""

import gzip
import os
import tarfile
import tempfile
import zipfile
from unittest import TestCase

from kg_bioportal.transformer import Transformer

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


class TestDecompressTarGz(DecompressTestCase):
    """Single-member .tar.gz -- the case the code was written for."""

    def test_single_member_tarball_is_extracted(self):
        inner = self.path("onto.owl")
        with open(inner, "wb") as f:
            f.write(ONTOLOGY)
        archive = self.path("ONTO.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(inner, arcname="onto.owl")
        os.remove(inner)

        out = self.txr.decompress(archive, "ONTO")
        self.assertNotEqual(out, archive)
        self.assertTrue(os.path.exists(out))
        self.assertEqual(open(out, "rb").read(), ONTOLOGY)


class TestDecompressZip(DecompressTestCase):
    def _zip(self, members):
        archive = self.path("ONTO.zip")
        with zipfile.ZipFile(archive, "w") as z:
            for name in members:
                z.writestr(name, ONTOLOGY)
        return archive

    def test_single_member_zip_is_extracted(self):
        archive = self._zip(["onto.owl"])
        out = self.txr.decompress(archive, "ONTO")
        self.assertNotEqual(out, archive)
        self.assertEqual(open(out, "rb").read(), ONTOLOGY)

    def test_multi_member_zip_is_declined(self):
        # Known gap (#137): CTX (3 members), ICPS (25), OCDARWN (2), OCRE (6).
        # Returning the input unchanged is what transform() reads as failure.
        archive = self._zip(["onto.owl", "imports/other.owl"])
        self.assertEqual(
            self.txr.decompress(archive, "ONTO"), archive,
            "known gap (#137): multi-member archives are refused outright",
        )


class TestDecompressPlainGzip(DecompressTestCase):
    """A .gz that is not a tarball -- ROR and HGNC-NR in the published stats."""

    def test_plain_gzip_is_declined(self):
        archive = self.path("onto.owl.gz")
        with gzip.open(archive, "wb") as f:
            f.write(ONTOLOGY)
        # Known gap (#137): every .gz goes through tarfile.open(..., "r:gz"),
        # which needs a tar inside and raises ReadError: invalid header.
        self.assertEqual(
            self.txr.decompress(archive, "ONTO"), archive,
            "known gap (#137): plain gzip is opened as a tarball",
        )

    def test_corrupt_archive_does_not_raise(self):
        # Whatever the fix, a bad archive must be reported as a failed
        # decompression rather than escaping as an exception.
        archive = self.path("onto.owl.gz")
        with open(archive, "wb") as f:
            f.write(b"this is not gzip data at all")
        self.assertEqual(self.txr.decompress(archive, "ONTO"), archive)
