"""Transformer for KG-Bioportal."""

import csv
import logging
import os
import re
import signal
import sys
import tarfile
import zipfile
from contextlib import contextmanager
from typing import Tuple

import yaml
from kgx.transformer import Transformer as KGXTransformer

from kg_bioportal.config import LICENSE_RESTRICTED_REASON, PER_ONTOLOGY_TIMEOUT_MIN
from kg_bioportal.downloader import DOWNLOAD_REPORT_NAME, ONTOLOGY_LIST_NAME
from kg_bioportal.robot_utils import initialize_robot, robot_convert, robot_relax

# TODO: Don't repeat steps if the products already exist
# TODO: Fix KGX hijacking logging
# TODO: Save KGX logs to a file for each ontology
# TODO: Address BNodes
# TODO: Assign IDs to edges when they lack them

# Files in the input dir that are not ontologies to transform.
_NON_ONTOLOGY_FILES = {ONTOLOGY_LIST_NAME, DOWNLOAD_REPORT_NAME}

# Patterns for ontology import declarations in the two XML serializations
# BioPortal serves most often: RDF/XML (<owl:imports .../>) and OWL/XML (<Import>...</Import>).
_IMPORT_PATTERNS = [
    re.compile(r"[ \t]*<owl:imports\b[^>]*/>[ \t]*\n?"),
    re.compile(r"[ \t]*<owl:imports\b[^>]*>.*?</owl:imports>[ \t]*\n?", re.S),
    re.compile(r"[ \t]*<(?:owl:)?Import\b[^>]*>.*?</(?:owl:)?Import>[ \t]*\n?", re.S),
]


def strip_imports(path: str) -> str:
    """Remove owl:imports / OWL-XML <Import> declarations from an ontology file.

    ROBOT (via the OWL API) tries to resolve owl:imports over the network when it
    loads an ontology; when an import URL is dead, slow, or unreachable from the
    runner the whole convert/relax fails (UnloadableImportException). This is the
    dominant KG-Bioportal transform failure. Each ontology is transformed on its
    own, so imports are not needed — references to imported terms just become
    dangling edges, resolved later at merge time.

    Only XML serializations (RDF/XML, OWL/XML) are handled. Returns the path to a
    cleaned sibling file, or the original path if nothing was removed / the file
    isn't an XML serialization we recognize.

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

    head = text[:400].lstrip().lower()
    if not (head.startswith("<?xml") or "<rdf:rdf" in head or "<ontology" in head):
        return path  # not an XML serialization we handle (e.g. obo, ttl)

    cleaned = text
    removed = 0
    for pattern in _IMPORT_PATTERNS:
        cleaned, n = pattern.subn("", cleaned)
        removed += n
    if removed == 0:
        return path

    base, ext = os.path.splitext(path)
    new_path = f"{base}_noimports{ext or '.owl'}"
    with open(new_path, "w", encoding="utf-8") as f:
        f.write(cleaned)
    logging.info(f"Stripped {removed} import declaration(s) from {os.path.basename(path)}.")
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


class TransformTimeout(Exception):
    """Raised when a single ontology transform exceeds its wall-clock budget."""


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
    ) -> None:
        """Initializes the Transformer class.

        Also sets up ROBOT.

        Args:
            input_dir: A string pointing to the location of the raw data.
            output_dir: A string pointing to the location to write products to.
            timeout_min: Per-ontology wall-clock cap in minutes. An ontology that
                runs longer is killed and recorded as skipped (too_slow).

        Returns:
            None.
        """
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.timeout_min = timeout_min
        self.timeout_sec = int(timeout_min * 60)

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
        its status (OK / Failed / Skipped) and the reason for any skip.

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
            try:
                with deadline(self.timeout_sec):
                    success, nodecount, edgecount = self.transform(filepath, compress)
            except TransformTimeout:
                logging.error(
                    f"Transform of {ontology_name} exceeded {self.timeout_min} min; skipping."
                )
                success, nodecount, edgecount = False, 0, 0
                reason = "too_slow"

            if not success:
                logging.error(f"Error transforming {filepath}.")
                strstatus = "Skipped" if reason == "too_slow" else "Failed"
                nodecount = 0
                edgecount = 0
                if not reason:
                    reason = "transform_error"
            else:
                logging.info(f"Transformed {filepath}.")
                strstatus = "OK"

            onto_log[ontology_name] = {
                "status": strstatus,
                "reason": reason,
                "name": report_row.get("name", ""),
                "version": report_row.get("version", ""),
                "nodecount": nodecount,
                "edgecount": edgecount,
                "submission_id": report_row.get("submission_id", "NA"),
                "source_bytes": int(report_row.get("source_bytes") or 0),
            }

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

    def transform(self, ontology_path: str, compress: bool) -> Tuple[bool, int, int]:
        """Transforms a single ontology to KGX nodes and edges.

        The compressed product is written flat as ``<output_dir>/<ACRONYM>.tar.gz``
        so it can be uploaded directly as a GitHub Release asset.

        Args:
            ontology_path: A string of the path to the ontology file to transform.
            compress: If True, compresses the output nodes and edges to tar.gz.

        Returns:
            Tuple of:
                True if transform was successful, otherwise False.
                Number of nodes in the ontology.
                Number of edges in the ontology.
        """
        status = False
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
                return False, nodecount, edgecount

        # Remove owl:imports so ROBOT doesn't try (and fail) to fetch external
        # ontologies over the network — the dominant cause of transform errors.
        # Each ontology is transformed standalone; references to imported terms
        # simply become dangling edges, resolved later at merge time.
        ontology_path = strip_imports(ontology_path)

        # Convert
        if not robot_convert(
            robot_path=self.robot_path,
            input_path=ontology_path,
            output_path=owl_output_path,
            robot_env=self.robot_env,
            timeout=self.timeout_sec,
        ):
            return False, nodecount, edgecount

        # Relax
        relaxed_outpath = os.path.join(workdir, f"{ontology_name}_relaxed.owl")
        if not robot_relax(
            robot_path=self.robot_path,
            input_path=owl_output_path,
            output_path=relaxed_outpath,
            robot_env=self.robot_env,
            timeout=self.timeout_sec,
        ):
            return False, nodecount, edgecount

        # Transform to KGX nodes + edges
        txr = KGXTransformer(stream=True)
        outfilename = os.path.join(workdir, f"{ontology_name}")
        nodefilename = outfilename + "_nodes.tsv"
        edgefilename = outfilename + "_edges.tsv"
        input_args = {
            "format": "owl",
            "filename": [relaxed_outpath],
        }
        output_args = {
            "format": "tsv",
            "filename": outfilename,
            "provided_by": ontology_name,
            "aggregator_knowledge_source": "infores:bioportal",
        }
        logging.info("Doing KGX transform.")
        try:
            txr.transform(
                input_args=input_args,
                output_args=output_args,
            )
            logging.info(
                f"Nodes and edges written to {nodefilename} and {edgefilename}."
            )
            status = True

            # Get length of nodefile
            with open(nodefilename, "r") as f:
                nodecount = len(f.readlines()) - 1

            # Get length of edgefile
            with open(edgefilename, "r") as f:
                edgecount = len(f.readlines()) - 1

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
            for path in (owl_output_path, relaxed_outpath):
                try:
                    os.remove(path)
                except OSError:
                    pass

        except Exception as e:
            logging.error(
                f"Error transforming {ontology_name} to KGX nodes and edges: {e}"
            )
            return False, nodecount, edgecount

        return status, nodecount, edgecount

    def decompress(self, ontology_path: str, ontology_name: str) -> str:
        """Decompresses a compressed ontology file.

        Args:
            ontology_path: A string of the path to the ontology file to decompress.

        Returns:
            The path to the decompressed file.
        """
        new_path = self.input_dir

        logging.info(f"Decompressing {ontology_path}")
        try:
            if ontology_path.endswith(".zip"):
                with zipfile.ZipFile(ontology_path, "r") as zip_ref:
                    extract_dir = os.path.join(self.input_dir, ontology_name)
                    zip_ref.extractall(extract_dir)
                    extracted_files = zip_ref.namelist()
                    if len(extracted_files) == 1:
                        new_path = os.path.join(extract_dir, extracted_files[0])
                    else:
                        logging.error(
                            f"Expected one file in the zip archive, but found {len(extracted_files)}."
                        )
                        return ontology_path
            elif ontology_path.endswith(".gz"):
                with tarfile.open(ontology_path, "r:gz") as tar:
                    extract_dir = os.path.join(self.input_dir, ontology_name)
                    tar.extractall(extract_dir)
                    extracted_files = tar.getnames()
                    if len(extracted_files) == 1:
                        new_path = os.path.join(extract_dir, extracted_files[0])
                    else:
                        logging.error(
                            f"Expected one file in the tar archive, but found {len(extracted_files)}."
                        )
                        return ontology_path
        except tarfile.ReadError as e:
            logging.error(f"Error when decompressing {ontology_path}: {e}")
            return ontology_path

        return new_path
