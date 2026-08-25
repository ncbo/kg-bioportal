"""Shards have to be balanced by cost, not by count.

In the 2026-08-11 run the slowest shard took 13m57s and the fastest 2m22s for
the same 30 ontologies: round-robin is not size-aware, and the heavy ontologies
happened to land together. The run took about 2.5x as long as the work in it
(#153).

That run is the fixture. RUN_2026_08_11 holds the six shards exactly as they
were reported, and the sizes sum to each shard's reported total, with the four
named heavyweights at their reported sizes -- so the packing is measured
against the case that motivated it rather than a shape invented to suit the
fix. (The individual sizes within a shard are apportioned, not measured, and
the input order that produced those shards is not recoverable from the report,
so the tests compare against the assignment that actually ran rather than
recomputing round-robin over a guessed order.)
"""

import json
import os
import tempfile
from unittest import TestCase

import yaml
from click.testing import CliRunner

from kg_bioportal.cli import (
    PER_ONTOLOGY_BYTES,
    assign_shards,
    load_index_sizes,
    main,
    transform_weights,
)

MB = 1024 * 1024

# The six shards that ran on 2026-08-11, with their reported duration and total
# source size. Sizes below sum to each shard's total; BDPM, FOODON, ICEO and RBO
# are the four the issue names individually.
RUN_SHARDS = {
    # duration, total MB, members with their MB
    "13m57s": {"BDPM": 88, "FOODON": 40, "ICEO": 37, "RBO": 29, "OCDARWN": 1},
    "4m59s-a": {"ADHER_INTCARE_EN": 2, "EMIF-AD": 8, "FYPO": 60, "NMDCO": 12, "CTX": 2},
    "4m59s-b": {"CDO": 3, "FOVT": 44, "KISAO": 5, "VALUESETS": 6, "OCRE": 2},
    "4m02s": {"DOVES": 42, "FRMO": 3, "MAXO": 15, "WWECA": 6, "ROR": 2},
    "3m08s": {"ADHER_INTCARE_SP": 2, "EO": 9, "GSSO": 17, "OAE": 4, "HGNC-NR": 2},
    "2m22s": {"AFPO": 1, "EPO": 3, "HANCESTRO": 6, "ONTOPSYCARE": 2, "ICPS": 2},
}
RUN_2026_08_11 = {a: mb for shard in RUN_SHARDS.values() for a, mb in shard.items()}
ALPHABETICAL = sorted(RUN_2026_08_11)

# The reported per-shard totals, as a check that the apportioned sizes add up.
REPORTED_TOTALS = {"13m57s": 195, "4m59s-a": 84, "4m59s-b": 60,
                   "4m02s": 68, "3m08s": 34, "2m22s": 14}


def sizes_in_bytes(mb_by_acronym):
    return {a: mb * MB for a, mb in mb_by_acronym.items()}


def spread(buckets, sizes):
    """Heaviest shard over lightest, the number that matters for wall-clock."""
    loads = [sum(sizes.get(a, 0) for a in b) for b in buckets]
    return max(loads) / max(1, min(loads))


class TestBalance(TestCase):
    def setUp(self):
        self.sizes = sizes_in_bytes(RUN_2026_08_11)

    def test_the_fixture_matches_the_reported_run(self):
        # Not a test of the fix: it holds the fixture to the numbers in the
        # report, so the improvement below is measured against something real.
        for name, members in RUN_SHARDS.items():
            self.assertEqual(sum(members.values()), REPORTED_TOTALS[name], name)

    def test_the_run_that_happened_was_badly_unbalanced(self):
        as_run = [list(members) for members in RUN_SHARDS.values()]
        self.assertGreater(spread(as_run, self.sizes), 10.0)

    def test_the_packing_is_close_to_even(self):
        buckets = assign_shards(ALPHABETICAL, 6, self.sizes)
        self.assertLess(spread(buckets, self.sizes), 1.3)

    def test_the_heavyweights_are_split_up(self):
        # BDPM, FYPO, FOVT and DOVES are the four largest; no two should share.
        buckets = assign_shards(ALPHABETICAL, 6, self.sizes)
        for bucket in buckets:
            heavy = [a for a in bucket if a in ("BDPM", "FYPO", "FOVT", "DOVES")]
            self.assertLessEqual(len(heavy), 1, f"{heavy} share a shard")

    def test_the_biggest_shard_is_near_the_ideal(self):
        buckets = assign_shards(ALPHABETICAL, 6, self.sizes)
        ideal = sum(self.sizes.values()) / 6
        heaviest = max(sum(self.sizes[a] for a in b) for b in buckets)
        # LPT's worst case is 4/3 of optimal; nothing here should approach it.
        self.assertLess(heaviest, ideal * 1.34)


class TestNothingIsLost(TestCase):
    def setUp(self):
        self.sizes = sizes_in_bytes(RUN_2026_08_11)

    def test_every_ontology_is_scheduled_exactly_once(self):
        buckets = assign_shards(ALPHABETICAL, 6, self.sizes)
        scheduled = [a for b in buckets for a in b]
        self.assertEqual(sorted(scheduled), ALPHABETICAL)
        self.assertEqual(len(scheduled), len(set(scheduled)))

    def test_no_empty_shards_are_emitted(self):
        buckets = assign_shards(["A", "B"], 6, {"A": MB, "B": MB})
        self.assertTrue(all(buckets))
        self.assertEqual(len(buckets), 2)

    def test_more_shards_than_ontologies_is_fine(self):
        buckets = assign_shards(["A"], 20, {"A": MB})
        self.assertEqual(buckets, [["A"]])

    def test_a_single_shard_holds_everything(self):
        buckets = assign_shards(ALPHABETICAL, 1, self.sizes)
        self.assertEqual(sorted(buckets[0]), ALPHABETICAL)

    def test_no_ontologies_gives_no_shards(self):
        self.assertEqual(assign_shards([], 6, {}), [])

    def test_the_assignment_is_deterministic(self):
        # The matrix has to be reproducible: same input, same shards.
        first = assign_shards(ALPHABETICAL, 6, self.sizes)
        for _ in range(3):
            self.assertEqual(assign_shards(ALPHABETICAL, 6, self.sizes), first)

    def test_input_order_does_not_change_the_packing(self):
        # Alphabetical order is exactly what made round-robin fail; the result
        # should not depend on it.
        shuffled = list(reversed(ALPHABETICAL))
        self.assertEqual(
            assign_shards(shuffled, 6, self.sizes),
            assign_shards(ALPHABETICAL, 6, self.sizes),
        )


class TestUnknownSizes(TestCase):
    def test_without_any_sizes_it_falls_back_to_round_robin(self):
        # No index, nothing to balance on: keep the behaviour that was there,
        # rather than inventing an order.
        acronyms = [f"O{i}" for i in range(10)]
        self.assertEqual(
            assign_shards(acronyms, 3, {}),
            [acronyms[0::3], acronyms[1::3], acronyms[2::3]],
        )

    def test_an_unknown_ontology_is_still_scheduled(self):
        sizes = {"BIG": 100 * MB, "SMALL": MB}
        buckets = assign_shards(["BIG", "SMALL", "NEW"], 2, sizes)
        self.assertIn("NEW", [a for b in buckets for a in b])

    def test_an_unknown_ontology_does_not_dominate(self):
        # A new submission is weighted at the median, not the maximum -- one
        # unknown should not be treated as if it were the heaviest thing here.
        sizes = sizes_in_bytes(RUN_2026_08_11)
        buckets = assign_shards(ALPHABETICAL + ["NEW"], 6, sizes)
        with_new = next(b for b in buckets if "NEW" in b)
        self.assertGreater(len(with_new), 1, "the unknown was treated as a giant")

    def test_sizes_for_ontologies_not_in_the_run_are_ignored(self):
        buckets = assign_shards(["A", "B"], 2, {"A": MB, "B": MB, "ZZZ": 500 * MB})
        self.assertEqual(sorted(a for b in buckets for a in b), ["A", "B"])


class TestIndexSizes(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write_index(self, entries):
        path = os.path.join(self._tmp.name, "onto_stats.yaml")
        with open(path, "w") as f:
            yaml.dump({"ontologies": entries}, f, sort_keys=False)
        return path

    def test_sizes_are_read_from_the_index(self):
        path = self.write_index([
            {"id": "BDPM", "source_bytes": 88 * MB, "submission_id": "3"},
            {"id": "AFPO", "source_bytes": MB, "submission_id": "1"},
        ])
        self.assertEqual(load_index_sizes(path), {"BDPM": 88 * MB, "AFPO": MB})

    def test_entries_without_a_size_are_skipped(self):
        # Skiplisted and never-downloaded entries carry 0.
        path = self.write_index([
            {"id": "GIANT", "source_bytes": 0},
            {"id": "REAL", "source_bytes": MB},
        ])
        self.assertEqual(load_index_sizes(path), {"REAL": MB})

    def test_a_junk_size_is_skipped_not_raised(self):
        path = self.write_index([
            {"id": "ODD", "source_bytes": "not a number"},
            {"id": "REAL", "source_bytes": MB},
        ])
        self.assertEqual(load_index_sizes(path), {"REAL": MB})

    def test_a_missing_index_is_empty_not_an_error(self):
        self.assertEqual(load_index_sizes(os.path.join(self._tmp.name, "nope.yaml")), {})

    def test_no_index_path_is_empty(self):
        self.assertEqual(load_index_sizes(""), {})


class TestShardListCommand(TestCase):
    """The command still emits only JSON on stdout -- it is a job output."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runner = CliRunner()

    def index(self, mb_by_acronym):
        path = os.path.join(self._tmp.name, "onto_stats.yaml")
        with open(path, "w") as f:
            yaml.dump({"ontologies": [
                {"id": a, "source_bytes": mb * MB, "submission_id": "1"}
                for a, mb in mb_by_acronym.items()
            ]}, f, sort_keys=False)
        return path

    def run_shard(self, *args):
        result = self.runner.invoke(main, ["shard-list", *args], catch_exceptions=False)
        self.assertEqual(result.exit_code, 0, result.output)
        return result

    def test_stdout_is_only_json(self):
        result = self.run_shard("--ontologies", "A B C D", "--num_shards", "2")
        self.assertEqual(len(json.loads(result.stdout.strip())), 2)

    def test_shards_are_balanced_when_an_index_is_given(self):
        index = self.index(RUN_2026_08_11)
        result = self.run_shard(
            "--ontologies", " ".join(ALPHABETICAL), "--num_shards", "6",
            "--index", index,
        )
        shards = json.loads(result.stdout.strip())
        self.assertEqual(len(shards), 6)
        sizes = sizes_in_bytes(RUN_2026_08_11)
        self.assertLess(spread([s.split() for s in shards], sizes), 1.3)

    def test_every_ontology_survives_the_command(self):
        index = self.index(RUN_2026_08_11)
        result = self.run_shard(
            "--ontologies", " ".join(ALPHABETICAL), "--num_shards", "6",
            "--index", index,
        )
        scheduled = " ".join(json.loads(result.stdout.strip())).split()
        self.assertEqual(sorted(scheduled), ALPHABETICAL)

    def test_an_explicit_list_is_never_version_skipped(self):
        # The workflow passes --index on both paths, for the sizes. Version-skip
        # must still apply only to the full list, or a targeted re-run of an
        # unchanged ontology would silently transform nothing.
        index = self.index(RUN_2026_08_11)
        result = self.run_shard(
            "--ontologies", "BDPM FOODON", "--num_shards", "2", "--index", index)
        scheduled = " ".join(json.loads(result.stdout.strip())).split()
        self.assertEqual(sorted(scheduled), ["BDPM", "FOODON"])

    def test_the_gated_count_is_reported(self):
        # The line is how a run explains its own shard sizes; a count derived
        # from the weights read 0 once the gated entries stopped weighing 0.
        index = self.index({"BERO": 878, "SMALL": 1})
        result = self.run_shard(
            "--ontologies", "BERO SMALL", "--num_shards", "2",
            "--index", index, "--max_source_mb", "100")
        self.assertIn("1 over the 100 MB gate", result.stderr)

    def test_nothing_is_gated_when_the_gate_is_high(self):
        index = self.index({"BERO": 878, "SMALL": 1})
        result = self.run_shard(
            "--ontologies", "BERO SMALL", "--num_shards", "2",
            "--index", index, "--max_source_mb", "1000")
        self.assertIn("0 over the 1000 MB gate", result.stderr)

    def test_it_works_without_an_index(self):
        result = self.run_shard("--ontologies", "A B C D E", "--num_shards", "2")
        self.assertEqual(json.loads(result.stdout.strip()), ["A C E", "B D"])


# The 2026-08-25 run, as the index and the Actions job list recorded it. Eight
# of its twenty shards did no transform work at all -- every one of them held
# nothing but ontologies already over the run's 100 MB gate, so each spent
# roughly a minute of job setup and stopped at a Content-Length check.
GATE_MB = 100

# The four the run gave a shard each, with their indexed source size.
RUN_2026_08_25_GATED = {
    "BERO": 878, "UPHENO": 397, "EFO": 332, "PMAPP-PMO": 290,
    "CHEBI": 258, "FMA": 254, "CCO": 244, "GO-PLUS": 227,
}
# The ontologies that run actually transformed, largest first. Two of them are
# most of the work; the rest are the long tail the packing has to spread.
RUN_2026_08_25_REAL = {
    "XREF-FUNDER-REG": 86, "MHCRO": 79, "GO": 35, "PHIPO": 30, "ECOCORE": 20,
    "ARO": 17, "CTCAE": 14, "ROR": 13, "JFO": 10, "VFB_DRIVERS": 10, "OBI": 9,
}
# The measured shards whose full membership the job list records, with their
# duration. UPHENO and BERO alone are the floor: a shard that does nothing
# still costs about a minute.
MEASURED = {"UPHENO": 57, "BERO": 63, "EFO": 69, "PMAPP-PMO": 56}


def gate_bytes(mb=GATE_MB):
    return mb * MB


def work_in(bucket, sizes, gate=None):
    """Source bytes a shard actually hands to ROBOT -- what sets its duration."""
    gate = gate if gate is not None else gate_bytes()
    return sum(s for a in bucket for s in [sizes.get(a, 0)] if 0 < s <= gate)


class TestTheGateIsPartOfTheCost(TestCase):
    """An ontology the run will not transform must not be weighed as if it will.

    The downloader checks Content-Length and skips without fetching, so an
    ontology over the gate costs a header check, not its size. Weighed at its
    size it buys a shard that does nothing, and on 2026-08-25 it bought four.
    """

    def setUp(self):
        self.sizes = sizes_in_bytes({**RUN_2026_08_25_GATED, **RUN_2026_08_25_REAL})
        self.acronyms = sorted(self.sizes)

    def test_the_run_that_happened_wasted_shards_on_them(self):
        # Not a test of the fix: it holds the fixture to what was measured.
        for acronym, seconds in MEASURED.items():
            self.assertLess(seconds, 75, f"{acronym} was not an idle shard")
            self.assertGreater(RUN_2026_08_25_GATED[acronym], GATE_MB)

    def test_without_the_gate_the_giants_get_their_own_shards(self):
        buckets = assign_shards(self.acronyms, 8, self.sizes)
        idle = [b for b in buckets if work_in(b, self.sizes) == 0]
        self.assertTrue(idle, "the fixture no longer reproduces the problem")

    def test_with_the_gate_no_shard_is_left_with_nothing_to_do(self):
        buckets = assign_shards(self.acronyms, 8, self.sizes, gate_bytes())
        for bucket in buckets:
            self.assertGreater(
                work_in(bucket, self.sizes), 0, f"{bucket} has no work in it")

    def test_the_gated_giants_are_spread_rather_than_isolated(self):
        buckets = assign_shards(self.acronyms, 8, self.sizes, gate_bytes())
        alone = [b for b in buckets if len(b) == 1 and b[0] in RUN_2026_08_25_GATED]
        self.assertEqual(alone, [], "a gated ontology still has a shard to itself")

    def test_the_real_work_is_spread_more_evenly(self):
        loads = lambda bs: [work_in(b, self.sizes) for b in bs]
        before = loads(assign_shards(self.acronyms, 8, self.sizes))
        after = loads(assign_shards(self.acronyms, 8, self.sizes, gate_bytes()))
        self.assertLess(max(after), max(before))

    def test_raising_the_gate_gives_them_their_weight_back(self):
        # The gate is a per-run input, not a property of the ontology: at 1000 MB
        # BERO is transformed, so it is the heaviest thing in the run again.
        buckets = assign_shards(self.acronyms, 8, self.sizes, gate_bytes(1000))
        with_bero = next(b for b in buckets if "BERO" in b)
        self.assertEqual(with_bero, ["BERO"], "BERO is 878 MB and should stand alone")

    def test_no_gate_keeps_the_previous_behaviour(self):
        self.assertEqual(
            assign_shards(self.acronyms, 8, self.sizes, 0),
            assign_shards(self.acronyms, 8, self.sizes),
        )

    def test_nothing_is_lost_to_the_gate(self):
        buckets = assign_shards(self.acronyms, 8, self.sizes, gate_bytes())
        self.assertEqual(sorted(a for b in buckets for a in b), self.acronyms)


class TestEveryOntologyCostsSomething(TestCase):
    """Size is not the whole cost: a download and two JVM starts are not free.

    In the 2026-08-25 run a shard of eight small ontologies spent ~31s on them
    and one of eleven ~120s, against ~3.4 s/MB measured elsewhere in the run --
    a floor of roughly 2 MB's worth of time each, well above the 0.46 MB median
    source. Ignoring it lets a shard of twenty tiny ontologies look empty.
    """

    def test_a_tiny_ontology_weighs_more_than_its_bytes(self):
        weights = transform_weights(["TINY"], {"TINY": 1024})
        self.assertGreater(weights["TINY"], 1024)
        self.assertGreaterEqual(weights["TINY"], PER_ONTOLOGY_BYTES)

    def test_a_gated_ontology_still_costs_its_header_check(self):
        weights = transform_weights(["BIG"], {"BIG": 878 * MB}, gate_bytes())
        self.assertEqual(weights["BIG"], float(PER_ONTOLOGY_BYTES))

    def test_a_gated_ontology_weighs_less_than_a_transformed_one(self):
        sizes = {"BIG": 878 * MB, "SMALL": MB}
        weights = transform_weights(["BIG", "SMALL"], sizes, gate_bytes())
        self.assertLess(weights["BIG"], weights["SMALL"])

    def test_many_tiny_ontologies_outweigh_one_middling_one(self):
        # The case the old model got wrong: twenty 0.1 MB ontologies are more
        # work than a single 2 MB one, because each pays the floor.
        sizes = {f"T{i}": MB // 10 for i in range(20)}
        sizes["MID"] = 2 * MB
        weights = transform_weights(list(sizes), sizes)
        self.assertGreater(sum(weights[f"T{i}"] for i in range(20)), weights["MID"])

    def test_a_pile_of_small_ontologies_outweighs_a_single_large_one(self):
        # A shard of forty 0.1 MB ontologies is not idle, and must not be given
        # a 30 MB ontology on top on the grounds that it holds "4 MB".
        sizes = {f"T{i}": MB // 10 for i in range(40)}
        sizes["BIG"] = 30 * MB
        weights = transform_weights(list(sizes), sizes)
        self.assertGreater(sum(weights[f"T{i}"] for i in range(40)), weights["BIG"])

    def test_the_gated_ones_do_not_all_land_on_one_shard(self):
        # They weigh the same as each other, so without a per-ontology cost they
        # would all follow the same lightest-shard choice.
        sizes = {f"G{i}": 500 * MB for i in range(12)}
        sizes.update({f"R{i}": (i + 1) * MB for i in range(4)})
        buckets = assign_shards(sorted(sizes), 4, sizes, gate_bytes())
        per_shard = [sum(1 for a in b if a.startswith("G")) for b in buckets]
        self.assertLess(max(per_shard), 12, "every gated ontology went to one shard")

    def test_the_weights_still_sum_over_every_ontology(self):
        sizes = {"A": MB, "B": 500 * MB}
        weights = transform_weights(["A", "B", "UNKNOWN"], sizes, gate_bytes())
        self.assertEqual(sorted(weights), ["A", "B", "UNKNOWN"])
        self.assertTrue(all(w > 0 for w in weights.values()))
