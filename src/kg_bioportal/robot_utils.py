"""Functions for working with ROBOT."""

import os

import sh  # type: ignore
from sh import chmod  # type: ignore

from post_setup.post_setup import robot_setup

# Note that sh module can take environment variables, see
# https://amoffat.github.io/sh/sections/special_arguments.html#env


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
        robot_setup()

    # Make sure it's executable
    chmod("+x", "robot")

    # Declare environment variables
    env = os.environ.copy()
    env["ROBOT_JAVA_ARGS"] = "-Xmx12g -XX:+UseG1GC"  # For JDK 10 and over

    try:
        robot_command = sh.Command(robot_path)
    except sh.CommandNotFound:  # If for whatever reason ROBOT isn't available
        robot_command = None

    return [robot_command, env]


def relax_ontology(
    robot_path: str, input_path: str, output_path: str, robot_env: dict
) -> bool:
    """
    Run the ROBOT relax command on a single ontology.

    Has a three-hour timeout limit - process is killed if it takes this long.
    :param robot_path: Path to ROBOT files
    :param input_owl: Ontology file to be relaxed
    :param output_owl: Ontology file to be created (needs valid ROBOT suffix)
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    print(f"Relaxing {input_path} to {output_path}...")

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
            _timeout=10800,
        )
        print("Complete.")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
        success = False
    except sh.SignalException_SIGKILL as e:  # If ROBOT encounters severe error
        print(f"ROBOT crashed! {e}")
        success = False

    return success


def robot_convert(
    robot_path: str, input_path: str, output_path: str, robot_env: dict
) -> bool:
    """
    Run a ROBOT convert command on a single ontology.

    :param robot_path: Path to ROBOT files
    :param input_path: Ontology file to be relaxed
    :param output_path: Ontology file to be created (needs valid ROBOT suffix)
    :param robot_env: dict of environment variables, including ROBOT_JAVA_ARGS
    :return: True if completed without errors, False if errors
    """
    success = False

    print(f"Converting {input_path} to {output_path}...")

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
        )
        print("Complete.")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
        success = False
    except sh.SignalException_SIGKILL as e:  # If ROBOT encounters severe error
        print(f"ROBOT crashed! {e}")
        success = False

    return success


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

    print(f"Merging and converting {input_path} to {output_path}...")

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
        print("Complete.")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
        success = False
    except sh.SignalException_SIGKILL as e:  # If ROBOT encounters severe error
        print(f"ROBOT crashed! {e}")
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

    print(f"Obtaining metrics for {input_path}...")

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
        print(f"Complete. See log in {output_log}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
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

    print(f"Removing selected elements from {input_path}: {term}...")

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
        print(f"Complete. See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
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

    print(f"Generating ROBOT report for {input_path}...")

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
        print(f"No errors here! See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        # For report, this is expected, as the error may be
        # in the target ontology.
        print(f"ROBOT report results: {e}\nSee {output_path}")
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

    print(f"Generating ROBOT measure log for {input_path}...")

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
        print(f"Complete. See {output_path}")
        success = True
    except sh.ErrorReturnCode_1 as e:  # If ROBOT runs but returns an error
        print(f"ROBOT encountered an error: {e}")
        success = False

    return success
