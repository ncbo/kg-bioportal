# KG-Bioportal

[Bioportal](https://bioportal.bioontology.org/), as a Knowledge Graph.

## Data Sources

In this graph pipeline, source data is primarily derived from [Bioportal-to-KGX](https://github.com/ncbo/BioPortal-to-KGX), starting from a 4store dump of the BioPortal ontologies.

## Components

### Download

The [download.yaml](download.yaml) contains all the URLs for source data. In this KG project, sources are pre-processed and this component is used for data transfer only.

### Transform

The [transform_utils](kg_bioportal/transform_utils) serve as a passthrough, allowing paths for sources to be stored.

### Merge

Implementation of the 'merge' function from [KGX](https://github.com/biolink/kgx) using [merge.yaml](merge.yaml) as a source file.

To enable flexibility in assembling the KG, the merge file is assembled on the fly.

## Example

`python run.py merge --merge_all`
