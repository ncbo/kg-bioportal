"""Transformer for KG-Bioportal."""

import logging
import os
import sys

from kg_bioportal.downloader import ONTOLOGY_LIST_NAME
from kg_bioportal.robot_utils import initialize_robot, robot_convert, robot_relax
from kgx.transformer import Transformer as KGXTransformer

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

        Args:
            None.

        Returns:
            None.
        """

        logging.info(
            f"Transforming all ontologies in {self.input_dir} to KGX nodes and edges."
        )

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
            if not self.transform(filepath):
                logging.error(f"Error transforming {filepath}.")
            else:
                logging.info(f"Transformed {filepath}.")

        return None

    def transform(self, ontology_path: str) -> bool:
        """Transforms a single ontology to KGX nodes and edges.

        Args:
            ontology: A string of the path to the ontology file to transform.

        Returns:
            True if transform was successful, otherwise False.
        """
        status = False

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
        except Exception as e:
            logging.error(f"Error transforming {ontology_name} to KGX nodes and edges: {e}")
            status = False

        return status
