"""Transform for ontologies."""

import gzip
import os
import shutil
from typing import Optional

from kgx.cli.cli_utils import transform  # type: ignore

from kg_bioportal.transform_utils.transform import Transform
from kg_bioportal.utils.robot_utils import convert_to_json

ONTOLOGIES = {"ChebiTransform": "chebi.owl.gz", "EnvoTransform": "envo.json"}


class OntologyTransform(Transform):
    """
    Parse an Obograph JSON form of an Ontology into nodes and edges.

    If it isn't in Obograph JSON format, it is transformed with ROBOT.
    If it needs to be decompressed, that happens here too.
    """

    def __init__(
        self, input_dir: Optional[str] = None, output_dir: Optional[str] = None
    ):
        """Initialize."""
        source_name = "ontologies"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Optional[str] = None) -> None:
        """Call method and performs needed transformations.

        Args:
            data_file: data file to parse
        Returns:
            None.
        """
        if data_file:  # if we specify a data file
            k = data_file.split(".")[0]
            data_file = os.path.join(self.input_base_dir, data_file)
            self.parse(k, data_file, k)
        else:
            # load all ontologies
            for k in ONTOLOGIES.keys():
                data_file = os.path.join(self.input_base_dir, ONTOLOGIES[k])
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: str, source: str) -> None:
        """Process the data_file.

        Args:
            name: Name of the ontology
            data_file: data file to parse
            source: Source name
        Returns:
             None.
        """
        print(f"Parsing {data_file}")

        # Decompress if needed
        if data_file[-3:] == ".gz":
            outfile = data_file[:-3]
            with gzip.open(data_file, "rb") as f_in:
                with open(outfile, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            data_file = outfile

        # Transform to obojson if needed
        # Need to set up ROBOT first
        if data_file[-4:] == ".owl":
            convert_to_json("data/raw/", "chebi")  # Use the downloaded ROBOT
            data_file = data_file[:-4] + ".json"

        transform(
            inputs=[data_file],
            input_format="obojson",
            output=os.path.join(self.output_dir, name),
            output_format="tsv",
        )
