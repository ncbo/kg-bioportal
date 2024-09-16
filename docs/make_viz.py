"""Create static plotly figures for KG-Bioportal"""

import pandas as pd
import plotly.express as px
import yaml

with open("onto_stats.yaml", "r") as infile:
    ontos = pd.DataFrame(((yaml.safe_load(infile)))["ontologies"])
    countcols = ["nodecount", "edgecount"]
    ontos[countcols] = ontos[countcols].apply(pd.to_numeric, errors="coerce")

# Consider putting these in subplots
# https://plotly.com/python/pie-charts/#pie-charts-in-subplots

# Node counts across all ontologies, unmerged
nodeontos = ontos.loc[ontos["nodecount"] < 150000, "id"] = "All other ontologies"
fig1 = px.bar(
    ontos,
    x="id",
    y="nodecount",
    title="Nodes in KG-Bioportal",
    text="nodecount"
)
fig1.update_traces(texttemplate='%{text:.2s}', textposition='outside')
fig1.update_layout(
    uniformtext_minsize=14,
    uniformtext_mode="hide",
    plot_bgcolor="rgba(0, 0, 0, 0)",
    paper_bgcolor="rgba(0, 0, 0, 0)",
    xaxis_title="Ontology ID",
    yaxis_title="Node Count"
)
fig1.write_html("_includes/fig1.html", include_plotlyjs="cdn")

# Edge counts across all ontologies, unmerged
ontos.loc[ontos["edgecount"] < 150000, "id"] = "All other ontologies"
fig2 = px.bar(
    ontos,
    x="id",
    y="edgecount",
    title="Edges in KG-Bioportal",
    text="edgecount"
)
fig2.update_traces(texttemplate='%{text:.2s}', textposition='outside')
fig2.update_layout(
    uniformtext_minsize=14,
    uniformtext_mode="hide",
    plot_bgcolor="rgba(0, 0, 0, 0)",
    paper_bgcolor="rgba(0, 0, 0, 0)",
    xaxis_title="Ontology ID",
    yaxis_title="Edge Count"
)
fig2.write_html("_includes/fig2.html", include_plotlyjs="cdn")
