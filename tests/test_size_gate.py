"""The size gate is a measurement, and CCO is why it is not the whole story.

Run 12 on 2026-08-25 attempted every ontology the index held between 100 and
250 MB, with only the gate raised. Twenty of the twenty-one transformed on a
standard runner, taking 2m32s to 7m49s each and adding 3,128,595 nodes and
6,637,965 edges -- roughly two thirds again on top of the whole rest of the
index.

The twenty-first was CCO, and it did not fail: it took the runner down. ROBOT
convert and relax both finished; rdflib then parsed 15,693,276 triples, went
quiet for five minutes, and the runner was reclaimed under it. Nothing was
recorded, and the run went red. CCO is 244 MB -- inside the gate -- so the gate
cannot be what stops it. What makes it expensive is that it ships as OBO, which
is far denser per byte than the RDF/XML most sources use; the next densest
ontology in the band, GNO at 206 MB, yielded about 2.2M nodes and edges to
CCO's 15.7M triples.

So the gate rises to what was measured, and CCO joins the static skiplist,
which is exactly the list for an ontology that cannot be transformed here.
"""

from unittest import TestCase

from kg_bioportal.config import KNOWN_GIANTS, MAX_SOURCE_MB, is_skiplisted

# The band run 12 attempted, with each source size as the index recorded it.
# The largest that transformed, and the one that did not.
LARGEST_THAT_WORKED = ("GO-PLUS", 227)
THE_ONE_THAT_DID_NOT = ("CCO", 244)
# Still out of reach, and untested at any gate: the next band up.
STILL_TOO_LARGE = {"FMA": 254, "CHEBI": 258, "PMAPP-PMO": 290,
                   "EFO": 333, "UPHENO": 397, "BERO": 878}


class TestTheGateMatchesWhatWasMeasured(TestCase):
    def test_the_largest_ontology_that_transformed_is_inside_the_gate(self):
        self.assertGreaterEqual(MAX_SOURCE_MB, LARGEST_THAT_WORKED[1])

    def test_nothing_untested_is_inside_the_gate(self):
        # Raising the gate past what has been run is a guess, and the failure
        # mode is a dead runner rather than a recorded skip.
        for acronym, size_mb in STILL_TOO_LARGE.items():
            self.assertLess(MAX_SOURCE_MB, size_mb, acronym)

    def test_the_gate_is_not_lowered_below_the_previous_one(self):
        # 100 MB was the previous setting; every ontology that built under it
        # must still build.
        self.assertGreaterEqual(MAX_SOURCE_MB, 100)


class TestSizeIsNotTheOnlyWayToBeAGiant(TestCase):
    def test_cco_is_skiplisted(self):
        self.assertTrue(is_skiplisted("CCO"))

    def test_it_is_skiplisted_despite_fitting_the_gate(self):
        # The point of the entry: the gate would let it through.
        acronym, size_mb = THE_ONE_THAT_DID_NOT
        self.assertLess(size_mb, MAX_SOURCE_MB)
        self.assertTrue(is_skiplisted(acronym))

    def test_the_ontologies_that_worked_are_not_skiplisted(self):
        for acronym in ("HRA", "DINTO", "RETO", "REXO", "OGG", "OGG-MM",
                        "REGN_GO", "GEXO", "LCGFT", "VTO", "PCL", "OBA", "ZP",
                        "IOBC", "HOOM", "GNO", "RDL", "MONDO", "HGNC", "GO-PLUS"):
            self.assertFalse(is_skiplisted(acronym), acronym)

    def test_the_skiplist_still_holds_the_giants_it_held_before(self):
        for acronym in ("NCBITAXON", "SNOMEDCT", "RXNORM", "MEDDRA", "NCIT",
                        "LOINC", "GAZ", "PR", "DRON", "CPT", "ICD10", "ICD10CM",
                        "OMIM", "MESH", "UMLS", "RH-MESH"):
            self.assertIn(acronym, KNOWN_GIANTS)
