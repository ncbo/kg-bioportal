"""Shared configuration and thresholds for KG-Bioportal.

These defaults are tuned for GitHub-hosted Action runners (~16 GB RAM, 6 h per
job). Ontologies that would blow past those limits are skipped rather than
allowed to fail the whole run; see ``KNOWN_GIANTS`` and the size / time gates.
"""

import os

# --- Skip thresholds ------------------------------------------------------- #

# Skip an ontology whose downloaded source file exceeds this many megabytes.
# Big source files mean big memory use in ROBOT and big output artifacts.
#
# Measured, not guessed: on 2026-08-25 all 21 ontologies the index held between
# 100 and 250 MB were transformed on a standard runner, from HRA at 100 MB to
# GO-PLUS at 227 MB, in 2m32s to 7m49s each. The one that did not survive was
# CCO at 244 MB, and it is on the skiplist below rather than being a reason to
# hold the gate down -- see KNOWN_GIANTS for why size is not what stopped it.
MAX_SOURCE_MB: float = float(os.environ.get("KGBP_MAX_SOURCE_MB", 250))

# Hard wall-clock cap for transforming a single ontology, in minutes. If a
# transform runs longer it is killed and recorded as skipped (too_slow), so one
# pathological ontology can't consume the whole job's time budget.
PER_ONTOLOGY_TIMEOUT_MIN: float = float(os.environ.get("KGBP_TIMEOUT_MIN", 30))

# --- Sharding -------------------------------------------------------------- #

# Number of parallel shards the ontology list is split into for the matrix
# build. GitHub Actions allows up to 20 concurrent jobs on the free tier.
DEFAULT_NUM_SHARDS: int = int(os.environ.get("KGBP_NUM_SHARDS", 20))

# --- ROBOT ----------------------------------------------------------------- #

# Java args for ROBOT. Overridable via the ROBOT_JAVA_ARGS environment variable
# so CI can dial the heap to the runner (leave headroom below 16 GB).
ROBOT_JAVA_ARGS: str = os.environ.get("ROBOT_JAVA_ARGS", "-Xmx12g -XX:+UseG1GC")

# --- Static skiplist ------------------------------------------------------- #

# Ontologies known to be too large / slow to transform on a GitHub Action.
# These are skipped up front (no download attempt) as a fast path; the dynamic
# size and time gates are the safety net for anything not listed here.
# BioPortal acronyms. Adjust as capacity changes.
KNOWN_GIANTS: frozenset = frozenset(
    {
        "NCBITAXON",   # NCBI organismal taxonomy — millions of classes
        "SNOMEDCT",    # SNOMED CT
        "RXNORM",      # RxNorm
        "MEDDRA",      # MedDRA
        "NCIT",        # NCI Thesaurus
        "LOINC",       # LOINC
        "GAZ",         # Gazetteer — very large
        "PR",          # Protein Ontology
        "DRON",        # Drug ontology (large, ingest-derived)
        "CPT",         # Current Procedural Terminology
        "ICD10",       # ICD-10
        "ICD10CM",     # ICD-10-CM
        "OMIM",        # OMIM
        "MESH",        # Medical Subject Headings
        "UMLS",        # UMLS-derived
        "RH-MESH",     # MeSH (Robert Hoehndorf variant)
        # Not a giant by file size -- 244 MB, inside the gate -- but by what
        # that file expands to. CCO ships as OBO, which is far denser per byte
        # than the RDF/XML most sources use, and it parsed to 15,693,276
        # triples: an order of magnitude more than anything else in its size
        # band (GNO, 206 MB, is the next densest at ~2.2M nodes+edges). ROBOT
        # convert and relax both finished; rdflib held the graph, went quiet
        # for five minutes, and the runner was reclaimed under it, so the
        # ontology was never recorded as anything and the whole run went red.
        # Measured 2026-08-25 (run 12).
        "CCO",         # Cell Cycle Ontology — 15.7M triples from 244 MB of OBO
    }
)


def is_skiplisted(acronym: str) -> bool:
    """True if the ontology is on the static skiplist of known giants."""
    return acronym.strip().upper() in KNOWN_GIANTS


# --- Base and full graphs -------------------------------------------------- #

# Every ontology is transformed twice, after the OBO Foundry's distinction:
#   base  = the ontology alone, its owl:imports stripped (what KG-Bioportal has
#           always published), released as <ACRONYM>.tar.gz;
#   full  = the ontology with its import closure merged in by ROBOT, released
#           beside it as <ACRONYM><FULL_SUFFIX>.tar.gz.
# Base graphs merge cleanly (nothing is counted twice); full graphs are
# self-contained. Which one a reader wants depends on what they know about the
# ontology's imports, so the index records both.
FULL_SUFFIX: str = "_full"

# Recorded on an OK base graph that is nothing but the ontology's header: the
# source declares imports and every class lives behind them (SWEET, OBOE). The
# artifact is honest, and it is also useless; the full graph is the one to use.
IMPORT_ONLY_REASON: str = "import_only"

# A header-only base graph still carries a few nodes: KGX makes one of the
# ontology IRI itself and one of each IRI-valued header annotation (a license,
# a creator). No edges and at most this many nodes, from a source that declares
# imports, reads as import-only.
IMPORT_ONLY_MAX_NODES: int = int(os.environ.get("KGBP_IMPORT_ONLY_MAX_NODES", 10))

# Why a full graph was not built.
NO_IMPORTS_REASON: str = "no_imports"  # nothing to merge: the base graph is the full graph
UNRESOLVABLE_IMPORTS_REASON: str = "unresolvable_imports"  # an import could not be fetched

# Reasons that mean "not attempted, or cut off by a gate" rather than "broken".
# An entry with one of these is Skipped; any other non-OK reason is Failed.
SKIP_REASONS: frozenset = frozenset({"too_slow", "too_large", NO_IMPORTS_REASON})

# --- Download outcomes ----------------------------------------------------- #

# Recorded when BioPortal declines to serve the source file because the
# ontology is under a license we don't hold (UMLS-derived terminologies and
# friends). This is not a failure of the pipeline: there is nothing to fix and
# nothing to retry, so it is counted separately from the ontologies that broke.
LICENSE_RESTRICTED_REASON: str = "license_restricted"

# HTTP statuses on the download endpoint that mean "you may not have this file"
# rather than "this file does not exist". 401 is included because a request
# without sufficient credentials is the same situation from our side.
LICENSE_STATUSES: frozenset = frozenset({401, 403})
