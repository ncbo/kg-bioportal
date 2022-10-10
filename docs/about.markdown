---
layout: default
title: About KG-Bioportal
permalink: /about/
---

## What is KG-Bioportal?

KG-Bioportal is a version of the set of ontologies on BioPortal in which nearly all ontologies have been merged into a single knowledge graph. This means it is a collection of entities and relations, with the classes in each ontology serving as the entities and the connections between ontologies becoming relations. Where possible, entities and relations are categorized using Biolink Model, so entries in [NCBI Taxonomy](https://bioportal.bioontology.org/ontologies/NCBITAXON) are categorized as [biolink:OrganismTaxon](https://biolink.github.io/biolink-model/docs/OrganismTaxon.html), and so on.

## How is it made?

KG-Bioportal is made by careful transformation of each ontology from a dump of its 4store form to graph nodes and edges compatible with the KGX tools. The nodes and edges are then merged with KGX.

## How is it useful?

KG-Bioportal supports a holistic examination of a broad collection of hierarchical relationships in biology and biomedicine. Because all ontologies are contained within the same graph, they may be analysed by graph traversal and a growing collection of informative graph machine learning approaches.
