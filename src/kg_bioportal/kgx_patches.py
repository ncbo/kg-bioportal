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
_owl_format_patched = False
_edge_id_patched = False


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


def owl_source_format(filename: str, requested: Optional[str]) -> str:
    """The rdflib format KGX should read ``filename`` with.

    ``OwlSource.parse`` maps its default format ("owl") straight to "xml", so
    KGX reads every file as RDF/XML whatever it actually is. That is fine until
    RDF/XML cannot hold the ontology: three ontologies cannot be serialized to
    it at all (#139), so their intermediate is Turtle, and KGX then tries to
    read Turtle with an XML parser.

    Resolving the format from the file name instead is a no-op for everything
    that works today -- rdflib's own ``guess_format`` maps .owl to "xml", which
    is exactly what the hardcoded value says -- and correct for the rest.

    Args:
        filename: The file KGX is about to parse.
        requested: The format KGX was asked for; "owl" or None mean "work it out".

    Returns:
        An rdflib format name.
    """
    if requested not in (None, "owl"):
        return requested  # an explicit format the caller meant; leave it alone

    import rdflib.util

    return rdflib.util.guess_format(filename) or "xml"


def patch_owl_source_format() -> bool:
    """Make KGX's OwlSource read a file in the format the file is actually in.

    Wraps ``OwlSource.parse`` rather than reimplementing it: the format is
    resolved on the way in, and everything else stays KGX's code, so the patch
    holds across KGX versions and stops mattering once upstream stops hardcoding
    the format.

    Returns:
        True if the patch was applied, False if it was already in place.
    """
    global _owl_format_patched
    if _owl_format_patched:
        return False

    try:
        from kgx.source.owl_source import OwlSource
    except ImportError as e:
        # A patch that cannot be applied has to leave the pipeline exactly as it
        # found it. Raising here would run at import of the transformer and cost
        # every ontology, to fix three.
        logging.warning(f"Could not patch KGX's OwlSource format handling: {e}")
        return False

    original_parse = OwlSource.parse

    def parse(self, filename: str, format: str = "owl", **kwargs: Any):
        return original_parse(
            self, filename, format=owl_source_format(filename, format), **kwargs
        )

    OwlSource.parse = parse
    _owl_format_patched = True
    logging.debug("Patched kgx.source.OwlSource.parse to honour the file's format.")
    return True


def edge_key(edge: dict) -> str:
    """The id KGX itself would give this edge, from its subject/predicate/object.

    Matches ``kgx.utils.kgx_utils.generate_edge_key``, which is what KGX uses
    for the edges it does assign ids to, so a filled-in id is indistinguishable
    from one KGX wrote -- rather than a second scheme sitting alongside the
    first.
    """
    return "{}-{}-{}".format(
        edge.get("subject", ""), edge.get("predicate", ""), edge.get("object", "")
    )


def patch_missing_edge_ids() -> bool:
    """Give every edge an id, not just the ones a cache flush happened to catch.

    KGX's RdfSource holds parsed edges in ``edge_cache`` and drains it in two
    places. The mid-stream drain, which fires when the cache reaches
    ``CACHE_SIZE`` (10,000), assigns an id to every edge that does not already
    have one::

        if "id" not in self.edge_cache[k] and "association_id" not in ...:
            self.edge_cache[k]["id"] = generate_edge_key(subject, predicate, object)

    The final drain at end-of-parse -- the one that yields everything left over
    -- has no such block. So an ontology's edges get ids only in whole batches
    of 10,000, and the remainder never do.

    That is exactly what the published graphs show (#71). NANDO has 14,133
    edges: the first 10,000 carry ids and the last 4,133 are blank, with the
    same mix of predicates on both sides of the boundary. FAST-EVENT-SKOS is
    60,000 of 62,123, MONDO 260,000 of 268,909. An ontology with fewer than
    10,000 edges never flushes at all, so BFO's 115 edges are blank to the last
    one -- which is the case the issue was filed about.

    (A handful of edges carry an id regardless: those dereified from an
    owl:Axiom bring their own, which is why HPIO has 3 ids among 244 edges.)

    So: fill in the id on the way past, using KGX's own scheme. This is a fix to
    a KGX bug applied from outside, like the two patches above; it stops
    mattering if upstream drains the final batch the way it drains the others.

    Returns:
        True if the patch was applied, False if it was already in place.
    """
    global _edge_id_patched
    if _edge_id_patched:
        return False

    try:
        from kgx.source.owl_source import OwlSource
    except ImportError as e:
        logging.warning(f"Could not patch KGX's edge id assignment: {e}")
        return False

    original_parse = OwlSource.parse

    def parse(self, *args: Any, **kwargs: Any):
        for record in original_parse(self, *args, **kwargs):
            # Node records are 2-tuples, edge records 4-tuples of
            # (subject, object, key, data) -- see RdfSource's drains. The
            # stream also carries a bare None after every triple that did not
            # complete a record, so this cannot assume it has a tuple at all.
            if isinstance(record, tuple) and len(record) == 4:
                edge = record[3]
                if isinstance(edge, dict) and not edge.get("id"):
                    edge["id"] = edge_key(edge)
            yield record

    OwlSource.parse = parse
    _edge_id_patched = True
    logging.debug("Patched kgx.source.OwlSource.parse to give every edge an id.")
    return True
