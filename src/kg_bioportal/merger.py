"""Merge functions for KG-Bioportal."""

import logging
import os
import sys
import tarfile
from typing import List, Tuple

from cat_merge.merge import merge as catmerge


class Merger:

    def __init__(
        self,
        input_dir: str = "data/transformed",
        output_dir: str = "data/merged",
    ) -> None:
        """Initializes the Merger class.

        This uses the cat_merge package to merge KGX nodes and edges.

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

        return None

    def merge_all(self) -> None:
        """Merges all ontologies in the input directory to a single graph.

        Yields one log files: merged_graph_stats.yaml.

        Args:
            compress: If True, compresses the output nodes and edges to tar.gz.

        Returns:
            None.
        """
        logging.info(
            f"Merging all ontology graphs in {self.input_dir} to single graph."
        )

        # This dict has a tuple of ontology name and submission ID as the key
        # And a list of node and edge file paths as the values.
        # This is also the step where we decompress the tar.gz files if they are present
        filepaths = {}
        for walkpath in os.walk(self.input_dir):
            if len(walkpath[1]) == 0:  # This is a leaf directory
                ontology_name = walkpath[0].split(os.sep)[-2]
                ontology_submission_id = walkpath[0].split(os.sep)[-1]
                files = walkpath[2]
                for file in files:
                    if (ontology_name, ontology_submission_id) not in filepaths:
                        filepaths[(ontology_name, ontology_submission_id)] = []
                    if file.endswith(".gz"):
                        decompressed_files = self.decompress(
                            ontology_path=os.path.join(walkpath[0], file),
                            ontology_name=ontology_name,
                            ontology_submission_id=ontology_submission_id,
                        )
                        filepaths[(ontology_name, ontology_submission_id)].extend(
                            decompressed_files
                        )
                    if file.endswith(".tsv"):
                        filepaths[(ontology_name, ontology_submission_id)].append(
                            os.path.join(walkpath[0], file)
                        )

        if len(filepaths) == 0:
            logging.error(f"No graphs found in {self.input_dir}.")
            sys.exit()
        else:
            logging.info(f"Found {len(filepaths)} ontologies to merge.")

        # Make a list of node and edge files, respectively
        nodelist = []
        edgelist = []
        for ontology in filepaths:
            nodelist.extend(
                [file for file in filepaths[ontology] if file.endswith("_nodes.tsv")]
            )
            edgelist.extend(
                [file for file in filepaths[ontology] if file.endswith("_edges.tsv")]
            )

        for filepath in filepaths:
            ontology_name = filepath[0]
            success, nodecount, edgecount = self.merge(nodelist, edgelist)
            if not success:
                logging.error("Error in merging.")
                status = False
            else:
                logging.info(f"Merge was successful.")
                status = True

        return None

    def merge(
        self, nodelist: List[str], edgelist: List[str]
    ) -> Tuple[bool, int, int]:
        """Merge graph files using cat_merge.

        Args:
            nodelist: A list of paths to node files to transform.
            edgelist: A list of paths to edge files to transform.
            compress: If True, compresses the output nodes and edges to tar.gz.

        Returns:
            Tuple of:
                True if transform was successful, otherwise False.
                Number of nodes in the merged graph.
                Number of edges in the merged graph.
        """
        status = False
        nodecount = 0
        edgecount = 0

        logging.info(
            f"Merging {len(nodelist)} node files and {len(edgelist)} edge files."
        )

        catmerge(
            name="kg_bioportal",
            nodes=nodelist,
            edges=edgelist,
            output_dir=self.output_dir,
            qc_report=True,
        )

        return status, nodecount, edgecount

    def decompress(
        self, ontology_path: str, ontology_name: str, ontology_submission_id: str
    ) -> List[str]:
        """Decompresses a compressed graph file.

        It expects to find just two files: a node file and an edge file.

        Args:
            ontology_path: A string of the path to the ontology file to decompress.
            ontology_name: A string of the name of the ontology.
            ontology_submission_id: A string of the submission ID of the ontology.

        Returns:
            A list of the paths to the decompressed files.
        """
        new_paths = []

        logging.info(f"Decompressing {ontology_path}")

        with tarfile.open(ontology_path, "r:gz") as tar:
            extract_dir = os.path.join(
                self.input_dir, ontology_name, ontology_submission_id
            )
            tar.extractall(extract_dir)
            extracted_files = tar.getnames()
            if len(extracted_files) == 2:
                for file in extracted_files:
                    new_paths.append(os.path.join(extract_dir, file))
            else:
                logging.error(
                    f"Expected two files in the tar archive, but found {len(extracted_files)}."
                )
                sys.exit(1)

        return new_paths
