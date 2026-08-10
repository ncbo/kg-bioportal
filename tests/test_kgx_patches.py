"""Tests for the KGX runtime patches.

The mixed-type sort patch is the difference between 24 ontologies transforming
and 24 ontologies being lost (#135). Two things have to hold: it fixes the
values that crash, and it changes nothing about the values that don't -- the
latter matters because 1108 ontologies transform today and their output must not
move.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import TestCase

from kgx.utils import kgx_utils

from kg_bioportal import kgx_patches

# Importing the transformer applies the patch; do it explicitly so this module
# does not depend on import order.
kgx_patches.patch_mixed_type_sorting()

DELIM = "|"


def sanitize(values):
    """Run a multi-valued property through the KGX code path that used to crash."""
    return kgx_utils._sanitize_import_property("synonym", values, DELIM)


class TestPatchIsApplied(TestCase):
    def test_kgx_uses_the_safe_sort(self):
        self.assertIs(kgx_utils.sorted, kgx_patches._safe_sorted)

    def test_patching_twice_is_a_no_op(self):
        self.assertFalse(
            kgx_patches.patch_mixed_type_sorting(),
            "already-applied patch should report that it did nothing",
        )


class TestMixedTypesNoLongerCrash(TestCase):
    """Every type pairing observed in the failing ontologies."""

    def test_int_and_str(self):
        # CDO, DOVES, EMIF-AD, FRMO, HANCESTRO, ICEO, OAE, VALUESETS
        self.assertEqual(len(sanitize(["b", 3])), 2)

    def test_datetime_and_str(self):
        # FOVT, FYPO, MAXO, NMDCO, RBO
        self.assertEqual(len(sanitize(["b", datetime(2020, 1, 1)])), 2)

    def test_date_and_str(self):
        # KISAO
        self.assertEqual(len(sanitize(["b", date(2020, 1, 1)])), 2)

    def test_decimal_and_str(self):
        # EO, WWECA
        self.assertEqual(len(sanitize(["b", Decimal("1.5")])), 2)

    def test_naive_and_aware_datetimes(self):
        # FOODON: same type, still not comparable to each other.
        values = [datetime(2020, 1, 1), datetime(2021, 1, 1, tzinfo=timezone.utc)]
        self.assertEqual(len(sanitize(values)), 2)

    def test_values_with_no_ordering_at_all(self):
        # ONTOPSYCARE: 'Document' vs 'Document'.
        class Unorderable:
            def __init__(self, n):
                self.n = n

            def __hash__(self):
                return hash(self.n)

            def __eq__(self, other):
                return isinstance(other, Unorderable) and self.n == other.n

            def __str__(self):
                return f"doc{self.n}"

        self.assertEqual(len(sanitize([Unorderable(1), Unorderable(2)])), 2)

    def test_values_are_preserved_not_coerced(self):
        # The string form is only the sort key; the values themselves are
        # untouched, so downstream serialization behaves as it always did.
        out = sanitize(["b", 3])
        self.assertIn(3, out)
        self.assertIn("b", out)

    def test_result_is_deterministic(self):
        values = ["b", 3, datetime(2020, 1, 1), Decimal("1.5")]
        self.assertEqual(sanitize(list(values)), sanitize(list(values)))


class TestBehaviourIsOtherwiseUnchanged(TestCase):
    """Anything that sorted before must sort identically now."""

    def test_strings_sort_as_before(self):
        self.assertEqual(sanitize(["c", "a", "b"]), ["a", "b", "c"])

    def test_numbers_sort_numerically_not_as_strings(self):
        # The fallback would give [1, 10, 2]; the normal path must still win.
        self.assertEqual(sanitize([10, 2, 1]), [1, 2, 10])

    def test_duplicates_are_still_removed(self):
        self.assertEqual(sanitize(["a", "b", "a"]), ["a", "b"])

    def test_delimited_string_is_still_split(self):
        self.assertEqual(sanitize("b|a"), ["a", "b"])


class TestSafeSorted(TestCase):
    """The wrapper itself, independent of KGX."""

    def test_passes_through_key_and_reverse(self):
        self.assertEqual(
            kgx_patches._safe_sorted(["bb", "a", "ccc"], key=len, reverse=True),
            ["ccc", "bb", "a"],
        )

    def test_key_is_honoured_in_the_fallback_too(self):
        # key() returns unorderable values; the fallback must apply str to the
        # key's output, not to the raw item.
        out = kgx_patches._safe_sorted([("b", 1), ("a", None)], key=lambda t: t[1])
        self.assertEqual(len(out), 2)

    def test_counter_records_fallbacks(self):
        before = kgx_patches.mixed_type_sort_count()
        kgx_patches._safe_sorted(["a", 1])
        self.assertEqual(kgx_patches.mixed_type_sort_count(), before + 1)

    def test_counter_ignores_normal_sorts(self):
        before = kgx_patches.mixed_type_sort_count()
        kgx_patches._safe_sorted(["b", "a"])
        self.assertEqual(kgx_patches.mixed_type_sort_count(), before)
