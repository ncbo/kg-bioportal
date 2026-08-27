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

Edges are left at ``biolink:Association``. See ``ASSOCIATION_NOTE``.
"""

import collections
import logging
import os
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

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
    "UBERON:0000105": "biolink:LifeStage",           # life cycle stage
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
    # OMIT's root carries no label of its own; its subclasses are gene symbols
    # (A1BG, A2M, NAT1, NAT2 ...), which is what identifies it.
    "NCRO:0000025": "biolink:Gene",                  #                    59,874
    # SIO's real top level, read from the published SIO graph. (SIO:000000
    # "entity" is deliberately absent: it is the top, and seeding the top only
    # re-derives NamedThing.)
    "SIO:000776": "biolink:PhysicalEntity",          # object
    "SIO:000614": "biolink:Attribute",               # attribute
    "SIO:000006": "biolink:Activity",                # process
    # Roots identified from another published graph rather than from a label of
    # their own, then confirmed against their subclasses. The reach noted is
    # measured on data-2026.08.26-16.
    #
    # FMA's anatomical entity, under the IRI the OWL API rewrote it to. Its two
    # subclasses are "Physical anatomical entity" and "Non-physical anatomical
    # entity", which is what identifies it.
    "http://purl.org/obo/owlapi/fma#FMA_62955": "biolink:AnatomicalEntity",  # 78,558
    # CCF, whose classes carry no label inside HRA but do inside CCF itself.
    "http://purl.org/ccf/AnatomicalStructure": "biolink:AnatomicalEntity",   #  7,838
    "http://purl.org/ccf/CellType": "biolink:Cell",                          #  1,831
    # (ccf/Biomarker is deliberately absent: its subclasses mix gene symbols
    # with peptides, so no one category is true of them.)
    "https://identifiers.org/ito:Process": "biolink:Activity",               # 14,351
    # HOOM keeps its HPO and Orphanet identifiers under classes of their own.
    "http://www.semanticweb.org/ontology/HOOM#HPO_id": "biolink:PhenotypicFeature",  # 8,763
    "http://www.semanticweb.org/ontology/HOOM#OrphaCode": "biolink:Disease",         # 4,362
    # Read Codes are chaptered, and each chapter is coherent even though the
    # ontology as a whole is not. Checked by reading each chapter's subclasses:
    # "Artery and vein operations" under 7, "Fracture of skull" under S.
    # Chapter T, "Causes of injury and poisoning", is absent on purpose -- its
    # subclasses are accidents ("Railway accidents"), which is not a disease and
    # not clearly anything else in Biolink either.
    "http://purl.bioontology.org/ontology/RCTV2/7....00": "biolink:Procedure",  # 14,984
    "http://purl.bioontology.org/ontology/RCTV2/4....00": "biolink:Procedure",  #  5,992
    "http://purl.bioontology.org/ontology/RCTV2/3....00": "biolink:Procedure",
    "http://purl.bioontology.org/ontology/RCTV2/S....00": "biolink:Disease",    #  7,013
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

# Which of the categories above are ancestors of which others, in Biolink.
# Written out rather than looked up so that assignment needs no model download
# at transform time; tests/test_categories.py checks it still agrees with the
# installed bmt, so it cannot drift silently.
#
# It is shorter than it looks because most of these sit directly under
# NamedThing -- AnatomicalEntity is *not* under PhysicalEntity, which is why
# that particular tie needs the tiers above rather than this table.
CATEGORY_ANCESTORS: Dict[str, Tuple[str, ...]] = {
    "biolink:Cell": ("biolink:AnatomicalEntity",),
    "biolink:CellularComponent": ("biolink:AnatomicalEntity",),
    "biolink:Food": ("biolink:ChemicalEntity",),
    "biolink:MaterialSample": ("biolink:PhysicalEntity",),
    "biolink:MolecularEntity": ("biolink:ChemicalEntity",),
    "biolink:NucleicAcidEntity": ("biolink:ChemicalEntity", "biolink:MolecularEntity"),
    "biolink:Pathway": ("biolink:BiologicalProcessOrActivity",),
    "biolink:Protein": ("biolink:Polypeptide",),
    "biolink:Publication": ("biolink:InformationContentEntity",),
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


def canonical_forms(curie: str) -> Tuple[str, ...]:
    """Every id shape one seed term arrives in across our graphs.

    The same term is not written the same way twice across 1,200 ontologies.
    GO-PLUS abbreviates GO classes to ``GO:0008150``; VTO leaves its own to
    ``OBO:VTO_0000001``; some sources never abbreviate at all. Rather than
    guessing which an ontology uses, recognise all three.
    """
    if "://" in curie:
        # Already an IRI -- BFO 1.1's terms arrive as one. There is no CURIE
        # form to derive, and deriving one anyway would put "OBO:http_//..."
        # into the index: harmless, since nothing would ever match it, but the
        # index is easier to trust when every key is a shape a node can have.
        return (curie,)
    prefix, _, local = curie.partition(":")
    underscored = f"{prefix}_{local}"
    return (curie, f"OBO:{underscored}", f"{_OBO_IRI}{underscored}")


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
    ambiguous: int = 0      # nodes left holding more than one category
    uncategorized: int = 0  # nodes still NamedThing

    @property
    def assigned(self) -> int:
        return self.seeded + self.inherited + self.mapped + self.defaulted

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
        if self.ambiguous:
            parts.append(f"{self.ambiguous:,} ambiguous")
        return "; ".join(parts)


def _edge_graph(
    edge_file: str,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], Set[str]]:
    """Read the edge file once into what assignment needs from it.

    Returns ``(children, mates, present_seeds)``: parent -> subclasses, node ->
    nodes it is asserted to be the same thing as, and which seed terms this
    ontology actually mentions. All three are built from edges alone, so nothing
    here is proportional to the node file.

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
        if not subject or not obj:
            continue
        if predicate == SUBCLASS_PREDICATE:
            children[obj].append(subject)
        elif predicate in MAPPING_PREDICATES:
            mates[subject].append(obj)
            mates[obj].append(subject)
        else:
            continue
        for node in (subject, obj):
            if node in SEED_INDEX:
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
    children: Dict[str, List[str]], present_seeds: Set[str]
) -> Tuple[Dict[str, Set[str]], Set[str]]:
    """Spread the seeds down the subclass hierarchy; the nearest seed wins.

    One breadth-first sweep from every seed at once, so a class takes the
    category of the seed fewest subclass steps above it -- which is what makes a
    general upper-ontology seed safe to include beside a specific one.

    Two seeds can still land on a class from the same distance. Then the more
    specific tier wins (see UPPER_SEEDS), and if the tier is level too the class
    keeps every category that survives ``most_specific``: Biolink permits
    several, and a class that really is two things at once is a fact about the
    ontology worth being able to see in the tally.

    Returns ``(categories, seeded_ids)``. A seed the ontology mentions in no
    edge at all is not here -- it has nothing to propagate to -- and ``apply_to``
    recognises those as it streams the node file.
    """
    # node -> (tier of the nearest seed that reached it, its categories)
    reached: Dict[str, Tuple[int, Set[str]]] = {}
    seeded: Set[str] = set()

    # Every seed the ontology mentions starts at distance zero, so a seeded
    # class is always already reached by the time the sweep arrives from above:
    # its own category wins over an inherited one without needing a check for it
    # further down.
    frontier = sorted(present_seeds)
    for node in frontier:
        category, tier = SEED_INDEX[node]
        reached[node] = (tier, {category})
        seeded.add(node)
    while frontier:
        following: Dict[str, Tuple[int, Set[str]]] = {}
        for parent in frontier:
            parent_tier, parent_cats = reached[parent]
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
                    following[child] = (parent_tier, set(parent_cats))
                elif parent_tier == equally_near[0]:
                    equally_near[1].update(parent_cats)
        for node, value in following.items():
            reached.setdefault(node, value)
        frontier = list(following)

    return {node: most_specific(cats) for node, (_, cats) in reached.items()}, seeded


def _propagate_mappings(
    categories: Dict[str, Set[str]],
    mates: Dict[str, List[str]],
    rounds: int = 3,
) -> Set[str]:
    """Carry categories across exact-match edges to nodes that have none.

    Only ever fills a gap: a node that already has a category from the
    hierarchy is left alone, so a mapping can never overrule the ontology's own
    structure. Bounded rather than run to a fixpoint because mapping chains are
    shallow in practice and an unbounded loop over a pathological graph is not
    worth the risk.

    Returns the ids that gained a category this way.
    """
    gained: Set[str] = set()
    for _ in range(rounds):
        additions: Dict[str, Set[str]] = {}
        for node, cats in categories.items():
            for mate in mates.get(node, ()):
                if mate not in categories and mate not in additions:
                    additions[mate] = set(cats)
        if not additions:
            break
        categories.update(additions)
        gained |= set(additions)
    return gained


def assign(node_file: str, edge_file: str) -> Tuple[Dict[str, Set[str]], Set[str], Set[str]]:
    """Work out a category for as many nodes as the evidence supports.

    Returns ``(categories, seeded, mapped)`` keyed by node id. Nodes with no
    evidence are simply absent; the caller leaves those as they are.
    """
    children, mates, present_seeds = _edge_graph(edge_file)
    categories, seeded = _roll_up(children, present_seeds)
    mapped = _propagate_mappings(categories, mates)
    return categories, seeded, mapped


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
    categories, seeded, mapped = assign(node_file, edge_file)
    defaulted: Set[str] = set()

    temp_path = node_file + ".categorized"
    counts = dict(total=0, seeded=0, inherited=0, mapped=0, defaulted=0,
                  ambiguous=0, uncategorized=0)
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
            if assigned is None and node_id in SEED_INDEX:
                assigned = {SEED_INDEX[node_id][0]}
                seeded.add(node_id)
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
                if node_id in seeded:
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
