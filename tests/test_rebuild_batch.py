"""A rebuild-all runs as a chain of batches, cut by cursor, not by position.

Everything does not fit in one release (1,000 assets; about 1.1 per ontology),
so a rebuild-all takes the list in batches, each run dispatching the next.
The batch is cut as "the next N acronyms after the previous batch's last one",
so an ontology BioPortal adds mid-chain shifts nothing.
"""

import os
import tempfile
from unittest import TestCase

from click.testing import CliRunner

from kg_bioportal.cli import DEFAULT_BATCH_SIZE, main, rebuild_batch


class TestRebuildBatch(TestCase):
    ACR = ["PATO", "AGRO", "GO", "sweet", "OBOE", "ZFA", "AGRO"]

    def test_first_batch_is_the_head_of_the_sorted_list(self):
        b = rebuild_batch(self.ACR, "", 3)
        self.assertEqual(b, {"ontologies": "AGRO GO OBOE", "last": "OBOE", "more": True})

    def test_next_batch_follows_the_cursor(self):
        b = rebuild_batch(self.ACR, "OBOE", 3)
        self.assertEqual(b, {"ontologies": "PATO sweet ZFA", "last": "ZFA", "more": False})

    def test_an_ontology_added_mid_chain_is_not_skipped(self):
        # BioPortal adds "AAA" after the first batch ran; the cursor still
        # picks up where that batch ended, and nothing after it is missed.
        later = self.ACR + ["AAA", "OBOE-2"]
        b = rebuild_batch(later, "OBOE", 3)
        self.assertEqual(b["ontologies"], "OBOE-2 PATO sweet")
        self.assertTrue(b["more"])

    def test_cursor_at_the_end_yields_nothing(self):
        self.assertEqual(rebuild_batch(self.ACR, "ZFA", 3),
                         {"ontologies": "", "last": "", "more": False})

    def test_exact_fit_has_no_more(self):
        self.assertFalse(rebuild_batch(["A", "B", "C"], "", 3)["more"])
        self.assertEqual(DEFAULT_BATCH_SIZE, 330)


class TestRebuildBatchCommand(TestCase):
    def test_prints_github_output_lines_and_drops_the_skiplist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ontologylist.tsv")
            with open(path, "w") as f:
                f.write("id\tname\tcurrent_version\tsubmission_id\n")
                for a in ["NCBITAXON", "GO", "AGRO", "PATO"]:
                    f.write(f"{a}\tn\tv\t1\n")
            result = CliRunner().invoke(main, ["rebuild-batch", "-f", path, "--size", "2"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.splitlines(),
                         ["ontologies=AGRO GO", "last=GO", "more=true"])
