"""Transformer for KG-Bioportal."""

import logging
import os


class Transformer:

    def __init__(
        self,
        input_dir: str = "data/raw",
        output_dir: str = "data/tranformed",
    ) -> None:
        """Initializes the Transformer class.

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

        return None
