import uuid

from biolink_model_pydantic.model import ( #type: ignore
    ChemicalEntity,
    Pathway,
    ChemicalToPathwayAssociation,
    Predicate,
)

from koza.cli_runner import koza_app #type: ignore

source_name="chebi2reactome"
full_source_name="Reactome"

row = koza_app.get_row(source_name)

# Entities
chemical = ChemicalEntity(id='CHEBI:' + row['CHEBI_ID'])
pathway = Pathway(id='REACT:' + row['REACT_PATH_ID'],
                    source=full_source_name)

# Association
association = ChemicalToPathwayAssociation(
    id="uuid:" + str(uuid.uuid1()),
    subject=chemical.id,
    predicate=Predicate.participates_in,
    object=pathway.id,
    relation = koza_app.translation_table.resolve_term("pathway"),
    source=full_source_name
)

koza_app.write(chemical, association, pathway)
