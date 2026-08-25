"""Functions for working with ROBOT."""

import os
import logging
import re
import requests
import sh  # type: ignore
from sh import chmod  # type: ignore

from typing import NamedTuple

from kg_bioportal.config import ROBOT_JAVA_ARGS

# Note that sh module can take environment variables, see
# https://amoffat.github.io/sh/sections/special_arguments.html#env

# How much of a ROBOT error to carry back. Enough for the exception and its
# cause chain, which is one line; the stack trace below it says nothing about
# the ontology.
_MAX_ERROR_CHARS = 500


class RobotResult(NamedTuple):
    """Whether a ROBOT command succeeded, and what it said if it didn't.

    Truthy exactly when the command succeeded, so ``if not robot_convert(...)``
    reads the same as it did when these returned a bare bool -- the error text
    is there for a caller that wants to record *why* (#134).
    """

    ok: bool
    error: str = ""

    def __bool__(self) -> bool:
        return self.ok


# Lines the JVM and its logging frameworks write to stderr before ROBOT gets a
# word in. Whichever of these a runner happens to emit is not the failure.
_JVM_NOISE = (
    "Picked up JAVA_TOOL_OPTIONS",
    "Picked up _JAVA_OPTIONS",
    "Picked up JAVA_OPTIONS",
    "SLF4J:",
    "log4j:",
    "OpenJDK",
    "Java HotSpot",
    "WARNING: ",
)

# A Java throwable, or anything shouting ERROR -- what ROBOT's failures look
# like: "java.lang.IllegalArgumentException: ...UnloadableImportException: ..."
# or "java.io.IOException: errors#INVALID ONTOLOGY FILE ERROR ...".
_THROWABLE = re.compile(r"\b[\w.$]*(?:Exception|Error|ERROR)\b")

# A cause that points into the file: an OWL API parser position ("[line=26:
# column=46]"), a SAX one ("lineNumber: 27"), or the "at line 4 of" a Turtle or
# functional-syntax parser writes. A stack frame never carries one of these,
# which is what makes it a usable filter for the reason among the noise.
_POSITIONED_REASON = re.compile(
    r"\[line=\d+|lineNumber:\s*\d+|\bat line \d+|\bat index \d+", re.I
)

# ROBOT's logging appends the first stack element to the message line itself,
# after a run of spaces: "...Malformed escape pair at index 15        org.
# semanticweb.owlapi.rdf.rdfxml.parser.RDFXMLParser.parse(RDFXMLParser.java:74)".
# It identifies nothing about the ontology and it is the longest part of the
# line, so it is cut before the 500-character budget is spent on it.
_STACK_TAIL = re.compile(r"\s{2,}\S*\(\w+\.\w+:\d+\).*$")

# Enough of stderr to find the error in; a stack trace that deep is not hiding
# a better line further down.
_MAX_ERROR_LINES = 200


def _output_written(output_path: str) -> str:
    """Why a ROBOT command's output is unusable, or "" if it is fine.

    A command that exits 0 having written nothing is not a success, and saying
    so here keeps the blame with the step that produced the file rather than the
    next one to read it (#141). It is not hypothetical that the next step would
    swallow it: ROBOT reads a zero-byte file as a valid *empty* ontology, so an
    empty intermediate transforms all the way to a graph with nothing in it.
    """
    if not os.path.exists(output_path):
        return (f"ROBOT exited cleanly but wrote no output file "
                f"({os.path.basename(output_path)})")
    if os.path.getsize(output_path) == 0:
        return (f"ROBOT exited cleanly but wrote an empty output file "
                f"({os.path.basename(output_path)})")
    return ""


def _error_text(e: Exception) -> str:
    """The part of a ROBOT failure worth keeping.

    ROBOT writes its verbose (-vvv) log to stdout and the failure to stderr,
    where one line carries the exception and its cause chain --
    "java.lang.IllegalArgumentException: ...UnloadableImportException: Could not
    load imported ontology: <url>". Everything under it is a stack trace through
    OWL API internals, which identifies nothing about the ontology, and anything
    above it is the JVM clearing its throat.

    That top line is enough when it names the cause, and useless when it does
    not. A file ROBOT cannot read reports only "INVALID ONTOLOGY FILE ERROR
    Could not load a valid ontology from file: X" -- true of every unreadable
    file there has ever been. The reason is further down, because the OWL API
    tries each parser in turn and collects their complaints under
    UnparsableOntologyException:

        [line=26:column=46] IRI 'http://ex.org/a%b' cannot be resolved against
        current base IRI http://ex.org/o reason is: Malformed escape pair

    That is the line that says which ontology, and where in it. So keep the top
    line, and append the first line below it that points at a position in the
    file -- the one thing a stack frame never does.
    """
    stderr = getattr(e, "stderr", b"") or b""
    if isinstance(stderr, (bytes, bytearray)):
        stderr = stderr.decode("utf-8", "replace")

    head = ""
    fallback = ""
    for line in stderr.splitlines()[:_MAX_ERROR_LINES]:
        line = line.strip()
        if not line or line.startswith(("at ", "... ")) or line.startswith(_JVM_NOISE):
            continue
        line = _STACK_TAIL.sub("", line).strip()
        if not line:
            continue
        if not head:
            if _THROWABLE.search(line):
                head = line
                continue
            fallback = fallback or line
            continue
        # Past the headline: the only thing left worth adding is a reason that
        # names a place. Take the first, then stop -- the parsers after it are
        # complaining about the same file in their own syntax.
        if _POSITIONED_REASON.search(line) and line not in head:
            return f"{head} | {line}"[:_MAX_ERROR_CHARS]
    return (head or fallback or str(e).strip())[:_MAX_ERROR_CHARS]


def initialize_robot(robot_path: str) -> list:
    """
    Initialize ROBOT with necessary configuration.

    During install, ROBOT is downloaded to the root project directory,
    and the path variable used here is only necessary if it varies from
    the project location.
    :param path: Path to ROBOT files.
    :return: A list consisting an instance of Command and
    dict of all environment variables.
    """
    # We may have made it this far without installing ROBOT,
    # so do that now if needed
    if not os.path.exists(robot_path):
        logging.info("ROBOT not found. Downloading...")
        robot_url = "https://raw.githubusercontent.com/ontodev/robot/master/bin/robot"
        robot_jar_url = "https://github.com/ontodev/robot/releases/download/v1.9.6/robot.jar"
        robot_ex = requests.get(robot_url)
        robot_jar = requests.get(robot_jar_url)
        with open("robot", "wb") as f:
            f.write(robot_ex.content)
        with open("robot.jar", "wb") as f:
            f.write(robot_jar.content)

        # Make sure it's executable
        chmod("+x", "robot")

    # Declare environment variables. Heap/GC args come from config, which reads
    # the ROBOT_JAVA_ARGS environment variable if set (so CI can size the heap
    # to the runner) and otherwise falls back to a sane default.
    env = os.environ.copy()
    env["ROBOT_JAVA_ARGS"] = ROBOT_JAVA_ARGS  # For JDK 10 and over

    try:
        robot_command = sh.Command(robot_path)
    except sh.CommandNotFound:  # If for whatever reason ROBOT isn't available
        robot_command = None

    return [robot_command, env]


def robot_relax(
    robot_path: str,
    input_path: str,
    output_path: str,
    robot_env: dict,
    timeout: int = 10800,
) -> RobotResult:
    """
    Run the ROBOT relax command on a single ontology.

    :param robot_path: Path to ROBOT files
    :param input_owl: Ontology file to be relaxed
    :param output_owl: Ontology file to be created (needs valid ROBOT suffix)
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :param timeout: Wall-clock limit in seconds; the process is killed if exceeded.
    :return: RobotResult -- truthy if completed without errors, carrying the
        error text if not.
    """
    logging.info(f"Relaxing {input_path} to {output_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "relax",
            "--input",
            input_path,
            "--output",
            output_path,
            "-vvv",
            _env=robot_env,
            _timeout=timeout,
        )
        logging.info("Complete.")
        unusable = _output_written(output_path)
        if unusable:
            logging.error(unusable)
            return RobotResult(False, unusable)
        return RobotResult(True)
    # SignalException subclasses ErrorReturnCode, so it has to be caught first
    # or a kill reads as an ordinary nonzero exit and reports a stderr that a
    # killed process never got to write.
    except sh.SignalException_SIGKILL:  # If ROBOT encounters severe error
        error = "ROBOT was killed (SIGKILL); the runner most likely ran out of memory"
        logging.error(error)
    # The base class, not ErrorReturnCode_1: a nonzero exit of any other code is
    # recorded as a failure rather than taking the whole shard down with it.
    except sh.ErrorReturnCode as e:  # If ROBOT runs but returns an error
        error = _error_text(e)
        logging.error(f"ROBOT encountered an error: {error}")
    except sh.TimeoutException:  # If ROBOT exceeded the wall-clock limit
        error = f"ROBOT relax timed out after {timeout}s"
        logging.error(error)

    return RobotResult(False, error)


def robot_convert(
    robot_path: str,
    input_path: str,
    output_path: str,
    robot_env: dict,
    timeout: int = 10800,
) -> RobotResult:
    """
    Run a ROBOT convert command on a single ontology.

    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file to be relaxed
    :param output_path: Ontology file to be created (needs valid ROBOT suffix)
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :param timeout: Wall-clock limit in seconds; the process is killed if exceeded.
    :return: RobotResult -- truthy if completed without errors, carrying the
        error text if not.
    """
    logging.info(f"Converting {input_path} to {output_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "convert",
            "--input",
            input_path,
            "--output",
            output_path,
            "-vvv",
            _env=robot_env,
            _timeout=timeout,
        )
        logging.info("Complete.")
        unusable = _output_written(output_path)
        if unusable:
            logging.error(unusable)
            return RobotResult(False, unusable)
        return RobotResult(True)
    # SignalException subclasses ErrorReturnCode, so it has to be caught first
    # or a kill reads as an ordinary nonzero exit and reports a stderr that a
    # killed process never got to write.
    except sh.SignalException_SIGKILL:  # If ROBOT encounters severe error
        error = "ROBOT was killed (SIGKILL); the runner most likely ran out of memory"
        logging.error(error)
    # The base class, not ErrorReturnCode_1: a nonzero exit of any other code is
    # recorded as a failure rather than taking the whole shard down with it.
    except sh.ErrorReturnCode as e:  # If ROBOT runs but returns an error
        error = _error_text(e)
        logging.error(f"ROBOT encountered an error: {error}")
    except sh.TimeoutException:  # If ROBOT exceeded the wall-clock limit
        error = f"ROBOT convert timed out after {timeout}s"
        logging.error(error)

    return RobotResult(False, error)


def merge_and_convert_ontology(
    robot_path: str, input_path: str, output_path: str, robot_env: dict
) -> bool:
    """
    Run a merge and convert ROBOT command on a single ontology.

    Has a three-hour timeout limit - process is killed if it takes this long.
    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file to be relaxed
    :param output_path: Ontology file to be created (needs valid ROBOT suffix)
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    logging.info(f"Merging and converting {input_path} to {output_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "merge",
            "--input",
            input_path,
            "convert",
            "--output",
            output_path,
            "-vvv",
            _env=robot_env,
            _timeout=10800,
        )
        logging.info("Complete.")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        logging.error(f"ROBOT encountered an error: {e}")
        success = False
    except sh.SignalException_SIGKILL as e:  # If ROBOT encounters severe error
        logging.error(f"ROBOT crashed! {e}")
        success = False

    return success


def measure_ontology(
    robot_path: str, input_path: str, output_log: str, robot_env: dict
) -> bool:
    """
    Run the ROBOT measure command on a single ontology.

    Yield all metrics as string and as a log file.
    :param robot_path: Path to ROBOT files
    :param input_owl: Ontology file to be validated
    :param output_owl: Location of log file to be created
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    logging.info(f"Obtaining metrics for {input_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "measure",
            "--input",
            input_path,
            "--format",
            "tsv",
            "--metrics",
            "all",
            "--output",
            output_log,
            _env=robot_env,
        )
        logging.info(f"Complete. See log in {output_log}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        logging.error(f"ROBOT encountered an error: {e}")
        success = False

    return success


def robot_remove(
    robot_path: str,
    input_path: str,
    output_path: str,
    term: str,
    robot_env: dict
) -> bool:
    """
    Run the ROBOT remove command on a single ontology.

    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file for input
    :param output_path: Ontology file to be created (needs valid ROBOT suffix)
    :param term: term to select for removal
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    logging.info(f"Removing selected elements from {input_path}: {term}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "remove",
            "-vvv",
            "--input",
            input_path,
            "--term",
            term,
            "--output",
            output_path,
            _env=robot_env,
        )
        logging.info(f"Complete. See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        logging.error(f"ROBOT encountered an error: {e}")
        success = False

    return success


def robot_report(
    robot_path: str, input_path: str, output_path: str, robot_env: dict
) -> bool:
    """
    Run the ROBOT report command on a single ontology.

    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file for input
    :param output_path: Path to create report at
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    logging.info(f"Generating ROBOT report for {input_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "report",
            "--input",
            input_path,
            "--output",
            output_path,
            "--format",
            "tsv",
            _env=robot_env,
        )
        logging.info(f"No errors here! See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        # For report, this is expected, as the error may be
        # in the target ontology.
        logging.error(f"ROBOT report results: {e}\nSee {output_path}")
        success = False

    return success


def robot_measure(
    robot_path: str, input_path: str, output_path: str, robot_env: dict
) -> bool:
    """
    Run the ROBOT measure command on a single ontology, returning all metrics.

    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file for input
    :param output_path: Path to create measure log at
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    logging.info(f"Generating ROBOT measure log for {input_path}...")

    robot_command = sh.Command(robot_path)

    try:
        robot_command(
            "measure",
            "-vvv",
            "--input",
            input_path,
            "--output",
            output_path,
            "--format",
            "tsv",
            "--metrics",
            "all",
            _env=robot_env,
        )
        logging.info(f"Complete. See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        logging.error(f"ROBOT encountered an error: {e}")
        success = False

    return success
