"""Status vocabulary and site-wide totals for the ontology index.

Kept free of heavy imports on purpose: ``.github/scripts/merge_stats.py`` loads
this module by path, the way it loads ``config.py``, so the totals it writes on
a release and the totals the transformer writes per shard come from one
function instead of two copies that drift.
"""

from typing import Iterable, Union

from kg_bioportal.config import (
    IMPORT_ONLY_REASON,
    LICENSE_RESTRICTED_REASON,
    SKIP_REASONS,
)


def status_for(ok: bool, reason: str) -> str:
    """The status word an entry gets for an outcome: OK, Skipped, or Failed.

    A deliberate skip (a gate tripped, nothing to build) is not an error;
    saying so in the index keeps the two apart when reading a run afterwards.
    """
    if ok:
        return "OK"
    return "Skipped" if reason in SKIP_REASONS else "Failed"


def summarize(entries: Union[Iterable[dict], dict]) -> dict:
    """Roll per-ontology index entries up into the fields of total_stats.yaml.

    ``status``/``reason`` and the counts describe the base graph, as they always
    have; ``full_*`` describe the full graph and are absent from entries that
    never reached the transform or predate full graphs.

    License-restricted ontologies get their own count and are *excluded* from
    ``failedcount``. They keep ``status: Failed`` in onto_stats (no artifact
    exists for them either way), but nothing about them is broken and no rerun
    will change that, so counting them as failures overstates how much of the
    pipeline needs fixing.

    Import-only ontologies stay inside ``totalcount``: their base artifact
    exists and downloads. ``importonlycount`` says how many of those base graphs
    are empty shells whose content lives in the full graph.

    Args:
        entries: The index entries, as dicts, or {acronym: entry}.

    Returns:
        Ordered mapping of total_stats.yaml field name to value.
    """
    # The transformer keeps its log as {acronym: entry}; the index is a list.
    entries = list(entries.values() if isinstance(entries, dict) else entries)

    def by_status(status, key="status"):
        return sum(1 for e in entries if e.get(key) == status)

    licensed = sum(1 for e in entries if e.get("reason") == LICENSE_RESTRICTED_REASON)
    import_only = sum(
        1 for e in entries
        if e.get("status") == "OK" and e.get("reason") == IMPORT_ONLY_REASON
    )
    return {
        "totalcount": by_status("OK"),
        "skippedcount": by_status("Skipped"),
        "failedcount": by_status("Failed") - licensed,
        "licensedcount": licensed,
        "importonlycount": import_only,
        "fullcount": by_status("OK", "full_status"),
        "fullskippedcount": by_status("Skipped", "full_status"),
        "fullfailedcount": by_status("Failed", "full_status"),
        "totalnodecount": sum(e.get("nodecount") or 0 for e in entries),
        "totaledgecount": sum(e.get("edgecount") or 0 for e in entries),
    }
