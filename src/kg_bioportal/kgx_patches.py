"""Runtime patches for KGX bugs that cost us whole ontologies.

Each patch here works around a defect in an installed dependency. They are
narrow on purpose: a patch must not change behaviour in any case that already
worked, so that applying it cannot perturb the ontologies that transform today.

Remove a patch once the upstream fix is in a release we depend on.
"""

import logging
from typing import Any, Callable, Iterable, List, Optional

# Number of times the mixed-type sort fallback has been used this process.
# Not used for control flow -- it is here so a transform can say whether an
# ontology carried mixed-type property values.
_mixed_type_sorts = 0

_patched = False


def mixed_type_sort_count() -> int:
    """How many times the mixed-type sort fallback has fired this process."""
    return _mixed_type_sorts


def _safe_sorted(
    iterable: Iterable,
    key: Optional[Callable] = None,
    reverse: bool = False,
) -> List[Any]:
    """``sorted`` that falls back to string ordering when values aren't comparable.

    A multi-valued node or edge property can hold a mix of ``str`` and typed
    literals -- rdflib hands back ``int``, ``datetime``, ``date``, ``Decimal``,
    ``Document`` -- and Python has no ordering across those. The same applies
    within a single type: two ``Document`` objects aren't orderable at all, and
    a naive and an aware ``datetime`` can't be compared to each other.

    The fallback only runs when the normal sort raises, so any list that sorts
    today sorts identically after this patch.
    """
    global _mixed_type_sorts
    try:
        return sorted(iterable, key=key, reverse=reverse)
    except TypeError:
        _mixed_type_sorts += 1
        if _mixed_type_sorts == 1:
            logging.warning(
                "Sorted a property holding values of mixed or unorderable types by "
                "their string form. Without this the ontology would fail to transform."
            )
        str_key = (lambda v: str(key(v))) if key else str
        return sorted(iterable, key=str_key, reverse=reverse)


def patch_mixed_type_sorting() -> bool:
    """Make KGX tolerate multi-valued properties with mixed value types.

    ``kgx.utils.kgx_utils._sanitize_import_property`` deduplicates a list-valued
    property and then calls bare ``sorted`` on the result. When the values are
    not mutually orderable that raises ``TypeError``, KGX aborts, and the whole
    ontology is lost -- 24 of them in the ``data-2026.07`` index, including
    FOODON, FYPO, MAXO, HANCESTRO and GSSO. See issue #135; upstream fix is a
    one-liner (``sorted(value_set, key=str)``).

    ``sorted`` is looked up in the module's globals before builtins, so binding
    the name on the module redirects it without copying any of KGX's code --
    which keeps this working across KGX versions and makes it a no-op once
    upstream fixes it.

    Returns:
        True if the patch was applied, False if it was already in place.
    """
    global _patched
    if _patched:
        return False

    from kgx.utils import kgx_utils

    kgx_utils.sorted = _safe_sorted
    _patched = True
    logging.debug("Patched kgx.utils.kgx_utils.sorted for mixed-type property values.")
    return True
