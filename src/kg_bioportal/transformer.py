"""Transformer for KG-Bioportal."""

import csv
import gzip
import logging
import os
import re
import shutil
import signal
import sys
import tarfile
import zipfile
from contextlib import contextmanager
from typing import Dict, List, NamedTuple, Optional, Tuple

import yaml
from kgx.transformer import Transformer as KGXTransformer

from kg_bioportal.config import (
    LICENSE_RESTRICTED_REASON,
    MAX_SOURCE_MB,
    PER_ONTOLOGY_TIMEOUT_MIN,
)
from kg_bioportal.categories import categorize
from kg_bioportal.downloader import DOWNLOAD_REPORT_NAME, ONTOLOGY_LIST_NAME
from kg_bioportal.kgx_patches import (
    patch_missing_edge_categories,
    patch_missing_edge_ids,
    patch_mixed_type_sorting,
    patch_owl_source_format,
)
from kg_bioportal.robot_utils import initialize_robot, robot_convert, robot_relax

# Applied at import so it is in place for any use of the KGX transform, not just
# the ones that go through Transformer. See kgx_patches for what and why.
patch_mixed_type_sorting()
patch_owl_source_format()
patch_missing_edge_ids()
patch_missing_edge_categories()

# TODO: Don't repeat steps if the products already exist
# TODO: Fix KGX hijacking logging
# TODO: Save KGX logs to a file for each ontology
# TODO: Address BNodes
# TODO: Assign IDs to edges when they lack them

# Files in the input dir that are not ontologies to transform.
_NON_ONTOLOGY_FILES = {ONTOLOGY_LIST_NAME, DOWNLOAD_REPORT_NAME}

_OWL_NS = "http://www.w3.org/2002/07/owl#"

# How much of a file we read to decide which serialization it is. The old
# 400-character window fell inside the <!DOCTYPE rdf:RDF [ ... ]> entity block
# some RDF/XML sources open with, so <rdf:RDF never came into view and the file
# was written off as "not XML we handle" (#138).
_SNIFF_CHARS = 65536

# xmlns bindings of the OWL namespace, so an ontology that binds it to anything
# other than the conventional "owl:" is still recognized.
_XMLNS_OWL = re.compile(
    r"""xmlns:([A-Za-z_][\w.\-]*)\s*=\s*(["'])%s\2""" % re.escape(_OWL_NS)
)

# @prefix / PREFIX bindings of the OWL namespace in Turtle and N3. The prefix
# label is optional: ":imports" is legal when the default prefix is owl.
_TTL_PREFIX_OWL = re.compile(
    r"^[ \t]*@?prefix[ \t]+([A-Za-z_][\w.\-]*)?:[ \t]*<%s>" % re.escape(_OWL_NS),
    re.I | re.M,
)

# Turtle/N3 terms an owl:imports object can be: an IRI or a prefixed name.
_TTL_IRI = re.compile(r"""<[^<>"{}|^`\\\s]*>""")
_TTL_PNAME = re.compile(r"(?:[A-Za-z_][\w.\-]*)?:[\w.\-%]*")
_TTL_NAME_CHAR = re.compile(r"[\w:.\-%]")

# OBO header line: "import: http://purl.obolibrary.org/obo/po.owl".
_OBO_IMPORT_LINE = re.compile(r"^import:[ \t][^\n]*\n?", re.M)
_OBO_STANZA = re.compile(r"^\[", re.M)

# Extension for the cleaned copy when the source has none -- BioPortal serves
# extensionless sources (HASCO), and ROBOT infers the format from the name.
_EXT_FOR_KIND = {"xml": ".owl", "turtle": ".ttl", "obo": ".obo"}


def _sniff_serialization(text: str) -> Optional[str]:
    """Which serialization a source is written in, as far as imports go.

    Extension is not consulted: BioPortal serves ``.owl`` files holding Turtle
    and files with no extension at all. Returns "xml" (RDF/XML or OWL/XML),
    "turtle" (Turtle or N3), "obo", or None when nothing is recognized.
    """
    head = text[:_SNIFF_CHARS].lstrip("\ufeff").lstrip()
    lowered = head.lower()
    if (
        lowered.startswith(("<?xml", "<!doctype", "<!--"))
        or "<rdf:rdf" in lowered
        or "<owl:ontology" in lowered
        or "<ontology" in lowered
    ):
        return "xml"
    # The tags want their trailing space: "ontology:Thing" at the start of a
    # Turtle line is a prefixed name, not an OBO header.
    if re.search(r"^(?:format-version:[ \t]|ontology:[ \t]|\[term\]|\[typedef\])", lowered, re.M):
        return "obo"
    if re.search(r"^[ \t]*(?:@prefix\b|@base\b|prefix\b|base\b)", lowered, re.M) or re.search(
        r"^[ \t]*<[^<>\s]*>[ \t]", head, re.M
    ):
        return "turtle"
    return None


def _xml_import_patterns(text: str) -> List["re.Pattern"]:
    """Import declarations to remove from an XML serialization.

    Covers RDF/XML (``<owl:imports .../>``, or with a nested resource) and
    OWL/XML (``<Import>IRI</Import>``), under every prefix the file binds to the
    OWL namespace.
    """
    prefixes = {m.group(1) for m in _XMLNS_OWL.finditer(text)}
    prefixes.add("owl")
    alt = "|".join(re.escape(p) for p in sorted(prefixes))
    return [
        re.compile(r"[ \t]*<(?:%s):imports\b[^>]*/>[ \t]*\n?" % alt),
        re.compile(
            r"[ \t]*<(?:%s):imports\b[^>]*>.*?</(?:%s):imports>[ \t]*\n?" % (alt, alt),
            re.S,
        ),
        re.compile(
            r"[ \t]*<(?:(?:%s):)?Import\b[^>]*>.*?</(?:(?:%s):)?Import>[ \t]*\n?"
            % (alt, alt),
            re.S,
        ),
        re.compile(r"[ \t]*<(?:(?:%s):)?Import\b[^>]*/>[ \t]*\n?" % alt),
    ]


def _strip_xml_imports(text: str) -> Tuple[str, int]:
    """Remove import declarations from RDF/XML or OWL/XML."""
    removed = 0
    for pattern in _xml_import_patterns(text):
        text, n = pattern.subn("", text)
        removed += n
    return text, removed


def _line_start(text: str, i: int) -> int:
    return text.rfind("\n", 0, i) + 1


def _line_scan(text: str, start: int, end: int) -> Tuple[Optional[int], bool]:
    """Walk a fragment of one line, tracking Turtle quoting.

    Returns the index where a comment begins (a ``#`` that is not inside an IRI
    or a literal), or None, and whether ``end`` lands inside an unclosed literal
    or IRI. Literals that span lines are not tracked -- a triple-quoted string
    containing something that reads like an imports statement would fool this,
    which is why a caller that cannot tell leaves the file alone.
    """
    i, quote, in_iri = start, "", False
    while i < end:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = ""
                continue
        elif in_iri:
            if c == ">":
                in_iri = False
        elif c == "<":
            in_iri = True
        elif c in "\"'":
            quote = c * 3 if text.startswith(c * 3, i) else c
            i += len(quote)
            continue
        elif c == "#":
            return i, False
        i += 1
    return None, bool(quote) or in_iri


def _skip_ws(text: str, i: int) -> int:
    """Advance past whitespace and comments."""
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text[i] == "#":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
        else:
            break
    return i


def _prev_significant(text: str, i: int, hole: Tuple[int, int] = (0, 0)) -> int:
    """Index of the last character before i that is not whitespace or comment.

    ``hole`` is a span of text that has already been cut, and is stepped over as
    if it were not there: what precedes an imports statement, once the one before
    it has been removed, is whatever preceded them both.
    """
    while i > 0:
        i -= 1
        if hole[0] <= i < hole[1]:
            i = hole[0]
            continue
        if text[i].isspace():
            continue
        comment_at, _ = _line_scan(text, _line_start(text, i), i + 1)
        if comment_at is not None:
            i = comment_at  # i sat inside a trailing comment; carry on before it
            continue
        return i
    return -1


def _term_end(text: str, i: int) -> Optional[int]:
    """End of the Turtle term starting at i, or None if there isn't one."""
    match = _TTL_IRI.match(text, i) or _TTL_PNAME.match(text, i)
    if not match:
        return None
    end = match.end()
    # A prefixed name cannot end in '.', so a trailing one is the statement's.
    while end > i and text[end - 1] == ".":
        end -= 1
    return end if end > i else None


def _object_list_end(text: str, i: int) -> Optional[Tuple[int, int]]:
    """End of the (possibly comma-separated) object list, and of the whitespace after it."""
    while True:
        i = _skip_ws(text, i)
        end = _term_end(text, i)
        if end is None:
            return None
        after = _skip_ws(text, end)
        if after < len(text) and text[after] == ",":
            i = after + 1
            continue
        return end, after


def _subject_start(text: str, end: int) -> Optional[int]:
    """Start of the subject term whose last character is at index end."""
    if text[end] == ">":
        start = text.rfind("<", 0, end)
        return start if start != -1 else None
    if not _TTL_NAME_CHAR.match(text[end]):
        return None  # e.g. ']' closing a blank node property list -- don't guess
    start = end
    while start > 0 and _TTL_NAME_CHAR.match(text[start - 1]):
        start -= 1
    return start


def _turtle_import_span(
    text: str, match: "re.Match", hole: Tuple[int, int] = (0, 0)
) -> Optional[Tuple[int, int]]:
    """The span to cut for one Turtle/N3 imports statement, or None if unclear.

    Removing the predicate and its objects is not enough on its own: what has to
    go with them depends on where the statement sits.

    * ``owl:Ontology ; owl:imports <x> ; rdfs:label "y" .`` -- take the trailing
      ``;`` with it, leaving the rest of the predicate list intact.
    * ``owl:Ontology ; owl:imports <x> .`` -- there is no trailing ``;``, so take
      the leading one instead.
    * ``<onto> owl:imports <x> .`` -- imports is the whole statement; the subject
      and the final ``.`` go too, since a subject with no predicate is a parse
      error.

    Anything that doesn't fit one of those shapes is left alone. A file that
    still has an import in it fails the way it does today; a file mangled into
    unparseable Turtle would fail in a new and worse way.

    ``hole`` is the span the previous cut removed, which this one has to see
    through: consecutive imports separated by ';' would otherwise each find a
    separator that is already gone and leave the other one dangling.
    """
    line_start = _line_start(text, match.start())
    comment_at, in_literal = _line_scan(text, line_start, match.start())
    if comment_at is not None or in_literal:
        return None  # this "owl:imports" is text in a comment or a literal

    objects = _object_list_end(text, match.end())
    if objects is None:
        return None
    obj_end, after = objects
    terminator = text[after] if after < len(text) else ""
    prev = _prev_significant(text, match.start(), hole)
    prev_char = text[prev] if prev >= 0 else ""

    if terminator == ";":
        return match.start(), after + 1
    if terminator not in (".", "]", "}", ""):
        return None
    if prev_char == ";":
        return prev, obj_end
    if prev_char in ("[", "{", ""):
        return match.start(), obj_end
    if terminator != ".":
        return None
    subject = _subject_start(text, prev)
    if subject is None:
        return None
    return subject, after + 1


def _tidy(text: str, start: int, end: int) -> Tuple[int, int]:
    """Widen a cut to the whole line when nothing else is on it."""
    line_start = _line_start(text, start)
    newline = text.find("\n", end)
    line_end = len(text) if newline == -1 else newline + 1
    if not text[line_start:start].strip() and not text[end:line_end].strip():
        return line_start, line_end
    return start, end


def _strip_turtle_imports(text: str) -> Tuple[str, int]:
    """Remove owl:imports statements from Turtle or N3.

    Text-level rather than a parse-and-reserialize: rdflib would have to hold the
    whole graph in memory for a source of up to MAX_SOURCE_MB, and its output
    would replace a file that is otherwise fine with a round-tripped one. Cutting
    the statement leaves every other byte where it was.
    """
    prefixes = {m.group(1) or "" for m in _TTL_PREFIX_OWL.finditer(text)}
    prefixes.add("owl")
    alt = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))
    predicate = re.compile(
        r"<%s>|(?<![\w:.\-])(?:%s):imports(?![\w.\-])"
        % (re.escape(_OWL_NS + "imports"), alt)
    )

    out: List[str] = []
    pos = removed = declined = 0
    chunk_start = 0  # source index the last chunk in `out` was copied from
    cut_start = 0  # where the previous cut began
    for match in predicate.finditer(text):
        if match.start() < pos:
            continue
        span = _turtle_import_span(text, match, (cut_start, pos))
        if span is None:
            declined += 1
            continue
        start, end = _tidy(text, *span)
        if end <= pos:
            continue
        if start >= pos:
            chunk_start = pos
            out.append(text[chunk_start:start])
            cut_start = start
        elif chunk_start <= start < cut_start:
            # Consecutive imports share a separator, so this cut can reach back
            # into text already copied out. Trim that copy back to it.
            out[-1] = text[chunk_start:start]
            cut_start = start
        # Anything at or past cut_start went with the previous cut already.
        pos = end
        removed += 1
    out.append(text[pos:])

    if declined:
        logging.warning(
            f"Left {declined} owl:imports statement(s) in place: could not tell "
            "what to cut without risking the file's syntax."
        )
    return "".join(out), removed


def _strip_obo_imports(text: str) -> Tuple[str, int]:
    """Remove ``import:`` lines from an OBO header.

    Only the header carries them, and only there is ``import:`` a tag rather
    than ordinary text, so the stanzas below are not touched.
    """
    stanza = _OBO_STANZA.search(text)
    end = stanza.start() if stanza else len(text)
    header, removed = _OBO_IMPORT_LINE.subn("", text[:end])
    return header + text[end:], removed


_STRIPPERS = {
    "xml": _strip_xml_imports,
    "turtle": _strip_turtle_imports,
    "obo": _strip_obo_imports,
}


def strip_imports(path: str) -> str:
    """Remove ontology import declarations from an ontology file.

    ROBOT (via the OWL API) tries to resolve owl:imports over the network when it
    loads an ontology; when an import URL is dead, slow, or unreachable from the
    runner the whole convert/relax fails (UnloadableImportException). This is the
    dominant KG-Bioportal transform failure. Each ontology is transformed on its
    own, so imports are not needed -- references to imported terms just become
    dangling edges, resolved later at merge time.

    RDF/XML, OWL/XML, Turtle, N3 and OBO are handled; the serialization is
    sniffed from the content, since BioPortal serves Turtle under a .owl name and
    sources with no extension at all. Anything else is passed through untouched,
    as is a file whose imports could not be removed without risking its syntax.

    Args:
        path: Path to the downloaded ontology file.

    Returns:
        Path to use for the transform (cleaned copy, or the original).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        logging.warning(f"Could not read {path} to strip imports: {e}")
        return path

    kind = _sniff_serialization(text)
    if kind is None:
        logging.info(
            f"Not stripping imports from {os.path.basename(path)}: "
            "unrecognized serialization."
        )
        return path

    cleaned, removed = _STRIPPERS[kind](text)
    if removed == 0:
        return path

    base, ext = os.path.splitext(path)
    new_path = f"{base}_noimports{ext or _EXT_FOR_KIND[kind]}"
    with open(new_path, "w", encoding="utf-8") as f:
        f.write(cleaned)
    logging.info(f"Stripped {removed} import declaration(s) from {os.path.basename(path)}.")
    return new_path


# XML 1.0 forbids the C0 control characters outright -- only tab, newline and
# carriage return are allowed -- and U+FFFE / U+FFFF are never legal either.
# Nothing escapes them: not a character reference, not CDATA. A document holding
# one cannot be parsed, whatever wrote it.
_XML_ILLEGAL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

# The two that are whitespace by origin. A vertical tab or form feed sits
# between words -- they arrive in definitions pasted out of PDFs -- so a space
# keeps the text as it read; dropping it would run the words together.
_ILLEGAL_AS_SPACE = "\x0b\x0c"


def strip_xml_illegal_chars(path: str, ontology_name: str = "") -> str:
    """Remove characters XML cannot represent from an ontology file.

    This is what makes ``robot relax`` fail to load the file ``robot convert``
    just wrote (#141). A control character is perfectly legal in the source: in
    Turtle it is written as an escape (``\\u0001``), and ROBOT parses it happily.
    On the way out, though, ROBOT unescapes it and writes the raw character into
    RDF/XML -- ``<rdfs:label>bad\x01char</rdfs:label>`` -- which no XML parser
    will read back. ``convert`` exits 0, and ``relax`` takes the blame for an
    unusable intermediate it did not produce.

    So this runs over ROBOT's output rather than the source: by then whatever the
    source encoded is raw text, and it is the only point where both spellings of
    the problem look the same.

    Args:
        path: Path to the RDF/XML ROBOT wrote.
        ontology_name: Acronym, used only to make the log line actionable.

    Returns:
        Path to use for the next step (cleaned copy, or the original).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        logging.warning(f"Could not read {path} to check for illegal characters: {e}")
        return path

    found = _XML_ILLEGAL_CHARS.findall(text)
    if not found:
        return path

    cleaned = _XML_ILLEGAL_CHARS.sub(
        lambda m: " " if m.group() in _ILLEGAL_AS_SPACE else "", text
    )

    base, ext = os.path.splitext(path)
    new_path = f"{base}_xmlsafe{ext or '.owl'}"
    with open(new_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    label = ontology_name or os.path.basename(path)
    seen = sorted({f"U+{ord(c):04X}" for c in found})
    logging.warning(
        f"{label}: removed {len(found)} character(s) XML cannot represent "
        f"({', '.join(seen)}); they would have made ROBOT's own output unreadable."
    )
    return new_path


# An xml:lang attribute in either XML serialization, single- or double-quoted.
_XML_LANG_ATTR = re.compile(r"""\s+xml:lang\s*=\s*(["'])(.*?)\1""", re.S)

# What counts as a language tag. This is rdflib 7's own rule (term.py,
# _lang_tag_regex) rather than the stricter BCP 47 shape, which caps each subtag
# at eight characters: rdflib is the only consumer of the file we sanitize, so
# matching its rule exactly strips every tag that would abort the parse and not
# one more. A tag like "portuguese" is not BCP 47, but rdflib accepts it and the
# ontologies carrying it build today.
_LANG_TAG_SHAPE = re.compile(r"^[a-zA-Z]+(?:-[a-zA-Z0-9]+)*$")


def strip_invalid_lang_tags(path: str, ontology_name: str = "") -> str:
    """Drop xml:lang attributes whose values aren't language tags.

    rdflib validates the language tag on every Literal it builds and raises
    rather than warning, so a single bogus ``xml:lang`` anywhere in the file
    aborts the entire KGX parse and loses the ontology (#140). Nothing on the
    BioPortal side validates these, and the values seen in the wild are not near
    misses — an email domain, a Medium article slug — so there is nothing to
    repair. Dropping the attribute keeps the literal, untagged.

    An empty ``xml:lang=""`` is left alone: in XML that resets the language
    inherited from an ancestor element, and rdflib reads it as no tag at all.

    Args:
        path: Path to an RDF/XML or OWL/XML ontology file.
        ontology_name: Acronym, used only to make the log line actionable.

    Returns:
        Path to use for the transform (cleaned copy, or the original).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        logging.warning(f"Could not read {path} to check language tags: {e}")
        return path

    if "xml:lang" not in text:
        return path

    removed: List[str] = []

    def drop_if_invalid(match: "re.Match") -> str:
        value = match.group(2)
        if value == "" or _LANG_TAG_SHAPE.match(value):
            return match.group(0)
        removed.append(value)
        return ""

    cleaned = _XML_LANG_ATTR.sub(drop_if_invalid, text)
    if not removed:
        return path

    base, ext = os.path.splitext(path)
    new_path = f"{base}_langfix{ext or '.owl'}"
    with open(new_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    # One line per distinct value, not per occurrence: these repeat in the
    # hundreds. Named loudly enough to report back to the ontology's maintainers.
    label = ontology_name or os.path.basename(path)
    for value in sorted(set(removed)):
        logging.warning(
            f"{label}: removed invalid xml:lang={value!r} "
            f"({removed.count(value)} occurrence(s)); rdflib rejects it as a language tag."
        )
    return new_path


def summarize(onto_log: dict) -> dict:
    """Roll a per-ontology log up into the fields of total_stats.yaml.

    License-restricted ontologies get their own count and are *excluded* from
    ``failedcount``. They keep ``status: Failed`` in onto_stats (no artifact
    exists for them either way), but nothing about them is broken and no rerun
    will change that, so counting them as failures overstates how much of the
    pipeline needs fixing.

    Args:
        onto_log: {acronym: entry} as built by ``transform_all``.

    Returns:
        Ordered mapping of total_stats.yaml field name to value.
    """
    def by_status(status):
        return sum(1 for e in onto_log.values() if e["status"] == status)

    licensed = sum(
        1 for e in onto_log.values() if e.get("reason") == LICENSE_RESTRICTED_REASON
    )
    return {
        "totalcount": by_status("OK"),
        "skippedcount": by_status("Skipped"),
        "failedcount": by_status("Failed") - licensed,
        "licensedcount": licensed,
        "totalnodecount": sum(e["nodecount"] for e in onto_log.values()),
        "totaledgecount": sum(e["edgecount"] for e in onto_log.values()),
    }


# Extensions BioPortal sources actually arrive in. Used to find the ontology
# among an archive's members; order carries no preference.
_ONTOLOGY_EXTS = frozenset(
    {".owl", ".rdf", ".ttl", ".obo", ".owx", ".n3", ".nt", ".xml", ".omn", ".ofn"}
)

# Archive members that are never the ontology: macOS bundles zip metadata, and
# some submissions carry a licence or readme alongside the source.
_JUNK_PREFIXES = ("__MACOSX/", "._")


def _extract_all(archive, dest: str) -> None:
    """Extract every member, preferring the 'data' filter where available.

    The filter became available in Python 3.12 and is the default from 3.14; ask
    for it explicitly so behaviour doesn't change under us, and fall back for
    the older interpreters this package still supports.
    """
    try:
        archive.extractall(dest, filter="data")
    except TypeError:
        archive.extractall(dest)


def _archive_stem(archive_path: str) -> str:
    """``…/PatientSafetyIncident.zip`` -> ``patientsafetyincident``."""
    base = os.path.basename(archive_path)
    for suffix in (".gz", ".zip"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base.lower().endswith(".tar"):
        base = base[: -len(".tar")]
    return os.path.splitext(base)[0].lower()


def pick_ontology_member(
    members: List[Tuple[str, int]], ontology_name: str, archive_path: str = ""
) -> Optional[str]:
    """Choose the ontology file from an archive's members.

    Several BioPortal submissions ship the ontology alongside its imports, a
    licence, or a project file — OCRE has six members, ICPS twenty-five.
    Refusing those outright (as this used to) loses the ontology entirely.

    Size alone is not a good enough signal: ICPS ships a 340 kB ``Countries.owl``
    next to the 126 kB ``PatientSafetyIncident.owl`` that is actually the
    ontology. What names the subject is the archive itself. So prefer, in order:

    1. a member named after the archive — ``PatientSafetyIncident.zip`` holds
       ``PatientSafetyIncident.owl``;
    2. a member named after the acronym — ``OCRe.zip`` holds ``OCRe.owl``;
    3. the largest file carrying an ontology extension;
    4. the largest file of any kind, since the extension may simply be missing
       (BioPortal serves extensionless sources).

    Ties break on name, so the choice is deterministic across runs.

    Args:
        members: ``(path, size)`` for each file in the archive, paths relative
            to the extraction directory.
        ontology_name: The ontology's acronym.
        archive_path: Path to the archive, for rule 1. Optional so the rule
            simply doesn't apply when the caller has no name to offer.

    Returns:
        The chosen member path, or None if the archive holds nothing usable.
    """
    def is_junk(name):
        base = os.path.basename(name)
        return not base or name.startswith(_JUNK_PREFIXES) or base.startswith(_JUNK_PREFIXES)

    candidates = [(n, s) for n, s in members if not is_junk(n)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # Largest first, then by name for a stable tie-break.
    def rank(item):
        name, size = item
        return (-size, name)

    def stem(name):
        return os.path.splitext(os.path.basename(name))[0].lower()

    for wanted in (_archive_stem(archive_path) if archive_path else "", ontology_name.lower()):
        if not wanted:
            continue
        matches = [(n, s) for n, s in candidates if stem(n) == wanted]
        if matches:
            return sorted(matches, key=rank)[0][0]

    ontology_files = [
        (n, s) for n, s in candidates if os.path.splitext(n)[1].lower() in _ONTOLOGY_EXTS
    ]
    return sorted(ontology_files or candidates, key=rank)[0][0]


# ROBOT errors that mean "the ontology loaded, but this serialization cannot
# express it". The source is fine; RDF/XML is the problem -- most often an IRI
# whose local part is not a legal XML element name, which RDF/XML has no way to
# write. Both spellings ROBOT uses are here: it reports the failure to save as
# ONTOLOGY STORAGE ERROR, and the offending IRI as INVALID ELEMENT ERROR.
_SERIALIZATION_ERRORS = (
    "ONTOLOGY STORAGE ERROR",
    "INVALID ELEMENT ERROR",
    "OWLOntologyStorageException",
)

# What to write instead when RDF/XML cannot hold the ontology. Turtle can write
# any IRI (it falls back to <...>), and stays RDF all the way to the KGX step --
# where OWL functional syntax would only move the same wall one step later.
FALLBACK_SERIALIZATION = ".ttl"


# ROBOT errors that mean the file could not be read at all -- not that some
# step went wrong with it. When convert says this, the file is the source
# exactly as BioPortal served it, and nothing on our side will change the
# outcome (#142). The same words from relax are about our own intermediate
# (#141), which is why only the convert stage consults this.
_LOAD_FAILURE_MARKERS = (
    "INVALID ONTOLOGY FILE ERROR",
    "Could not load a valid ontology",
    "UnparsableOntologyException",
)

# The onto_stats reason for those, so they stop sitting in the same bucket as
# failures we can do something about.
INVALID_SOURCE_REASON = "invalid_source"


# Who we got the ontology from. BioPortal aggregates ontologies it does not
# author, which is what an aggregator_knowledge_source is for; the ontology
# itself is the primary source of its own assertions.
AGGREGATOR_INFORES = "infores:bioportal"

# The columns the TSVs carry. Streaming is the only way a 250 MB ontology fits
# on a runner, and a streaming sink cannot discover its columns from records it
# has already written past -- KGX says as much, and falls back to a fixed
# DEFAULT_EDGE_COLUMNS that has "knowledge_source" in it and neither of the two
# slots we actually populate. So the provenance would sit on every record and
# reach no column. Declared here instead.
#
# These are KGX's own defaults with the edge provenance corrected: the generic
# "knowledge_source" is dropped because nothing fills it once the specific slots
# are set, and an always-empty column is worse than no column.
NODE_COLUMNS = [
    "id", "category", "name", "description", "provided_by",
    "synonym", "exact_synonym", "broad_synonym", "narrow_synonym",
    "related_synonym",
]
EDGE_COLUMNS = [
    "id", "subject", "predicate", "object", "category", "relation",
    "primary_knowledge_source", "aggregator_knowledge_source",
]

# An acronym is not an infores identifier, and inventing a registry entry for
# 1190 ontologies is not this function's job -- but a bare "AGRO" in a
# knowledge_source column is not one either. Namespacing it says plainly where
# the value came from and keeps it distinguishable from a registered infores,
# which is the honest state of things until BioPortal ontologies have real ones.
INFORES_PREFIX = "infores:bioportal."


def ontology_infores(acronym: str) -> str:
    """The knowledge-source identifier for one BioPortal ontology.

    Lowercased and namespaced under the aggregator: infores identifiers are
    conventionally lowercase, and an acronym on its own would read as a claim to
    a registered infores that does not exist.
    """
    return f"{INFORES_PREFIX}{acronym.strip().lower()}"

# Ceiling on the syntax check below. It runs only for an ontology that has
# already failed, but rdflib holds the whole graph in memory and the per-
# ontology deadline is still ticking, so a giant source is reported unchecked
# rather than risking the diagnosis turning into a timeout.
MAX_SYNTAX_CHECK_MB = 25

# rdflib format for each serialization the sniffer recognizes. OBO is not RDF,
# so there is nothing rdflib can say about it.
_RDFLIB_FORMATS = {"xml": "xml", "turtle": "turtle"}

# An HTML document arriving under an ontology's name -- an error page served in
# place of the file. Worth naming outright: rdflib's RDF/XML parser reads
# arbitrary XML, so it will happily report "valid XML, 3 triples" for a 404 page
# and the diagnosis would reassure where it should not.
_HTML_DOCUMENT = re.compile(r"^\s*(?:<!doctype\s+html|<html[\s>])", re.I)


def is_load_failure(error: str) -> bool:
    """Whether ROBOT could not read the file at all, as opposed to failing over it."""
    return any(marker in error for marker in _LOAD_FAILURE_MARKERS)


class SourceDiagnosis(NamedTuple):
    """What a syntax check could establish about a file ROBOT would not read."""

    # True when the file parses as RDF, False when it does not, and None when
    # nothing could be checked -- too large, not an RDF serialization, or
    # unreadable. None is not "fine": it is "unknown", and callers must not
    # read it as either answer.
    parsed: Optional[bool]
    # A phrase to append to the recorded detail, or "" when there is nothing
    # to say at all.
    detail: str


UNCHECKED = SourceDiagnosis(None, "")


def diagnose_source(
    path: str, max_mb: float = MAX_SYNTAX_CHECK_MB, subject: str = "source"
) -> SourceDiagnosis:
    """Say why a file ROBOT refused is unusable, in terms someone can act on.

    ROBOT reports the same thing for a file that is not valid RDF and for one
    that is valid RDF it will not accept as an ontology, and #142 wants those
    told apart: the first is a bug report to the ontology's maintainers, with a
    line number; the second is a file that might yet be readable another way.
    rdflib answers the question directly, and it is already a dependency.

    Args:
        path: The file to check.
        max_mb: Ceiling above which the file is reported unchecked.
        subject: What to call the file in the phrase, since this is also used
            on our own intermediates, where calling them "source" would pin our
            bug on the ontology's maintainers.
    """
    try:
        size_mb = os.path.getsize(path) / 1024 / 1024
    except OSError:
        return UNCHECKED
    if max_mb and size_mb > max_mb:
        return SourceDiagnosis(None, f"{subject} not syntax-checked ({size_mb:.1f} MB)")

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return UNCHECKED

    if _HTML_DOCUMENT.match(text[:4096].lstrip("\ufeff")):
        return SourceDiagnosis(False, f"{subject} is an HTML document, not an ontology")

    rdflib_format = _RDFLIB_FORMATS.get(_sniff_serialization(text) or "")
    if not rdflib_format:
        return SourceDiagnosis(
            None, f"{subject} is not an RDF serialization we can check"
        )

    try:
        import rdflib
    except ImportError:  # pragma: no cover - rdflib ships with kgx
        return UNCHECKED

    graph = rdflib.Graph()
    try:
        graph.parse(path, format=rdflib_format)
    except Exception as e:
        # The line and column live in the message; they are what an upstream
        # report needs, so keep the message rather than just the type.
        return SourceDiagnosis(
            False, f"{subject} is not valid {rdflib_format}: {type(e).__name__}: {e}"
        )
    return SourceDiagnosis(
        True,
        f"{subject} is valid {rdflib_format} ({len(graph)} triples) that ROBOT "
        "will not load as an ontology",
    )


# What we call the file we hand ROBOT when it is not the file BioPortal served.
STRIPPED_SUBJECT = "the import-stripped copy"


def diagnose_load_failure(
    source_path: str,
    robot_input_path: str,
    max_mb: float = MAX_SYNTAX_CHECK_MB,
) -> Tuple[str, str]:
    """Attribute a file ROBOT could not read to BioPortal or to ourselves.

    strip_imports rewrites most sources before ROBOT sees them, so "ROBOT could
    not load this file" is not on its own a statement about what BioPortal
    served -- the file named in the error may be one we wrote. Recording that as
    invalid_source blames the ontology's maintainers for our own bug, and hides
    a stripper that corrupts files inside a bucket labelled "not our problem".

    So check the source itself. If it does not parse, the source is the story.
    If it parses and the copy we handed ROBOT does not, the corruption is ours
    and belongs with the failures we can fix.

    Returns:
        (reason, detail): reason is INVALID_SOURCE_REASON when the source is
        what is unusable, or "" -- meaning the transform's own stage reason --
        when our preprocessing is what ROBOT choked on.
    """
    source = diagnose_source(source_path, max_mb=max_mb)
    if robot_input_path == source_path or source.parsed is not True:
        # Nothing of ours stands between BioPortal's file and ROBOT, or the
        # source is itself unreadable (or unknowable). Either way, the source.
        return INVALID_SOURCE_REASON, source.detail

    ours = diagnose_source(robot_input_path, max_mb=max_mb, subject=STRIPPED_SUBJECT)
    if ours.parsed is False:
        return "", f"{ours.detail}, from a source that parses cleanly"
    return INVALID_SOURCE_REASON, source.detail


def is_serialization_failure(error: str) -> bool:
    """Whether a ROBOT error is the output format's fault rather than the input's."""
    return any(marker in error for marker in _SERIALIZATION_ERRORS)


# How much of a failure message to keep in the stats. Long enough for a ROBOT
# exception with its cause chain, short enough that onto_stats.yaml stays
# readable with a few hundred failures in it.
MAX_DETAIL_CHARS = 500

# Stages a transform can fail at, in the order it runs them. The reason written
# to onto_stats is "transform_error_<stage>", so every transform failure still
# greps as transform_error while saying which step lost the ontology (#134).
TRANSFORM_STAGES = ("decompress", "convert", "relax", "kgx")


def reason_for_stage(stage: str) -> str:
    """The onto_stats ``reason`` for a transform that died at ``stage``."""
    if stage in TRANSFORM_STAGES:
        return f"transform_error_{stage}"
    return "transform_error"  # a failure with no stage recorded; keep the old name


class TransformOutcome(NamedTuple):
    """What became of one ontology, and -- when it failed -- where and why.

    Every failure used to arrive at the caller as a bare False, so the stats
    could only record the constant "transform_error" for all of them. Auditing
    66 failures then meant reconstructing the stage from half a million lines of
    Actions logs, which expire (#134).
    """

    success: bool
    nodecount: int = 0
    edgecount: int = 0
    stage: str = ""
    detail: str = ""
    # Set only when the stage does not describe the failure: a source ROBOT
    # cannot load is not "the convert step went wrong", it is a file we were
    # never going to be able to transform (#142).
    reason: str = ""
    # Literals whose lexical form does not match their declared datatype -- a
    # data-quality fact about the source, counted rather than logged (#152).
    malformed_literals: int = 0
    # Biolink categories present on this ontology's nodes and edges, and how
    # many of each (#98). Empty for a failure, and for an ontology whose files
    # carry no category column at all. Appended after malformed_literals so
    # ``failed()``'s positional construction is unaffected.
    #
    # The two empty dicts are shared defaults, as any NamedTuple default is:
    # nothing here mutates a tally after it is built.
    node_categories: Dict[str, int] = {}
    edge_categories: Dict[str, int] = {}

    @classmethod
    def failed(
        cls,
        stage: str,
        detail: str = "",
        reason: str = "",
        malformed_literals: int = 0,
    ) -> "TransformOutcome":
        return cls(
            False, 0, 0, stage, summarize_detail(detail), reason, malformed_literals
        )


# SKOS vocabularies label with skos:prefLabel, and KGX reads only the properties
# the Biolink model names -- where `name` is rdfs:label and nothing else. So an
# ontology that labels the SKOS way loses every label silently: ICD10PCS ships
# 192,698 procedure codes and four names, and six other ontologies in the twenty
# holding the most uncategorized nodes are in the same state, 1,009,910 nodes
# between them (#173).
#
# KGX can be told about the extra predicates -- Transformer.transform forwards
# both keys to RdfSource -- but prefLabel must NOT be mapped straight to `name`.
# `name` is single-valued, so where a term carries rdfs:label *and* a differing
# prefLabel the winner is whichever the parser reaches last, and that order comes
# out of a set: measured across PYTHONHASHSEED 0-7, the same file produced the
# rdfs:label three times and the prefLabel five. A published name that flips
# between releases with no change to the source is worse than a missing one.
#
# So prefLabel is given a column to itself, where it can race nothing, and
# adopt_pref_labels folds it into `name` afterwards -- only where rdfs:label left
# `name` empty. Deterministic, and rdfs:label always wins.
SKOS = "http://www.w3.org/2004/02/skos/core#"
PREF_LABEL_COLUMN = "pref_label"
SKOS_PROPERTY_MAP = {
    SKOS + "prefLabel": PREF_LABEL_COLUMN,
    SKOS + "altLabel": "synonym",
    SKOS + "definition": "description",
}

# What we ask KGX to write: the published columns plus the scratch one that
# adopt_pref_labels consumes and removes. dcterms:title needs no entry -- Biolink
# already maps it to `name`.
KGX_NODE_COLUMNS = NODE_COLUMNS + [PREF_LABEL_COLUMN]


def adopt_pref_labels(node_file: str) -> int:
    """Fill an empty ``name`` from ``skos:prefLabel``, and drop the scratch column.

    Runs over the finished node file, so the choice is made per node against
    what was actually written rather than against whatever order a parser
    happened to visit two triples in.

    A file without the scratch column -- one written before this existed, or by
    a test -- is left exactly as it is.

    Returns:
        How many nodes took their name from a prefLabel.
    """
    with open(node_file, "r") as f:
        header = f.readline()
    if not header:
        return 0
    fields = header.rstrip("\n").split("\t")
    if PREF_LABEL_COLUMN not in fields:
        return 0
    pref_at = fields.index(PREF_LABEL_COLUMN)
    name_at = fields.index("name") if "name" in fields else None
    keep = [i for i in range(len(fields)) if i != pref_at]

    adopted = 0
    temp_path = node_file + ".labelled"
    with open(node_file, "r") as src, open(temp_path, "w") as dest:
        src.readline()
        dest.write("\t".join(fields[i] for i in keep) + "\n")
        for line in src:
            cells = line.rstrip("\n").split("\t")
            while len(cells) < len(fields):
                cells.append("")
            if name_at is not None and not cells[name_at].strip() and cells[pref_at].strip():
                cells[name_at] = cells[pref_at]
                adopted += 1
            dest.write("\t".join(cells[i] for i in keep) + "\n")
    os.replace(temp_path, node_file)
    return adopted


# Recorded in place of an empty category cell, so "how many of these carry no
# category at all" is a number in the report rather than a blank key.
UNCATEGORIZED = "(none)"


def tally_column(path: str, column: str = "category") -> Tuple[int, Dict[str, int]]:
    """Count a KGX TSV's rows and tally the values of one column.

    Read line by line rather than in one go: a large ontology's node file runs
    to hundreds of megabytes, and this replaces a ``readlines()`` that held all
    of it at once purely to take its length.

    KGX writes a multi-valued column pipe-delimited, and a node may legitimately
    carry more than one category. Each value is counted once per row it appears
    in, so a tally sums to at least the row count and can exceed it: it answers
    "how many nodes are a Disease", not "how do the nodes partition".

    Args:
        path: The TSV to read. Its first line is the header.
        column: Header name to tally. A file without that column is still
            counted; its tally is empty.

    Returns:
        (rows excluding the header, {value: rows carrying that value}).
    """
    counts: Dict[str, int] = {}
    rows = 0
    with open(path, "r") as f:
        header = f.readline()
        if not header:
            return 0, counts
        fields = header.rstrip("\n").split("\t")
        index = fields.index(column) if column in fields else None
        for line in f:
            rows += 1
            if index is None:
                continue
            cells = line.rstrip("\n").split("\t")
            cell = cells[index].strip() if index < len(cells) else ""
            values = [v.strip() for v in cell.split("|") if v.strip()]
            for value in values or [UNCATEGORIZED]:
                counts[value] = counts.get(value, 0) + 1
    return rows, counts


def format_tally(counts: Dict[str, int], limit: int = 10) -> str:
    """A tally as one log line, biggest first.

    Truncated rather than unbounded: the full tally goes to onto_stats.yaml, and
    an ontology with a long tail of categories should not push everything else
    in the shard log out of view.
    """
    if not counts:
        return "none"
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ", ".join(f"{name} {count:,}" for name, count in ranked[:limit])
    if len(ranked) > limit:
        shown += f", and {len(ranked) - limit} more"
    return shown


def summarize_detail(text: str, limit: int = MAX_DETAIL_CHARS) -> str:
    """Squash a failure message onto one line and cap its length.

    These end up in a YAML field that people read; a multi-line exception or a
    dumped stack trace makes onto_stats.yaml unusable as a summary.
    """
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


# rdflib logs one warning per literal whose lexical form does not match its
# declared datatype, with exc_info, so each costs two formatted tracebacks. One
# ontology (BDPM, which types DD/MM/YYYY dates as xsd:dateTime) produced 36,710
# of them in a single run -- about 95% of that shard's half-million log lines,
# burying everything else in it (#152).
_LITERAL_WARNING = "Failed to convert Literal lexical form to value"

# The datatype is in the message; the offending value is in neither the message
# nor, reliably, the exception text -- see _offending_value.
_WARNING_DATATYPE = re.compile(r"Datatype=(\S+?),")
_QUOTED_VALUE = re.compile(r"'([^']*)'")


def _offending_value(record: "logging.LogRecord") -> Optional[str]:
    """The literal rdflib could not convert, from the frame that failed.

    Read out of the traceback rather than out of the exception's prose, because
    the prose depends on which converter is installed and does not reliably put
    the value first. rdflib's own ``_castLexicalToPython(lexical, datatype)`` is
    the frame the exception was raised in, so its ``lexical`` is exactly the
    value, whatever converter raised:

        isodate:        "ISO 8601 time designator 'T' missing. Unable to parse
                         datetime string '06/09/2012'"     <- 'T' comes first
        fromisoformat:  "Invalid isoformat string: '06/09/2012'"

    Falls back to the longest quoted run in the exception chain, for a future
    rdflib that names the variable something else -- longest rather than first
    for the same reason: 'T' is quoted too.
    """
    if not record.exc_info:
        return None
    _, exception, traceback = record.exc_info

    while traceback is not None:
        lexical = traceback.tb_frame.f_locals.get("lexical")
        if isinstance(lexical, str):
            return lexical
        traceback = traceback.tb_next

    best = None
    while exception is not None:
        for quoted in _QUOTED_VALUE.findall(str(exception)):
            if best is None or len(quoted) > len(best):
                best = quoted
        exception = exception.__cause__ or exception.__context__
    return best

# Namespaces worth abbreviating in the summary line. XSD is essentially all of
# them in practice, since it owns the datatypes with lexical rules.
_DATATYPE_PREFIXES = {
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
}


def abbreviate_datatype(iri: str) -> str:
    """``...XMLSchema#dateTime`` -> ``xsd:dateTime``, for a readable summary."""
    for namespace, prefix in _DATATYPE_PREFIXES.items():
        if iri.startswith(namespace):
            return prefix + iri[len(namespace):]
    return iri


class LiteralConversionTally(logging.Filter):
    """Counts rdflib's per-literal warnings instead of letting them print.

    "This ontology has 36,710 literals whose lexical form does not match their
    declared datatype" is a real fact about the source. Emitted once with a
    count it is information; emitted 36,710 times with tracebacks it is noise
    that hides every other line in the run -- and costs real time to format.

    Only that one message is intercepted. Anything else rdflib's term logger has
    to say still comes through.
    """

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.by_datatype: dict = {}
        self.example = ""

    def filter(self, record: "logging.LogRecord") -> bool:
        if record.levelno < logging.WARNING:
            return True
        try:
            message = record.getMessage()
        except Exception:  # a record we cannot even format is not ours to judge
            return True
        if _LITERAL_WARNING not in message:
            return True

        self.count += 1
        match = _WARNING_DATATYPE.search(message)
        datatype = abbreviate_datatype(match.group(1)) if match else "(no datatype)"
        self.by_datatype[datatype] = self.by_datatype.get(datatype, 0) + 1
        if not self.example:
            self.example = self._describe(datatype, record)
        return False  # counted; do not emit

    @staticmethod
    def _describe(datatype: str, record: "logging.LogRecord") -> str:
        """One example, for a summary that names the actual problem."""
        value = _offending_value(record)
        return f"{datatype} {value!r}" if value is not None else datatype

    def summary(self) -> str:
        """One line describing everything this tally swallowed."""
        if not self.count:
            return ""
        worst = sorted(self.by_datatype.items(), key=lambda kv: (-kv[1], kv[0]))
        datatypes = ", ".join(f"{name} x{n}" for name, n in worst[:3])
        if len(worst) > 3:
            datatypes += f", and {len(worst) - 3} more"
        example = f" (e.g. {self.example})" if self.example else ""
        return (
            f"{self.count} literal(s) whose lexical form does not match their "
            f"datatype [{datatypes}]{example}; values kept as written."
        )

    @contextmanager
    def installed(self):
        """Intercept the warnings for the duration of the block.

        A filter on the logger itself drops the record before any handler sees
        it, so nothing formats the tracebacks that make these expensive.
        """
        logger = logging.getLogger("rdflib.term")
        logger.addFilter(self)
        try:
            yield self
        finally:
            logger.removeFilter(self)


class TransformTimeout(Exception):
    """Raised when a single ontology transform exceeds its wall-clock budget."""


class SourceTooLarge(Exception):
    """Raised when a decompressed source exceeds the size gate.

    The downloader's gate weighs the file as served, which for a compressed
    source says nothing useful: ROR is 14 MB gzipped and 141 MB unpacked, HGNC-NR
    7.8 MB and 170 MB. Both are past the limit that exists to keep the runner
    alive, and neither could be caught until decompression made them visible.
    """


@contextmanager
def deadline(seconds: int):
    """Enforce a wall-clock deadline on a block of code.

    Uses SIGALRM, so it only arms on platforms that support it (Linux, macOS)
    and only in the main thread. Elsewhere it is a no-op. This is the outer cap
    covering the whole ROBOT + KGX chain for one ontology; ROBOT subprocesses
    also get their own ``_timeout`` as a backstop.
    """
    if not seconds or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise TransformTimeout()

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(seconds))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


class Transformer:

    def __init__(
        self,
        input_dir: str = "data/raw",
        output_dir: str = "data/transformed",
        timeout_min: float = PER_ONTOLOGY_TIMEOUT_MIN,
        max_source_mb: float = MAX_SOURCE_MB,
    ) -> None:
        """Initializes the Transformer class.

        Also sets up ROBOT.

        Args:
            input_dir: A string pointing to the location of the raw data.
            output_dir: A string pointing to the location to write products to.
            timeout_min: Per-ontology wall-clock cap in minutes. An ontology that
                runs longer is killed and recorded as skipped (too_slow).
            max_source_mb: Size gate re-applied to a *decompressed* source, which
                the downloader's gate could not weigh. Over this, the ontology is
                recorded as skipped (too_large) instead of being handed to ROBOT.

        Returns:
            None.
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.timeout_min = timeout_min
        self.timeout_sec = int(timeout_min * 60)
        self.max_source_mb = max_source_mb
        self.max_source_bytes = int(max_source_mb * 1024 * 1024)

        # If the output directory does not exist, create it
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # Do ROBOT setup
        logging.info("Setting up ROBOT...")
        self.robot_path = os.path.join(os.getcwd(), "robot")
        self.robot_params = initialize_robot(self.robot_path)
        logging.info(f"ROBOT path: {self.robot_path}")
        self.robot_env = self.robot_params[1]
        logging.info(f"ROBOT evironment variables: {self.robot_env['ROBOT_JAVA_ARGS']}")

        return None

    def _load_download_report(self) -> dict:
        """Read download_report.tsv (if present) into {id: row} form.

        This lets the final stats account for ontologies that were skipped or
        errored during download and therefore never reach the transform walk.
        """
        report_path = os.path.join(self.input_dir, DOWNLOAD_REPORT_NAME)
        report = {}
        if not os.path.exists(report_path):
            return report
        with open(report_path, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                report[row["id"]] = row
        return report

    def transform_all(self, compress: bool) -> None:
        """Transforms all ontologies in the input directory to KGX nodes and edges.

        Yields two log files: total_stats.yaml and onto_stats.yaml.
        The first contains the total counts of Bioportal ontologies and transforms.
        The second contains the counts of nodes and edges for each ontology, plus
        its status (OK / Failed / Skipped), the reason for any skip or failure,
        and -- for a failure -- a detail field carrying the message that caused it.

        Args:
            compress: If True, compresses the output nodes and edges to tar.gz.

        Returns:
            None.
        """

        logging.info(
            f"Transforming all ontologies in {self.input_dir} to KGX nodes and edges."
        )

        download_report = self._load_download_report()

        # This keeps track of the status of each transform.
        # Ontology acronym IDs are keys. Values carry status, counts, reason,
        # submission id, and source size.
        onto_log = {}

        # Seed the log with ontologies that were skipped or errored at download
        # time (they have no file on disk to walk).
        for onto_id, row in download_report.items():
            if row.get("status") in ("skipped", "error"):
                entry = {
                    "status": "Skipped" if row["status"] == "skipped" else "Failed",
                    "reason": row.get("reason", ""),
                    "name": row.get("name", ""),
                    "version": row.get("version", ""),
                    "nodecount": 0,
                    "edgecount": 0,
                    "submission_id": row.get("submission_id", "NA"),
                    "source_bytes": int(row.get("source_bytes") or 0),
                }
                # Only download outcomes have a status code; don't clutter the
                # other entries with an empty field.
                http_status = row.get("http_status") or ""
                if http_status:
                    entry["http_status"] = int(http_status)
                onto_log[onto_id] = entry

        filepaths = []
        for root, _dirs, files in os.walk(self.input_dir):
            for file in files:
                if file not in _NON_ONTOLOGY_FILES:
                    filepaths.append(os.path.join(root, file))

        if len(filepaths) == 0 and not onto_log:
            logging.error(f"No ontologies found in {self.input_dir}.")
            sys.exit()
        else:
            logging.info(f"Found {len(filepaths)} ontologies to transform.")

        for filepath in filepaths:
            ontology_name = (os.path.relpath(filepath, self.input_dir)).split(os.sep)[0]
            report_row = download_report.get(ontology_name, {})
            reason = ""
            detail = ""
            try:
                with deadline(self.timeout_sec):
                    outcome = self.transform(filepath, compress)
            except TransformTimeout:
                logging.error(
                    f"Transform of {ontology_name} exceeded {self.timeout_min} min; skipping."
                )
                outcome = TransformOutcome(False)
                reason = "too_slow"
                detail = f"exceeded the per-ontology limit of {self.timeout_min} min"
            except SourceTooLarge as e:
                logging.warning(f"Skipping {ontology_name}: {e}.")
                outcome = TransformOutcome(False)
                reason = "too_large"
                detail = summarize_detail(e)

            nodecount, edgecount = outcome.nodecount, outcome.edgecount
            if not outcome.success:
                strstatus = "Skipped" if reason in ("too_slow", "too_large") else "Failed"
                # A deliberate skip is not an error; saying so in the log made
                # the two indistinguishable when reading a run afterwards.
                if strstatus == "Failed":
                    logging.error(f"Error transforming {filepath}.")
                else:
                    logging.info(f"Skipped {filepath} ({reason}).")
                nodecount = 0
                edgecount = 0
                if not reason:
                    # Name the stage that lost it, so the next audit is a grep of
                    # onto_stats.yaml rather than an archaeology of expiring logs.
                    reason = outcome.reason or reason_for_stage(outcome.stage)
                    detail = outcome.detail
            else:
                logging.info(f"Transformed {filepath}.")
                strstatus = "OK"

            entry = {
                "status": strstatus,
                "reason": reason,
                "name": report_row.get("name", ""),
                "version": report_row.get("version", ""),
                "nodecount": nodecount,
                "edgecount": edgecount,
                "submission_id": report_row.get("submission_id", "NA"),
                "source_bytes": int(report_row.get("source_bytes") or 0),
            }
            # Only failures have anything to explain; an empty field on every OK
            # entry would be a thousand lines of noise in the index.
            if detail:
                entry["detail"] = detail
            # Same reasoning: recorded only for the ontologies that have any.
            if outcome.malformed_literals:
                entry["malformed_literals"] = outcome.malformed_literals
            # What kinds of node and edge this ontology actually produced (#98).
            # Only OK entries have any; a failure has no files to tally.
            if outcome.node_categories:
                entry["node_categories"] = dict(outcome.node_categories)
            if outcome.edge_categories:
                entry["edge_categories"] = dict(outcome.edge_categories)
            onto_log[ontology_name] = entry

        # Write total stats to a yaml
        logging.info("Writing total stats to total_stats.yaml.")
        totals = summarize(onto_log)
        with open(os.path.join(self.output_dir, "total_stats.yaml"), "w") as f:
            for key, value in totals.items():
                f.write(f"{key}: {value}\n")

        # Dump onto_log to a yaml
        logging.info("Writing ontology stats to onto_stats.yaml.")
        onto_stats_list = []
        for onto in sorted(onto_log):
            entry = {"id": onto}
            entry.update(onto_log[onto])
            onto_stats_list.append(entry)
        with open(os.path.join(self.output_dir, "onto_stats.yaml"), "w") as of:
            yaml.dump({"ontologies": onto_stats_list}, of, sort_keys=False)

        return None

    def transform(self, ontology_path: str, compress: bool) -> TransformOutcome:
        """Transforms a single ontology to KGX nodes and edges.

        The compressed product is written flat as ``<output_dir>/<ACRONYM>.tar.gz``
        so it can be uploaded directly as a GitHub Release asset.

        Args:
            ontology_path: A string of the path to the ontology file to transform.
            compress: If True, compresses the output nodes and edges to tar.gz.

        Returns:
            A TransformOutcome: whether it succeeded, the node and edge counts,
            and for a failure the stage it died at and the message that stage
            gave, so the stats can say more than "transform_error".
        """
        nodecount = 0
        edgecount = 0

        ontology_name = (os.path.relpath(ontology_path, self.input_dir)).split(os.sep)[
            0
        ]
        ontology_submission_id = (os.path.relpath(ontology_path, self.input_dir)).split(
            os.sep
        )[1]

        logging.info(
            f"Transforming {ontology_name}, submission ID {ontology_submission_id}, to nodes and edges."
        )

        workdir = os.path.join(
            self.output_dir, f"{ontology_name}", f"{ontology_submission_id}"
        )
        owl_output_path = os.path.join(workdir, f"{ontology_name}.owl")

        # If the downloaded file is compressed, we need to decompress it
        if ontology_path.endswith((".gz", ".zip")):
            new_path = self.decompress(
                ontology_path=ontology_path, ontology_name=ontology_name
            )
            if new_path != ontology_path:
                ontology_path = new_path
            else:
                logging.error(f"Failed to decompress {ontology_path}")
                return TransformOutcome.failed(
                    "decompress",
                    f"could not decompress {os.path.basename(ontology_path)}",
                )

            # Re-apply the size gate now that we can see the real size. The
            # downloader weighed the compressed file, which understates a
            # gzipped ontology by an order of magnitude.
            unpacked = os.path.getsize(ontology_path)
            if self.max_source_bytes and unpacked > self.max_source_bytes:
                raise SourceTooLarge(
                    f"{ontology_name} unpacks to {unpacked / 1024 / 1024:.1f} MB "
                    f"(> {self.max_source_mb} MB limit)"
                )

        # Keep what BioPortal served. From here on ontology_path may be a file
        # we wrote, and a failure over it is not upstream's to answer for.
        source_path = ontology_path

        # Remove owl:imports so ROBOT doesn't try (and fail) to fetch external
        # ontologies over the network — the dominant cause of transform errors.
        # Each ontology is transformed standalone; references to imported terms
        # simply become dangling edges, resolved later at merge time.
        ontology_path = strip_imports(ontology_path)

        # Drop invalid xml:lang here, on the way in, and not only from ROBOT's
        # output further down. An XML attribute takes any string, but a Turtle
        # language tag is part of the grammar, so when ROBOT writes one of these
        # out as Turtle -- which it does on either fallback below -- it emits
        # `"x"@editor@example.com`, which is not Turtle at all and takes the
        # ontology out at the KGX step instead. Cleaning the source means no
        # serialization ROBOT picks can carry the problem forward. XML-only, and
        # a no-op for a file with no xml:lang in it, so a Turtle source (where
        # such a tag could never have parsed) is untouched.
        ontology_path = strip_invalid_lang_tags(ontology_path, ontology_name)

        # Convert
        def convert_to(output_path):
            return robot_convert(
                robot_path=self.robot_path,
                input_path=ontology_path,
                output_path=output_path,
                robot_env=self.robot_env,
                timeout=self.timeout_sec,
            )

        intermediate_path = owl_output_path
        converted = convert_to(intermediate_path)
        if not converted and is_serialization_failure(converted.error):
            # The ontology loaded; RDF/XML just cannot write it back (#139).
            # Nothing downstream requires this intermediate to be RDF/XML, so
            # write the one serialization that can hold it.
            logging.warning(
                f"{ontology_name}: RDF/XML cannot express this ontology "
                f"({converted.error}); retrying as {FALLBACK_SERIALIZATION}."
            )
            intermediate_path = os.path.join(
                workdir, f"{ontology_name}{FALLBACK_SERIALIZATION}"
            )
            converted = convert_to(intermediate_path)
        if not converted:
            if is_load_failure(converted.error):
                # ROBOT could not read the file at all. That is usually a source
                # we were never going to transform, recorded apart from the
                # failures that are ours to fix (#142) -- but convert's input is
                # the stripped copy, not what BioPortal served, so which of the
                # two is unusable has to be established rather than assumed.
                reason, diagnosis = diagnose_load_failure(source_path, ontology_path)
                if reason == INVALID_SOURCE_REASON:
                    logging.error(f"{ontology_name}: unusable source. {diagnosis}")
                else:
                    logging.error(
                        f"{ontology_name}: we broke this file, not BioPortal. "
                        f"{diagnosis}"
                    )
                return TransformOutcome.failed(
                    "convert",
                    f"{converted.error} ({diagnosis})" if diagnosis else converted.error,
                    reason=reason,
                )
            return TransformOutcome.failed("convert", converted.error)

        # ROBOT can write a character into its own output that no XML parser will
        # read back, so `relax` fails on a file `convert` exited 0 over (#141).
        # Only XML has that problem, and only an XML file is worth rewriting for it.
        intermediate_ext = os.path.splitext(intermediate_path)[1]
        relax_input_path = intermediate_path
        if intermediate_ext != FALLBACK_SERIALIZATION:
            relax_input_path = strip_xml_illegal_chars(intermediate_path, ontology_name)

        # Relax. Its output is what KGX parses, so it keeps the serialization the
        # ontology could actually be written in.
        def relax_to(output_path, input_path):
            return robot_relax(
                robot_path=self.robot_path,
                input_path=input_path,
                output_path=output_path,
                robot_env=self.robot_env,
                timeout=self.timeout_sec,
            )

        relaxed_outpath = os.path.join(
            workdir, f"{ontology_name}_relaxed{intermediate_ext}"
        )
        relaxed = relax_to(relaxed_outpath, relax_input_path)
        if (
            not relaxed
            and is_serialization_failure(relaxed.error)
            and intermediate_ext != FALLBACK_SERIALIZATION
        ):
            # convert could write RDF/XML but relax cannot: same wall, one step
            # later, and the same way through it.
            logging.warning(
                f"{ontology_name}: RDF/XML cannot express the relaxed ontology "
                f"({relaxed.error}); retrying as {FALLBACK_SERIALIZATION}."
            )
            relaxed_outpath = os.path.join(
                workdir, f"{ontology_name}_relaxed{FALLBACK_SERIALIZATION}"
            )
            relaxed = relax_to(relaxed_outpath, relax_input_path)
        elif (
            not relaxed
            and is_load_failure(relaxed.error)
            and intermediate_ext != FALLBACK_SERIALIZATION
        ):
            # ROBOT will not read back the RDF/XML ROBOT just wrote. Its RDF/XML
            # parser resolves every IRI against the base with java.net.URI and
            # rejects what its Turtle parser accepted a step earlier, so an IRI
            # holding a stray '%', a quote, a '<' or a second '#' loads from the
            # source and then fails on the way in. Nothing is wrong with the
            # ontology and nothing downstream needs this intermediate to be
            # RDF/XML, so convert the source again to the serialization that can
            # hold those IRIs, and relax that.
            #
            # It has to start from the source: ROBOT cannot read the RDF/XML it
            # produced, so there is nothing to convert it *from*.
            logging.warning(
                f"{ontology_name}: ROBOT cannot read back its own RDF/XML "
                f"({relaxed.error}); converting to {FALLBACK_SERIALIZATION} instead."
            )
            fallback_path = os.path.join(
                workdir, f"{ontology_name}{FALLBACK_SERIALIZATION}"
            )
            reconverted = convert_to(fallback_path)
            if reconverted:
                intermediate_ext = FALLBACK_SERIALIZATION
                relaxed_outpath = os.path.join(
                    workdir, f"{ontology_name}_relaxed{FALLBACK_SERIALIZATION}"
                )
                relaxed = relax_to(relaxed_outpath, fallback_path)
        if not relaxed:
            return TransformOutcome.failed("relax", relaxed.error)

        # Strip imports again, this time from ROBOT's output. ROBOT keeps the
        # owl:imports triples in what it writes, and KGX's OwlSource dereferences
        # every one of them over the network as it parses — so a transform that
        # got this far could still die on whatever a remote server happened to
        # return, and an ontology that succeeded silently absorbed whatever was
        # at those URLs that day. Stripping here makes the KGX step hermetic.
        # ROBOT always writes RDF/XML for a .owl output, so the stripper applies.
        stripped_path = strip_imports(relaxed_outpath)

        # Same pass, same reason: rdflib raises on an invalid xml:lang instead
        # of warning, so one typo'd attribute takes the whole ontology down at
        # parse time. The source was cleaned on the way in; this catches an
        # RDF/XML output that reintroduces one, and no-ops on a Turtle output,
        # where such a tag could not have been written in the first place.
        kgx_input_path = strip_invalid_lang_tags(stripped_path, ontology_name)

        # Transform to KGX nodes + edges
        outfilename = os.path.join(workdir, f"{ontology_name}")
        nodefilename = outfilename + "_nodes.tsv"
        edgefilename = outfilename + "_edges.tsv"
        # Provenance goes in input_args, not output_args. KGX reads it in
        # Transformer.transform as `source.parse(f, default_provenance=..., 
        # **input_args)`, and the sink never looks at it -- so the same keys set
        # on output_args, as they were, are silently dropped (#72). What KGX
        # falls back to when nothing is set is
        #
        #     default_provenance = os.path.basename(f)
        #
        # which is our own intermediate: every node and edge of all 1190
        # published graphs says it was provided by "<ACRONYM>_relaxed.owl", a
        # build artifact that does not exist anywhere outside a runner's temp
        # directory and identifies nothing about where the knowledge came from.
        #
        # So say it properly. The ontology is the primary source of its own
        # assertions; BioPortal is the aggregator we got them from. Both slots
        # take the same infores rather than the bare acronym on one and a
        # namespaced id on the other: these are knowledge-source slots in
        # Biolink, and the acronym is still recoverable from the value, from the
        # file name, and from the index.
        input_args = {
            "format": "owl",
            "filename": [kgx_input_path],
            "provided_by": ontology_infores(ontology_name),
            "primary_knowledge_source": ontology_infores(ontology_name),
            "aggregator_knowledge_source": AGGREGATOR_INFORES,
            # Teach KGX the SKOS properties the Biolink model does not name, so
            # a vocabulary that labels the SKOS way is not published nameless
            # (#173). See SKOS_PROPERTY_MAP for why prefLabel is kept apart.
            "predicate_mappings": dict(SKOS_PROPERTY_MAP),
            "node_property_predicates": list(SKOS_PROPERTY_MAP),
        }
        output_args = {
            "format": "tsv",
            "filename": outfilename,
            "node_properties": KGX_NODE_COLUMNS,
            "edge_properties": EDGE_COLUMNS,
        }
        logging.info("Doing KGX transform.")
        # Constructing the transformer is inside the try as well: it is part of
        # the KGX stage, and an exception raised out here would take down the
        # whole shard instead of costing one ontology.
        literals = LiteralConversionTally()
        try:
            with literals.installed():
                txr = KGXTransformer(stream=True)
                txr.transform(
                    input_args=input_args,
                    output_args=output_args,
                )
            logging.info(
                f"Nodes and edges written to {nodefilename} and {edgefilename}."
            )
            if literals.count:
                logging.warning(f"{ontology_name}: {literals.summary()}")
            # Take names from skos:prefLabel where rdfs:label left none, and
            # drop the scratch column, before anything else reads this file.
            adopted = adopt_pref_labels(nodefilename)
            if adopted:
                logging.info(
                    f"{ontology_name}: {adopted:,} nodes took their name from "
                    "skos:prefLabel"
                )
            # Put real Biolink categories on the nodes before anything counts
            # them (#169). This runs on the finished files rather than inside
            # the KGX stream because it needs the whole subclass hierarchy at
            # once, which a streaming source cannot offer.
            categorize(nodefilename, edgefilename, ontology_name)
            # Size and composition of what we just wrote, in one pass over each
            # file. The categories are logged here as well as recorded, so a
            # shard log says what came out of an ontology and not just how much
            # (#98).
            nodecount, node_categories = tally_column(nodefilename)
            edgecount, edge_categories = tally_column(edgefilename)
            logging.info(
                f"{ontology_name}: node categories: {format_tally(node_categories)}"
            )
            logging.info(
                f"{ontology_name}: edge categories: {format_tally(edge_categories)}"
            )

            # Compress if requested. Product is written flat at the top of the
            # output dir as <ACRONYM>.tar.gz for direct release upload.
            if compress:
                logging.info("Compressing nodes and edges.")
                tar_path = os.path.join(self.output_dir, f"{ontology_name}.tar.gz")
                with tarfile.open(tar_path, "w:gz") as tar:
                    tar.add(nodefilename, arcname=f"{ontology_name}_nodes.tsv")
                    tar.add(edgefilename, arcname=f"{ontology_name}_edges.tsv")

                os.remove(nodefilename)
                os.remove(edgefilename)

            # Remove the owl files
            # They may not exist if the transform failed
            for path in (
                intermediate_path,
                relax_input_path,
                relaxed_outpath,
                stripped_path,
                kgx_input_path,
            ):
                try:
                    os.remove(path)
                except OSError:
                    pass

        except Exception as e:
            logging.error(
                f"Error transforming {ontology_name} to KGX nodes and edges: {e}"
            )
            # The exception type carries as much as its message does when the
            # message is empty, which some of KGX's are.
            if literals.count:
                logging.warning(f"{ontology_name}: {literals.summary()}")
            return TransformOutcome.failed(
                "kgx",
                f"{type(e).__name__}: {e}",
                malformed_literals=literals.count,
            )

        return TransformOutcome(
            True,
            nodecount,
            edgecount,
            malformed_literals=literals.count,
            node_categories=node_categories,
            edge_categories=edge_categories,
        )

    def decompress(self, ontology_path: str, ontology_name: str) -> str:
        """Decompresses a downloaded ontology archive.

        Handles the three shapes BioPortal actually serves: a zip, a gzipped
        tarball, and a bare gzipped file. Archives holding several members are
        unpacked in full and the ontology is picked out of them (see
        ``pick_ontology_member``) rather than being refused.

        Args:
            ontology_path: Path to the compressed file.
            ontology_name: The ontology's acronym, used to name the extraction
                directory and to recognise the ontology among several members.

        Returns:
            Path to the file to transform, or ``ontology_path`` unchanged if the
            archive could not be decompressed — which the caller reads as failure.
        """
        logging.info(f"Decompressing {ontology_path}")
        extract_dir = os.path.join(self.input_dir, ontology_name)

        try:
            if ontology_path.endswith(".zip"):
                with zipfile.ZipFile(ontology_path, "r") as zip_ref:
                    _extract_all(zip_ref, extract_dir)
                    members = [
                        (i.filename, i.file_size)
                        for i in zip_ref.infolist()
                        if not i.is_dir()
                    ]
            elif tarfile.is_tarfile(ontology_path):
                # A .tar.gz (or any tarball); is_tarfile sniffs the content, so
                # this no longer depends on the file being named .tar.gz.
                with tarfile.open(ontology_path) as tar:
                    _extract_all(tar, extract_dir)
                    members = [(m.name, m.size) for m in tar.getmembers() if m.isfile()]
            elif ontology_path.endswith(".gz"):
                # A bare gzipped ontology, not a tarball. Opening this with
                # tarfile — as this used to — fails with "invalid header".
                os.makedirs(extract_dir, exist_ok=True)
                member = os.path.basename(ontology_path)[: -len(".gz")] or ontology_name
                out_path = os.path.join(extract_dir, member)
                with gzip.open(ontology_path, "rb") as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                members = [(member, os.path.getsize(out_path))]
            else:
                logging.error(f"Not a recognised archive: {ontology_path}")
                return ontology_path
        except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError) as e:
            # gzip.BadGzipFile is an OSError. Whatever the archive's problem,
            # it is this ontology's failure and not the run's.
            logging.error(f"Error when decompressing {ontology_path}: {e}")
            return ontology_path

        chosen = pick_ontology_member(members, ontology_name, ontology_path)
        if chosen is None:
            logging.error(f"No ontology file found inside {ontology_path} ({len(members)} members).")
            return ontology_path
        if len(members) > 1:
            logging.info(
                f"{ontology_name}: chose {chosen} from {len(members)} archive members."
            )
        return os.path.join(extract_dir, chosen)
