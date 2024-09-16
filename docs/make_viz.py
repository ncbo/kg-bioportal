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
# Sort the DataFrame by nodecount in descending order and select the top 10
top_ontos = ontos.nlargest(10, 'nodecount')

fig1 = px.bar(
    top_ontos,
    x="id",
    y="nodecount",
    title="Top 10 Ontologies by Node Count in KG-Bioportal",
    text="nodecount"
)
fig1.update_traces(texttemplate='%{text:.2s}', textposition='outside')
fig1.update_layout(
    uniformtext_minsize=14,
    uniformtext_mode="hide",
    plot_bgcolor="rgba(0, 0, 0, 0)",
    paper_bgcolor="rgba(0, 0, 0, 0)",
    xaxis_title="Ontology ID",
    yaxis_title="Node Count",
    xaxis=dict(categoryorder='total descending')
)
fig1.update_traces(marker=dict(color=px.colors.qualitative.Plotly))
fig1.write_html("_includes/fig1.html", include_plotlyjs="cdn")

# Edge counts across all ontologies, unmerged
# Sort the DataFrame by nodecount in descending order and select the top 10
top_ontos = ontos.nlargest(10, 'edgecount')

fig2 = px.bar(
    top_ontos,
    x="id",
    y="edgecount",
    title="Top 10 Ontologies by Edge Count in KG-Bioportal",
    text="edgecount"
)
fig2.update_traces(texttemplate='%{text:.2s}', textposition='outside')
fig2.update_layout(
    uniformtext_minsize=14,
    uniformtext_mode="hide",
    plot_bgcolor="rgba(0, 0, 0, 0)",
    paper_bgcolor="rgba(0, 0, 0, 0)",
    xaxis_title="Ontology ID",
    yaxis_title="Edge Count",
    xaxis=dict(categoryorder='total descending')
)
fig2.update_traces(marker=dict(color=px.colors.qualitative.Plotly))
fig2.write_html("_includes/fig2.html", include_plotlyjs="cdn")
