#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from typing import List, Optional

from kg_bioportal.transform_utils.ontology import OntologyTransform
from kg_bioportal.transform_utils.ontology.ontology_transform import ONTOLOGIES

DATA_SOURCES = {"ChebiTransform": OntologyTransform, "EnvoTransform": OntologyTransform}


def transform(
    input_dir: str, output_dir: str, sources: Optional[List[str]] = None
) -> None:
    """Call scripts in kg_bioportal/transform/[source name]/ to transform each source into a graph format that
    KGX can ingest directly, in either TSV or JSON format:
    https://github.com/biolink/kgx/blob/master/specification/kgx-format.md

    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.
        sources: A list of sources to transform.

    Returns:
        None.

    """
    if not sources:
        # run all sources
        sources = list(DATA_SOURCES.keys())

    for source in sources:
        if source in DATA_SOURCES:
            logging.info(f"Parsing {source}")
            t = DATA_SOURCES[source](input_dir, output_dir)
            if source in ONTOLOGIES.keys():
                t.run(ONTOLOGIES[source])
            else:
                t.run()
