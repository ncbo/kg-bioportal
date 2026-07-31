"""Shared configuration and thresholds for KG-Bioportal.

These defaults are tuned for GitHub-hosted Action runners (~16 GB RAM, 6 h per
job). Ontologies that would blow past those limits are skipped rather than
allowed to fail the whole run; see ``KNOWN_GIANTS`` and the size / time gates.
"""

import os

# --- Skip thresholds ------------------------------------------------------- #

# Skip an ontology whose downloaded source file exceeds this many megabytes.
# Big source files mean big memory use in ROBOT and big output artifacts.
MAX_SOURCE_MB: float = float(os.environ.get("KGBP_MAX_SOURCE_MB", 100))

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
    }
)


def is_skiplisted(acronym: str) -> bool:
    """True if the ontology is on the static skiplist of known giants."""
    return acronym.strip().upper() in KNOWN_GIANTS
