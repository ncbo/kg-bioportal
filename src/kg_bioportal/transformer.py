"""Transformer for KG-Bioportal."""

import logging
import os
import sys
from typing import Tuple

import yaml
from kgx.transformer import Transformer as KGXTransformer

from kg_bioportal.downloader import ONTOLOGY_LIST_NAME
from kg_bioportal.robot_utils import initialize_robot, robot_convert, robot_relax

# TODO: Don't repeat steps if the products already exist
# TODO: Fix KGX hijacking logging
# TODO: Save KGX logs to a file for each ontology
# TODO: Address BNodes
# TODO: Assign IDs to edges when they lack them


class Transformer:

    def __init__(
        self,
        input_dir: str = "data/raw",
        output_dir: str = "data/tranformed",
    ) -> None:
        """Initializes the Transformer class.

        Also sets up ROBOT.

        Args:

            input_dir: A string pointing to the location of the raw data.

            output_dir: A string pointing to the location to download data to.

        Returns:
            None.
        """
        self.input_dir = input_dir
        self.output_dir = output_dir

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

    def transform_all(self) -> None:
        """Transforms all ontologies in the input directory to KGX nodes and edges.

        Yields two log files: total_stats.yaml and onto_stats.yaml.
        The first contains the total counts of Bioportal ontologies and transforms.
        The second contains the counts of nodes and edges for each ontology.

        Args:
            None.

        Returns:
            None.
        """

        logging.info(
            f"Transforming all ontologies in {self.input_dir} to KGX nodes and edges."
        )

        # This keeps track of the status of each transform.
        # Ontology acronym IDs are keys.
        # Values are dictionaries of:
        # status: True if transform was successful, otherwise False.
        # nodecount: Number of nodes in the ontology.
        # edgecount: Number of edges in the ontology.
        onto_log = {}

        filepaths = []
        for root, _dirs, files in os.walk(self.input_dir):
            for file in files:
                if not file.endswith(ONTOLOGY_LIST_NAME):
                    filepaths.append(os.path.join(root, file))

        if len(filepaths) == 0:
            logging.error(f"No ontologies found in {self.input_dir}.")
            sys.exit()
        else:
            logging.info(f"Found {len(filepaths)} ontologies to transform.")

        for filepath in filepaths:
            ontology_name = (os.path.relpath(filepath, self.input_dir)).split(os.sep)[0]
            success, nodecount, edgecount = self.transform(filepath)
            if not success:
                logging.error(f"Error transforming {filepath}.")
                status = False
                nodecount = 0
                edgecount = 0
            else:
                logging.info(f"Transformed {filepath}.")
                status = True
            if status == False:
                strstatus = "Failed"
            else:
                strstatus = "OK"
            onto_log[ontology_name] = {
                "status": strstatus,
                "nodecount": nodecount,
                "edgecount": edgecount,
            }

        # Write total stats to a yaml
        logging.info("Writing total stats to total_stats.yaml.")
        # Get the count of successful transforms
        success_count = 0
        for onto in onto_log:
            if onto_log[onto]["status"]:
                success_count += 1
        with open(os.path.join(self.output_dir, "total_stats.yaml"), "w") as f:
            f.write("totalcount: " + str(success_count) + "\n")

        # Dump onto_log to a yaml
        # Rearrange it a bit first
        logging.info("Writing ontology stats to onto_stats.yaml.")
        onto_stats_list = []
        for onto in onto_log:
            onto_stats_list.append(
                {
                    "id": onto,
                    "status": onto_log[onto]["status"],
                    "nodecount": onto_log[onto]["nodecount"],
                    "edgecount": onto_log[onto]["edgecount"],
                }
            )
        with open(os.path.join(self.output_dir, "onto_stats.yaml"), "w") as of:
            yaml.dump({"ontologies": onto_stats_list}, of)

        return None

    def transform(self, ontology_path: str) -> Tuple[bool, int, int]:
        """Transforms a single ontology to KGX nodes and edges.

        Args:
            ontology: A string of the path to the ontology file to transform.

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

        owl_output_path = os.path.join(
            self.output_dir,
            f"{ontology_name}",
            f"{ontology_submission_id}",
            f"{ontology_name}.owl",
        )

        # Convert
        if not robot_convert(
            robot_path=self.robot_path,
            input_path=ontology_path,
            output_path=owl_output_path,
            robot_env=self.robot_env,
        ):
            status = False

        # Relax
        relaxed_outpath = os.path.join(
            self.output_dir,
            f"{ontology_name}",
            f"{ontology_submission_id}",
            f"{ontology_name}_relaxed.owl",
        )
        if not robot_relax(
            robot_path=self.robot_path,
            input_path=owl_output_path,
            output_path=relaxed_outpath,
            robot_env=self.robot_env,
        ):
            status = False

        # Transform to KGX nodes + edges
        txr = KGXTransformer(stream=True)
        outfilename = os.path.join(
            self.output_dir,
            f"{ontology_name}",
            f"{ontology_submission_id}",
            f"{ontology_name}",
        )
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

        except Exception as e:
            logging.error(
                f"Error transforming {ontology_name} to KGX nodes and edges: {e}"
            )
            status = False

        return status, nodecount, edgecount
