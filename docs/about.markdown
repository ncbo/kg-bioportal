---
layout: default
title: About KG-Bioportal
permalink: /about/
---

## What is KG-Bioportal?

KG-Bioportal is a version of the set of ontologies on BioPortal in which ontologies have been transformed to graph nodes and edges in the [KGX format](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md). This means it is a collection of entities and relations, with the classes in each ontology serving as the entities and the connections between ontologies becoming relations. Where possible, entities and relations are categorized using Biolink Model, so entries in [NCBI Taxonomy](https://bioportal.bioontology.org/ontologies/NCBITAXON) are categorized as [biolink:OrganismTaxon](https://biolink.github.io/biolink-model/docs/OrganismTaxon.html), and so on.

## How is it made?

KG-Bioportal is made by careful transformation of each ontology from the [Bioportal API](https://data.bioontology.org/). Ontology files from Bioportal are transformed to a common format before being converted to nodes and egdes.

## How is it useful?

KG-Bioportal supports a holistic examination of a broad collection of hierarchical relationships in biology and biomedicine. Because all ontologies are contained a common format and data model, they may be merged in a modular fashion and analysed by graph traversal. This enables a growing collection of informative graph machine learning approaches.
