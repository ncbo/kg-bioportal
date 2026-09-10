"""Assign Biolink categories to the nodes of a transformed ontology (#169).

KGX writes ``biolink:NamedThing`` on every node, because a plain OWL file says
nothing about Biolink and that is the honest default for a transcriber to pick.
Deciding what these particular ontologies mean in Biolink terms is a
KG-Bioportal judgement, not KGX's and not the model toolkit's -- giving the
collection one consistent structure is much of what this pipeline is for -- so
it happens here, over the node and edge files KGX has just written.

Two sources of evidence, both already present in that output:

**The subclass hierarchy.** Label a term whose meaning is not in doubt, and
every class beneath it inherits. Measured over 12 graphs from release
``data-2026.08.25-12``, the top subclass root alone reaches 96.8% of VTO,
92.0% of ERO, 87.4% of MONDO's own classes and 81.6% of AGRO; three roots reach
70.5% of GO-PLUS. The roots are largely shared, because these ontologies import
the same upper ontologies, which is why one modest seed table goes a long way.

**Mappings.** An ``exact_match`` edge asserts the same referent, so a category
carries across it. This matters more than it sounds: 74.6% of MONDO's 148,965
nodes are mapping *targets* -- UMLS CUIs, ICD IRIs, MedGen, SNOMED -- rather
than MONDO classes, and having no subclass edges at all they are exactly the
population the hierarchy cannot reach. Propagating outward from the ontology's
own classes also means no external table is needed: the earlier idea of going
the other way, from a CUI's UMLS semantic type, would have required MRSTY and
its licence. That direction remains open as a fallback for the ontologies whose
own classes never get a category.

**Reviewed roots.** The seed table above holds terms whose Biolink meaning
is not in doubt. Much of what is left uncategorized hangs off roots that need
a judgement about one ontology: ICD9CM's chapters, HGNC's locus groups, SNMI's
axes. Those judgements were made by reading each root and its subclasses, with
the assistance of an AI agent, and are kept in ``reviewed_roots.yaml`` beside
this module rather than in the table -- with the reviewer, the date, the
evidence read, and whether a maintainer has confirmed them. The roll-up treats
a reviewed root exactly as a seed. What differs is the record: a node whose
category traces to a reviewed root is counted apart, and that count reaches
the index and the site so the provenance is visible wherever the category is.
See ``REVIEW_BAR`` for what a root has to show before it is accepted.

Edges are left at ``biolink:Association``. See ``ASSOCIATION_NOTE``.
"""

import collections
import logging
import os
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

import yaml

# The root Biolink class, which is what KGX writes and what a node keeps when
# nothing below establishes anything more specific.
NAMED_THING = "biolink:NamedThing"

# Why edges are not given a specific association class here. Biolink keys its
# association classes on the subject/object category pair, so in principle they
# follow from the node categories -- but the toolkit does not resolve one
# answer. bmt 4.4.4's get_associations returns candidates that are ambiguous
# (organism taxon -> organism taxon yields "taxon to taxon association",
# "organism taxon to organism taxon association", "... specialization" and
# "... interaction", which only the predicate's meaning separates) and
# sometimes plainly wrong (chemical entity -> chemical entity yields "gene
# regulates gene association"). subclass_of, which is most of our edges, maps
# to the bare "association". Picking one anyway would put a claim in the data
# that the data does not support, so the edge half of #169 stays open.
ASSOCIATION_NOTE = (
    "edge categories are unchanged: Biolink's association classes cannot be "
    "resolved from a category pair alone"
)

SUBCLASS_PREDICATE = "biolink:subclass_of"

# Predicates that put one term beneath another, and which end is the parent.
# SKOS vocabularies have no subclass axioms at all; their whole hierarchy is
# skos:broader (NLMVS carries 119,942 of them and not one subclass_of), so a
# roll-up that reads only subclass_of sees a flat file. narrower is broader
# written from the other end; both are read so a vocabulary that asserts only
# one of them is not missed.
HIERARCHY_PREDICATES: Dict[str, str] = {
    SUBCLASS_PREDICATE: "object",   # subject subclass_of object: object is the parent
    "skos:broader": "object",       # subject broader object: object is the parent
    "skos:narrower": "subject",     # subject narrower object: subject is the parent
}

# Predicates that assert the same referent, so a category is true of both ends.
# close_match is deliberately absent: "close" is not "same", and treating it as
# such would push categories across boundaries the source was careful about.
MAPPING_PREDICATES = frozenset({"biolink:exact_match", "biolink:same_as"})

# Terms whose Biolink category is not in doubt, and which sit high enough in
# their ontology to carry a subtree. Seeded deliberately *below* the literal
# top: owl:Thing and BFO:0000001 "entity" are the top roots of several
# ontologies in the sample and are useless here -- rolling up from them only
# re-derives NamedThing.
#
# Written in the canonical OBO CURIE form; see canonical_forms() for the other
# shapes the same term arrives in.
SEEDS: Dict[str, str] = {
    # -- anatomy, cells, organisms
    "UBERON:0001062": "biolink:AnatomicalEntity",    # anatomical entity
    "CL:0000000": "biolink:Cell",                    # cell
    "NCBITaxon:1": "biolink:OrganismTaxon",          # root
    "VTO:0000001": "biolink:OrganismTaxon",          # Chordata (VTO's root)
    "TTO:0": "biolink:OrganismTaxon",                # Chordata (TTO's root)  38,639
    "UBERON:0000105": "biolink:LifeStage",           # life cycle stage
    # Species anatomy ontologies, each rooted at its own "anatomical entity".
    # Reach measured on data-2026.09.09.
    "ZFA:0100000": "biolink:AnatomicalEntity",       # zebrafish anatomical entity
    "XAO:0000000": "biolink:AnatomicalEntity",       # Xenopus anatomical entity
    "FBbt:10000000": "biolink:AnatomicalEntity",     # anatomical entity (fly)  27,140
    # -- function, process, component
    "GO:0008150": "biolink:BiologicalProcessOrActivity",   # biological_process
    "GO:0003674": "biolink:BiologicalProcessOrActivity",   # molecular_function
    "GO:0005575": "biolink:CellularComponent",             # cellular_component
    # -- disease and phenotype
    "MONDO:0000001": "biolink:Disease",
    "MONDO:0042489": "biolink:Disease",              # disease susceptibility
    "DOID:4": "biolink:Disease",
    "HP:0000118": "biolink:PhenotypicFeature",       # phenotypic abnormality
    "MP:0000001": "biolink:PhenotypicFeature",
    "UPHENO:0001001": "biolink:PhenotypicFeature",
    # Species phenotype ontologies, each rooted at its own "phenotype". Their
    # base graphs do not reach UPHENO's root because the imports are stripped.
    "ZP:0000000": "biolink:PhenotypicFeature",       # Zebrafish Phenotype   43,521
    "XPO:0000000": "biolink:PhenotypicFeature",      # Xenopus phenotype     21,196
    "FLOPO:0000000": "biolink:PhenotypicFeature",    # flora phenotype       11,680
    "FYPO:0000001": "biolink:PhenotypicFeature",     # phenotype (yeast)      8,311
    # -- chemistry and molecules
    "CHEBI:24431": "biolink:ChemicalEntity",         # chemical entity
    "PR:000018263": "biolink:Polypeptide",           # amino acid chain (PR's root)
    "PR:000000001": "biolink:Protein",               # protein
    "SO:0000110": "biolink:NucleicAcidEntity",       # sequence_feature
    "GO:0032991": "biolink:MacromolecularComplex",   # protein-containing complex
    # -- environment and food
    "ENVO:00002297": "biolink:EnvironmentalFeature", # environmental feature
    "ENVO:01000254": "biolink:EnvironmentalFeature", # environmental system
    "FOODON:00001002": "biolink:Food",               # food material
    # -- information, publications, samples
    "IAO:0000013": "biolink:Publication",            # journal article
    "IAO:0000310": "biolink:Publication",            # document
    "OBI:0000011": "biolink:Procedure",              # planned process
    "OBI:0100051": "biolink:MaterialSample",         # specimen
    "ECO:0000000": "biolink:EvidenceType",           # evidence
    # -- roots that carry a large ontology on their own, found by looking at
    #    where the uncategorized nodes actually were after the first pass. Each
    #    reaches the number of nodes noted, measured on data-2026.08.26-16.
    "GNO:00000001": "biolink:ChemicalEntity",        # glycan            191,529
    "CAT:0000000": "biolink:ChemicalEntity",         # lipid classification 63,306
    "SO:0000704": "biolink:Gene",                    # gene
    "SO:0000340": "biolink:NucleicAcidEntity",       # chromosome
    "PW:0000001": "biolink:Pathway",                 # pathway
    "CLO:0000031": "biolink:CellLine",               # cell line
    "CHEBI:23367": "biolink:MolecularEntity",        # molecular entity
    "NCBITaxon:131567": "biolink:OrganismTaxon",     # cellular organisms
    # NCIt's top-level kinds. NCIt itself is on the skip list, but its classes
    # are reused by other ontologies (OMCO hangs 8,799 cancers off C9292), and
    # they arrive both as NCIT: CURIEs and under the EVS Thesaurus IRI -- see
    # canonical_forms. Labels checked against BioPortal's NCIT on 2026-09-10.
    "NCIT:C2991": "biolink:Disease",                 # Disease or Disorder
    "NCIT:C3262": "biolink:Disease",                 # Neoplasm
    "NCIT:C9292": "biolink:Disease",                 # Solid Neoplasm
    "NCIT:C7057": "biolink:DiseaseOrPhenotypicFeature",  # Disease, Disorder or Finding
    "NCIT:C12219": "biolink:AnatomicalEntity",       # Anatomic Structure, System, or Substance
    "NCIT:C12508": "biolink:Cell",                   # Cell
    "NCIT:C14250": "biolink:OrganismTaxon",          # Organism
    "NCIT:C16612": "biolink:Gene",                   # Gene
    "NCIT:C17021": "biolink:Protein",                # Protein
    "NCIT:C17828": "biolink:BiologicalProcess",      # Biological Process
    "NCIT:C25218": "biolink:Procedure",              # Clinical Intervention or Procedure
    "NCIT:C20189": "biolink:Attribute",              # Property or Attribute
    "NCIT:C43431": "biolink:Activity",               # Activity
    "NCIT:C1909": "biolink:ChemicalEntity",          # Pharmacologic Substance
    # Roots that carry no label, or whose label alone does not settle it, and
    # that were placed by reading their subclasses -- OMIT, SIO, FMA, CCF, ITO,
    # HOOM, RCTV2 -- are not here. They are judgements about one ontology, made
    # with an AI agent's help, and live in reviewed_roots.yaml with that said.
}

# Upper-ontology terms, kept apart because they are a *last resort*. Nearly
# every OBO ontology imports BFO, so these reach a great deal -- but they reach
# it from above, and where a domain seed also applies the domain seed is the
# better answer. Distance alone does not express that: "material anatomical
# entity" is one step below UBERON's "anatomical entity" and one step below
# BFO's "material entity", so the tie has to be broken by which seed says more.
# Hence the two tiers, and a general seed only wins where no specific one is
# equally near.
UPPER_SEEDS: Dict[str, str] = {
    "BFO:0000040": "biolink:PhysicalEntity",         # material entity
    "BFO:0000015": "biolink:Activity",               # process
    "BFO:0000019": "biolink:Attribute",              # quality
    "PATO:0000001": "biolink:Attribute",             # quality
    "IAO:0000030": "biolink:InformationContentEntity",
    # BFO 1.1, in the ifomis.org namespace it had before the OBO PURLs. Older
    # submissions still import it, and its terms share no ids with BFO 2 -- so
    # without these an ontology built on it looks, to the seeds above, like one
    # built on nothing. Four of the 90 randomly sampled ontologies use it.
    "http://www.ifomis.org/bfo/1.1/snap#IndependentContinuant": "biolink:PhysicalEntity",
    "http://www.ifomis.org/bfo/1.1/snap#MaterialEntity": "biolink:PhysicalEntity",
    "http://www.ifomis.org/bfo/1.1/snap#Object": "biolink:PhysicalEntity",
    "http://www.ifomis.org/bfo/1.1/snap#ObjectAggregate": "biolink:PhysicalEntity",
    "http://www.ifomis.org/bfo/1.1/snap#FiatObjectPart": "biolink:PhysicalEntity",
    "http://www.ifomis.org/bfo/1.1/snap#Quality": "biolink:Attribute",
    "http://www.ifomis.org/bfo/1.1/snap#RealizableEntity": "biolink:Attribute",
    "http://www.ifomis.org/bfo/1.1/snap#Role": "biolink:Attribute",
    "http://www.ifomis.org/bfo/1.1/snap#Disposition": "biolink:Attribute",
    "http://www.ifomis.org/bfo/1.1/snap#Function": "biolink:Attribute",
    "http://www.ifomis.org/bfo/1.1/snap#GenericallyDependentContinuant":
        "biolink:InformationContentEntity",
    "http://www.ifomis.org/bfo/1.1/span#Occurrent": "biolink:Activity",
    "http://www.ifomis.org/bfo/1.1/span#ProcessualEntity": "biolink:Activity",
    "http://www.ifomis.org/bfo/1.1/span#Process": "biolink:Activity",
    "http://www.ifomis.org/bfo/1.1/span#ProcessAggregate": "biolink:Activity",
    "http://www.ifomis.org/bfo/1.1/span#FiatProcessPart": "biolink:Activity",
    # The same BFO 1.1 terms under the shorter ifomis.org/snap# and span#
    # namespaces, which is how CSEO writes them (20,050 nodes under
    # bfo/1.1#Entity and not one under the form above). Same terms, same
    # categories; the namespace is the only difference.
    "http://www.ifomis.org/snap#IndependentContinuant": "biolink:PhysicalEntity",
    "http://www.ifomis.org/snap#MaterialEntity": "biolink:PhysicalEntity",
    "http://www.ifomis.org/snap#Object": "biolink:PhysicalEntity",
    "http://www.ifomis.org/snap#ObjectAggregate": "biolink:PhysicalEntity",
    "http://www.ifomis.org/snap#FiatObjectPart": "biolink:PhysicalEntity",
    "http://www.ifomis.org/snap#Quality": "biolink:Attribute",
    "http://www.ifomis.org/snap#RealizableEntity": "biolink:Attribute",
    "http://www.ifomis.org/snap#Role": "biolink:Attribute",
    "http://www.ifomis.org/snap#Disposition": "biolink:Attribute",
    "http://www.ifomis.org/snap#Function": "biolink:Attribute",
    "http://www.ifomis.org/snap#GenericallyDependentContinuant":
        "biolink:InformationContentEntity",
    "http://www.ifomis.org/span#Occurrent": "biolink:Activity",
    "http://www.ifomis.org/span#ProcessualEntity": "biolink:Activity",
    "http://www.ifomis.org/span#Process": "biolink:Activity",
    "http://www.ifomis.org/span#ProcessAggregate": "biolink:Activity",
    "http://www.ifomis.org/span#FiatProcessPart": "biolink:Activity",
    # BioTop, in the bioonto.de namespace BIOMODELS is built on. Same shape as
    # the BFO seeds above -- an upper ontology whose top classes are the only
    # thing a large ontology shares with anything else.
    "http://bioonto.de/ro2.owl#Continuant": "biolink:PhysicalEntity",
    "http://bioonto.de/ro2.owl#Process": "biolink:Activity",
    "http://bioonto.de/ro2.owl#Function": "biolink:Attribute",
    "http://bioonto.de/ro2.owl#Quality": "biolink:Attribute",
    "http://purl.org/biotop/biotop.owl#Particular": "biolink:PhysicalEntity",
}

# A category for a whole ontology, used only where nothing else establishes one.
#
# Some ontologies are one kind of thing end to end, and say so nowhere a machine
# can read: their hierarchy is rooted at owl:Thing or skos:Concept, which the
# seeds above deliberately refuse. GNO is 580,716 glycan structures; LION is
# lipid species; ROR is research organizations; FAST-TITLE is bibliographic
# records for works. Naming those four is worth more than any amount of
# traversal, because there is nothing in the file to traverse *to*.
#
# Every entry here is a judgement about an ontology rather than a fact read out
# of it, so the bar is: the labels have to show it. Checked by sampling, which
# is also why ICD10PCS and SNMI are absent despite being obvious candidates --
# they have four labelled nodes between them (#173), so there is nothing to
# check. NATPRO, HRA and RDL were considered and rejected: their labels show
# mixed content (NATPRO's are DOID diseases, RDL's run from "IRON" to "PRESSED
# GLASS LAMP").
ONTOLOGY_DEFAULTS: Dict[str, str] = {
    "GNO": "biolink:ChemicalEntity",
    "LION": "biolink:ChemicalEntity",
    "ROR": "biolink:Agent",
    "FAST-TITLE": "biolink:InformationContentEntity",
    # Mouse anatomy by Theiler stage: "TS23 liver right lobe", "TS19
    # metencephalon alar plate". 19,455 nodes and 525 subclass edges, so the
    # hierarchy reaches almost none of it; the labels reach all of it.
    "EMAP": "biolink:AnatomicalEntity",
}

# Prefixes that are never an ontology's own subject matter: the structural
# vocabulary and upper-ontology terms that ride along inside any OWL file. A
# whole-ontology default must not claim that skos:Concept is a glycan.
#
# RO and SIO are here for the same reason, having arrived by a different route:
# KGX materialises the relations an ontology uses as nodes of their own, so
# ROR's graph contains RO:0001025 "located in" alongside its 377,491
# organizations. A relation is not an organization.
#
# Only consulted for ONTOLOGY_DEFAULTS. The seeds and the roll-up need no such
# list, because they only ever assign what the hierarchy actually says.
STRUCTURAL_PREFIXES = (
    "owl:", "rdf:", "rdfs:", "xsd:", "skos:", "dc:", "dct:", "dcterms:",
    "foaf:", "schema:", "prov:", "OIO:", "IAO:", "BFO:", "STY:", "RO:", "SIO:",
    "http://www.w3.org/", "http://purl.org/dc/", "http://xmlns.com/foaf/",
)


def ontology_default(ontology_name: str, node_id: str) -> Optional[str]:
    """The whole-ontology category for this node, if there is one.

    Returns None for an ontology with no default, and for the structural terms
    inside one that has -- see STRUCTURAL_PREFIXES.

    It is a blunt instrument by design, and the residue is visible in the
    published graphs: LION's 36 lipid *properties* ("average tail order
    parameter") take ChemicalEntity along with its 63,546 lipids, and GNO's
    graph carries three nodes for the ontology's own IRI. Both are the price of
    a claim about a whole ontology, and both are small enough to be worth it --
    but the report counts defaults apart from evidence-backed assignments
    precisely so this can be watched rather than assumed.
    """
    category = ONTOLOGY_DEFAULTS.get(ontology_name.strip().upper())
    if not category or node_id.startswith(STRUCTURAL_PREFIXES):
        return None
    return category


SPECIFIC, GENERAL = 0, 1

# Where a seed came from: the tables above, or the reviewed-roots file. Carried
# through the roll-up and across mappings so the report can say exactly how
# many nodes owe their category to a review.
TABLE, REVIEW = 0, 1

# What a root has to show before it goes into reviewed_roots.yaml. The same bar
# ONTOLOGY_DEFAULTS is held to, written down because the reviewer is an agent
# and the bar is the whole of what makes its verdicts trustworthy.
REVIEW_BAR = """A root is accepted only if its own label, or failing that the labels of its
subclasses, show one Biolink class to be true of everything beneath it.
  * Read the root's label and at least the first few of its children's labels.
    A child that is itself a branch is judged by its children in turn.
  * Children of mixed kinds mean refusal, recorded under `refused` with the
    labels that showed the mix. No category is better than a wrong one.
  * A root is seeded for what is beneath it, never for being the top.
    owl:Thing, skos:Concept and BFO "entity" are never seeded, and neither is
    a root whose children are chapters of different kinds. Seed the chapters.
  * Obsolete, deprecated and "requiring curation" branches are never seeded.
  * A category is chosen from Biolink's named-thing hierarchy, as specific as
    the evidence supports and no more.
Every entry records the graph it was read from, the reviewer, the date, the
evidence read, the reach measured, and who has confirmed it, if anyone."""

REVIEWED_ROOTS_FILE = os.path.join(os.path.dirname(__file__), "reviewed_roots.yaml")


def load_reviewed_roots(path: str = REVIEWED_ROOTS_FILE) -> Dict[str, dict]:
    """The reviewed-roots file, keyed by upper-cased ontology acronym.

    Absent file: no reviews, which is a valid state and not an error.
    ``also`` lists other ontologies the same roots apply to -- GEXO, REXO
    and RETO all hang off SIO's three top classes -- and each of those gets
    the entry under its own name, so a lookup by acronym is all a caller does.
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        loaded = yaml.safe_load(f) or {}
    reviews: Dict[str, dict] = {}
    for acronym, review in loaded.items():
        review = review or {}
        reviews[str(acronym).strip().upper()] = review
        for other in review.get("also") or ():
            reviews.setdefault(str(other).strip().upper(), review)
    return reviews


REVIEWED_ROOTS: Dict[str, dict] = load_reviewed_roots()


def reviewed_index(ontology_name: str) -> Dict[str, Tuple[str, int]]:
    """This ontology's reviewed roots, keyed by every id shape they can wear.

    Scoped to the ontology the review was made in: a chapter of ICD9CM was read
    as a chapter of ICD9CM, and the disclosure on the page is per ontology.
    Same value shape as SEED_INDEX, and the specific tier -- a reviewed root is
    a domain judgement, not an upper-ontology one.
    """
    review = REVIEWED_ROOTS.get(ontology_name.strip().upper())
    if not review:
        return {}
    index: Dict[str, Tuple[str, int]] = {}
    for root in review.get("roots") or ():
        for form in canonical_forms(str(root["id"])):
            index[form] = (root["category"], SPECIFIC)
    return index


def review_record(ontology_name: str) -> Dict[str, object]:
    """What the index and the site say about this ontology's review, if any.

    The provenance and nothing else: the roots themselves stay in the file.
    ``roots`` is how many were accepted; ``refused`` how many were read and
    turned down, which is part of the record too.
    """
    review = REVIEWED_ROOTS.get(ontology_name.strip().upper())
    if not review:
        return {}
    return {
        "reviewer": str(review.get("reviewer", "")),
        "reviewed": str(review.get("reviewed", "")),
        "confirmed_by": str(review.get("confirmed_by") or ""),
        "graph": str(review.get("graph", "")),
        "roots": len(review.get("roots") or ()),
        "refused": len(review.get("refused") or ()),
    }

# Which of the categories above are ancestors of which others, in Biolink.
# Written out rather than looked up so that assignment needs no model download
# at transform time; tests/test_categories.py checks it still agrees with the
# installed bmt, so it cannot drift silently.
#
# Covers every category the seed tables and the reviewed-roots file use.
# BiologicalEntity is on many lines because ARO's resistance determinants are
# seeded with it (genes and proteins side by side); it is an ancestor of most
# of the biology and of none of the chemistry. AnatomicalEntity is *not* under
# PhysicalEntity, which is why that particular tie needs the tiers above
# rather than this table.
CATEGORY_ANCESTORS: Dict[str, Tuple[str, ...]] = {
    "biolink:AnatomicalEntity": ("biolink:BiologicalEntity",),
    "biolink:BiologicalProcess": ("biolink:BiologicalEntity", "biolink:BiologicalProcessOrActivity"),
    "biolink:BiologicalProcessOrActivity": ("biolink:BiologicalEntity",),
    "biolink:Cell": ("biolink:AnatomicalEntity", "biolink:BiologicalEntity"),
    "biolink:CellLine": ("biolink:BiologicalEntity",),
    "biolink:CellularComponent": ("biolink:AnatomicalEntity", "biolink:BiologicalEntity"),
    "biolink:ClinicalFinding": ("biolink:BiologicalEntity", "biolink:DiseaseOrPhenotypicFeature", "biolink:PhenotypicFeature"),
    "biolink:Disease": ("biolink:BiologicalEntity", "biolink:DiseaseOrPhenotypicFeature"),
    "biolink:DiseaseOrPhenotypicFeature": ("biolink:BiologicalEntity",),
    "biolink:Drug": ("biolink:ChemicalEntity",),
    "biolink:EvidenceType": ("biolink:InformationContentEntity",),
    "biolink:Food": ("biolink:ChemicalEntity",),
    "biolink:Gene": ("biolink:BiologicalEntity",),
    "biolink:GeneFamily": ("biolink:BiologicalEntity",),
    "biolink:LifeStage": ("biolink:BiologicalEntity",),
    "biolink:MacromolecularComplex": ("biolink:BiologicalEntity",),
    "biolink:MaterialSample": ("biolink:PhysicalEntity",),
    "biolink:MolecularEntity": ("biolink:ChemicalEntity",),
    "biolink:NucleicAcidEntity": ("biolink:ChemicalEntity", "biolink:MolecularEntity"),
    "biolink:Pathway": ("biolink:BiologicalEntity", "biolink:BiologicalProcess", "biolink:BiologicalProcessOrActivity"),
    "biolink:PhenotypicFeature": ("biolink:BiologicalEntity", "biolink:DiseaseOrPhenotypicFeature"),
    "biolink:Polypeptide": ("biolink:BiologicalEntity",),
    "biolink:Protein": ("biolink:BiologicalEntity", "biolink:Polypeptide"),
    "biolink:Publication": ("biolink:InformationContentEntity",),
    "biolink:SequenceVariant": ("biolink:BiologicalEntity",),
}


def most_specific(categories: Set[str]) -> Set[str]:
    """Drop any category that another one in the set already implies.

    A class reached from two equally near, equally specific seeds can come out
    as e.g. {Cell, AnatomicalEntity}. Every Cell is an AnatomicalEntity, so
    saying both says nothing the first does not; keep the narrower one. What
    survives is a genuine disagreement, and worth leaving visible.
    """
    if len(categories) < 2:
        return categories
    implied = set()
    for category in categories:
        implied.update(CATEGORY_ANCESTORS.get(category, ()))
    return categories - implied


# The OBO PURL stem, which is how the same term appears when a node id was not
# abbreviated to a CURIE.
_OBO_IRI = "http://purl.obolibrary.org/obo/"

# The stem OBO used before the obolibrary PURLs, in which BIOMODELS still
# writes CL and PATO: http://purl.org/obo/owl/CL#CL_0000000. 2,799 of its
# nodes sit under those two roots and matched nothing until this form was
# recognised.
_OLD_OBO_IRI = "http://purl.org/obo/owl/"

# Prefixes whose terms also travel under a stem of their own. NCIt classes are
# NCIT:C9292 in one graph and http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C9292
# in the next, and the EVS form cannot be derived from the OBO one.
_EXTRA_STEMS: Dict[str, str] = {
    "NCIT": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#",
}


def canonical_forms(curie: str) -> Tuple[str, ...]:
    """Every id shape one seed term arrives in across our graphs.

    The same term is not written the same way twice across 1,200 ontologies.
    GO-PLUS abbreviates GO classes to ``GO:0008150``; VTO leaves its own to
    ``OBO:VTO_0000001``; some sources never abbreviate at all, and a few still
    use the purl.org/obo/owl stem that predates the obolibrary PURLs. Rather
    than guessing which an ontology uses, recognise all four.
    """
    if "://" in curie:
        # Already an IRI -- BFO 1.1's terms arrive as one. There is no CURIE
        # form to derive, and deriving one anyway would put "OBO:http_//..."
        # into the index: harmless, since nothing would ever match it, but the
        # index is easier to trust when every key is a shape a node can have.
        return (curie,)
    prefix, _, local = curie.partition(":")
    underscored = f"{prefix}_{local}"
    forms = [
        curie,
        f"OBO:{underscored}",
        f"{_OBO_IRI}{underscored}",
        f"{_OLD_OBO_IRI}{prefix}#{underscored}",
    ]
    if prefix in _EXTRA_STEMS:
        forms.append(f"{_EXTRA_STEMS[prefix]}{local}")
    return tuple(forms)


def _expand() -> Dict[str, Tuple[str, int]]:
    """Both seed tables keyed by every form their terms can appear in.

    Values are ``(category, tier)``; see UPPER_SEEDS for what the tier decides.
    """
    expanded: Dict[str, Tuple[str, int]] = {}
    for seeds, tier in ((UPPER_SEEDS, GENERAL), (SEEDS, SPECIFIC)):
        for curie, category in seeds.items():
            for form in canonical_forms(curie):
                expanded[form] = (category, tier)
    return expanded


SEED_INDEX: Dict[str, Tuple[str, int]] = _expand()


class CategoryReport(NamedTuple):
    """What one ontology's assignment did, for the log and for tuning SEEDS."""

    total: int = 0          # nodes in the file
    seeded: int = 0         # nodes that are themselves a seed term
    inherited: int = 0      # nodes that got one from a subclass ancestor
    mapped: int = 0         # nodes that got one across a mapping edge
    defaulted: int = 0      # nodes that fell back to what the ontology is
    reviewed: int = 0       # nodes whose category traces to a reviewed root
    ambiguous: int = 0      # nodes left holding more than one category
    uncategorized: int = 0  # nodes still NamedThing

    @property
    def assigned(self) -> int:
        return self.seeded + self.inherited + self.mapped + self.defaulted + self.reviewed

    def sources(self) -> Dict[str, int]:
        """The assigned nodes by how they got there, for the index.

        Only the routes that assigned anything: a thousand ``reviewed: 0``
        lines would say nothing.
        """
        counts = {
            "seeded": self.seeded,
            "inherited": self.inherited,
            "mapped": self.mapped,
            "defaulted": self.defaulted,
            "reviewed": self.reviewed,
        }
        return {k: v for k, v in counts.items() if v}

    def summary(self) -> str:
        if not self.total:
            return "no nodes to categorize"
        share = self.assigned / self.total * 100
        parts = [
            f"{self.assigned:,}/{self.total:,} nodes categorized ({share:.1f}%)",
            f"{self.seeded:,} seeded",
            f"{self.inherited:,} by subclass",
            f"{self.mapped:,} by mapping",
        ]
        if self.defaulted:
            parts.append(f"{self.defaulted:,} by the ontology default")
        if self.reviewed:
            parts.append(f"{self.reviewed:,} by reviewed roots")
        if self.ambiguous:
            parts.append(f"{self.ambiguous:,} ambiguous")
        return "; ".join(parts)


def _edge_graph(
    edge_file: str, index: Dict[str, Tuple[str, int]],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], Set[str]]:
    """Read the edge file once into what assignment needs from it.

    Returns ``(children, mates, present_seeds)``: parent -> narrower terms
    (by subclass_of or skos:broader, see HIERARCHY_PREDICATES), node -> nodes
    it is asserted to be the same thing as, and which of ``index``'s seed
    terms this ontology actually mentions. All three are built from edges
    alone, so nothing here is proportional to the node file.

    ``present_seeds`` is collected here rather than derived from ``children``
    afterwards because a seed can appear only in a mapping edge, or only as
    somebody's subclass. Taking the seeds from ``children``'s keys missed both,
    and a seeded term with no subclasses of its own then propagated nothing
    across its mappings.
    """
    children: Dict[str, List[str]] = collections.defaultdict(list)
    mates: Dict[str, List[str]] = collections.defaultdict(list)
    present: Set[str] = set()
    for subject, predicate, obj in _columns(
        edge_file, "subject", "predicate", "object"
    ):
        if not subject or not obj or subject == obj:
            continue
        parent_end = HIERARCHY_PREDICATES.get(predicate)
        if parent_end == "object":
            children[obj].append(subject)
        elif parent_end == "subject":
            children[subject].append(obj)
        elif predicate in MAPPING_PREDICATES:
            mates[subject].append(obj)
            mates[obj].append(subject)
        else:
            continue
        for node in (subject, obj):
            if node in index:
                present.add(node)
    return children, mates, present


def _columns(path: str, *names: str) -> Iterable[Tuple[str, ...]]:
    """Rows of a KGX TSV as tuples of the named columns.

    Yields "" for a column the file does not have, so a file written by an
    older KGX -- or a hand-made one in a test -- reads rather than raising.
    """
    with open(path, "r") as f:
        header = f.readline()
        if not header:
            return
        fields = header.rstrip("\n").split("\t")
        idx = [fields.index(n) if n in fields else None for n in names]
        for line in f:
            cells = line.rstrip("\n").split("\t")
            yield tuple(
                "" if i is None or i >= len(cells) else cells[i] for i in idx
            )


def _roll_up(
    children: Dict[str, List[str]],
    present_seeds: Set[str],
    index: Dict[str, Tuple[str, int]],
    reviewed: Set[str],
) -> Tuple[Dict[str, Set[str]], Set[str], Set[str]]:
    """Spread the seeds down the subclass hierarchy; the nearest seed wins.

    One breadth-first sweep from every seed at once, so a class takes the
    category of the seed fewest subclass steps above it -- which is what makes a
    general upper-ontology seed safe to include beside a specific one.

    Two seeds can still land on a class from the same distance. Then the more
    specific tier wins (see UPPER_SEEDS), and if the tier is level too the class
    keeps every category that survives ``most_specific``: Biolink permits
    several, and a class that really is two things at once is a fact about the
    ontology worth being able to see in the tally.

    ``reviewed`` names the seeds in ``index`` that came from the review file.
    Each node remembers whether any seed that reached it was one of those, so
    the count of nodes owing a category to a review is exact -- and errs, on a
    tie, towards saying so.

    Returns ``(categories, seeded_ids, from_review)``. A seed the ontology
    mentions in no edge at all is not here -- it has nothing to propagate to --
    and ``apply_to`` recognises those as it streams the node file.
    """
    # node -> [tier of the nearest seed that reached it, its categories,
    #          whether a reviewed root is among the seeds that reached it]
    reached: Dict[str, List] = {}
    seeded: Set[str] = set()

    # Every seed the ontology mentions starts at distance zero, so a seeded
    # class is always already reached by the time the sweep arrives from above:
    # its own category wins over an inherited one without needing a check for it
    # further down.
    frontier = sorted(present_seeds)
    for node in frontier:
        category, tier = index[node]
        reached[node] = [tier, {category}, node in reviewed]
        seeded.add(node)
    while frontier:
        following: Dict[str, List] = {}
        for parent in frontier:
            parent_tier, parent_cats, parent_reviewed = reached[parent]
            for child in children.get(parent, ()):
                # Already reached in an earlier sweep: that seed is nearer, and
                # nearness outranks everything.
                if child in reached:
                    continue
                # Two seeds equally near: the more specific tier wins, and a
                # level tier keeps both. Written as a comparison rather than as
                # "first one in wins" so the result does not depend on which
                # order the seeds happened to be visited in.
                equally_near = following.get(child)
                if equally_near is None or parent_tier < equally_near[0]:
                    following[child] = [parent_tier, set(parent_cats), parent_reviewed]
                elif parent_tier == equally_near[0]:
                    equally_near[1].update(parent_cats)
                    equally_near[2] = equally_near[2] or parent_reviewed
        for node, value in following.items():
            reached.setdefault(node, value)
        frontier = list(following)

    categories = {node: most_specific(cats) for node, (_, cats, _) in reached.items()}
    from_review = {node for node, (_, _, flag) in reached.items() if flag}
    return categories, seeded, from_review


def _propagate_mappings(
    categories: Dict[str, Set[str]],
    mates: Dict[str, List[str]],
    from_review: Set[str],
    rounds: int = 3,
) -> Set[str]:
    """Carry categories across exact-match edges to nodes that have none.

    Only ever fills a gap: a node that already has a category from the
    hierarchy is left alone, so a mapping can never overrule the ontology's own
    structure. Bounded rather than run to a fixpoint because mapping chains are
    shallow in practice and an unbounded loop over a pathological graph is not
    worth the risk.

    A category that came from a reviewed root is still one when it has crossed
    a mapping, so ``from_review`` grows along with ``categories``.

    Returns the ids that gained a category this way.
    """
    gained: Set[str] = set()
    for _ in range(rounds):
        additions: Dict[str, Set[str]] = {}
        reviewed_additions: Set[str] = set()
        for node, cats in categories.items():
            for mate in mates.get(node, ()):
                if mate not in categories and mate not in additions:
                    additions[mate] = set(cats)
                    if node in from_review:
                        reviewed_additions.add(mate)
        if not additions:
            break
        categories.update(additions)
        from_review |= reviewed_additions
        gained |= set(additions)
    return gained


class Assignment(NamedTuple):
    """What ``assign`` worked out, keyed by node id.

    Nodes with no evidence are simply absent from ``categories``; the caller
    leaves those as they are. ``index`` is the seed index the assignment was
    made against, so the caller can recognise a seed the edge file never
    mentioned.
    """

    categories: Dict[str, Set[str]]
    seeded: Set[str]
    mapped: Set[str]
    from_review: Set[str]
    index: Dict[str, Tuple[str, int]]


def assign(node_file: str, edge_file: str, ontology_name: str = "") -> Assignment:
    """Work out a category for as many nodes as the evidence supports."""
    reviewed = reviewed_index(ontology_name)
    index = dict(SEED_INDEX)
    index.update(reviewed)
    children, mates, present_seeds = _edge_graph(edge_file, index)
    categories, seeded, from_review = _roll_up(
        children, present_seeds, index, set(reviewed)
    )
    mapped = _propagate_mappings(categories, mates, from_review)
    return Assignment(categories, seeded, mapped, from_review, index)


def apply_to(node_file: str, edge_file: str, ontology_name: str = "") -> CategoryReport:
    """Rewrite ``node_file``'s category column in place, and report what changed.

    The assigned category *replaces* ``biolink:NamedThing`` rather than joining
    it. Biolink treats the category as the most specific class that applies and
    leaves the ancestors implied, and nothing can be filtering usefully on
    NamedThing today given that every node in every published graph carries it.

    A node the evidence the ontology itself carries says nothing about falls back
    to ONTOLOGY_DEFAULTS, if this ontology has one; failing that it keeps
    whatever KGX wrote.
    """
    categories, seeded, mapped, from_review, index = assign(
        node_file, edge_file, ontology_name
    )
    defaulted: Set[str] = set()

    temp_path = node_file + ".categorized"
    counts = dict(total=0, seeded=0, inherited=0, mapped=0, defaulted=0,
                  reviewed=0, ambiguous=0, uncategorized=0)
    with open(node_file, "r") as src, open(temp_path, "w") as dest:
        header = src.readline()
        dest.write(header)
        fields = header.rstrip("\n").split("\t")
        try:
            id_at, cat_at = fields.index("id"), fields.index("category")
        except ValueError:
            # No id or no category column: nothing to write into. Leave the
            # file exactly as it was rather than rewriting it to no effect.
            os.remove(temp_path)
            logging.warning(
                f"{os.path.basename(node_file)} has no id/category column; "
                "leaving categories as they are."
            )
            return CategoryReport()
        for line in src:
            counts["total"] += 1
            cells = line.rstrip("\n").split("\t")
            node_id = cells[id_at] if id_at < len(cells) else ""
            # A seed with no edges at all never entered the graph built from the
            # edge file, so recognise it here too.
            assigned = categories.get(node_id)
            if assigned is None and node_id in index:
                assigned = {index[node_id][0]}
                seeded.add(node_id)
                if node_id not in SEED_INDEX:
                    from_review.add(node_id)
            # Last resort, and only for the few ontologies that have one: what
            # this whole ontology is. Never overrules evidence from the file.
            if not assigned:
                fallback = ontology_default(ontology_name, node_id)
                if fallback:
                    assigned = {fallback}
                    defaulted.add(node_id)
            if assigned:
                if len(assigned) > 1:
                    counts["ambiguous"] += 1
                # A reviewed root, and everything that owes its category to
                # one, is counted under the review whichever route carried it:
                # that is the number the disclosure on the page is made of.
                if node_id in from_review:
                    counts["reviewed"] += 1
                elif node_id in seeded:
                    counts["seeded"] += 1
                elif node_id in mapped:
                    counts["mapped"] += 1
                elif node_id in defaulted:
                    counts["defaulted"] += 1
                else:
                    counts["inherited"] += 1
                while len(cells) <= cat_at:
                    cells.append("")
                cells[cat_at] = "|".join(sorted(assigned))
                dest.write("\t".join(cells) + "\n")
            else:
                counts["uncategorized"] += 1
                dest.write(line)
    os.replace(temp_path, node_file)
    return CategoryReport(**counts)


def categorize(node_file: str, edge_file: str, ontology_name: str = "") -> Optional[CategoryReport]:
    """``apply_to`` that can never cost an ontology.

    Every other stage of the transform has already succeeded by the time this
    runs. A defect here would throw away a graph that is sitting complete on
    disk, to improve one column of it, so a failure is logged and the graph is
    published with the categories KGX wrote.
    """
    label = ontology_name or os.path.basename(node_file)
    try:
        report = apply_to(node_file, edge_file, ontology_name)
    except Exception as e:  # noqa: BLE001 -- see the docstring
        logging.warning(
            f"{label}: could not assign Biolink categories ({type(e).__name__}: {e}); "
            "keeping the categories KGX wrote."
        )
        return None
    logging.info(f"{label}: {report.summary()}")
    return report
