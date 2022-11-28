"""Create static plotly figures for KG-Bioportal"""

import pandas as pd
import plotly.express as px
import yaml
from plotly.subplots import make_subplots

with open("onto_status.yaml", "r") as infile:
    ontos = pd.DataFrame(((yaml.safe_load(infile)))["ontologies"])
    countcols = ["nodecount", "edgecount"]
    ontos[countcols] = ontos[countcols].apply(pd.to_numeric, errors="coerce")

# Consider putting these in subplots
# https://plotly.com/python/pie-charts/#pie-charts-in-subplots

# Node counts across all ontologies, unmerged
nodeontos = ontos.loc[ontos["nodecount"] < 150000, "id"] = "All other ontologies"
fig1 = px.pie(
    ontos,
    values="nodecount",
    names="id",
    title="Nodes used to make KG-Bioportal",
    hole=.3
)
fig1.update_traces(textposition='inside', textinfo='percent+label')
fig1.update_layout(uniformtext_minsize=14, uniformtext_mode='hide')
fig1.write_html("fig1.html", include_plotlyjs='cdn')

# Edge counts across all ontologies, unmerged
ontos.loc[ontos["edgecount"] < 150000, "id"] = "All other ontologies"
fig2 = px.pie(
    ontos,
    values="edgecount",
    names="id",
    title="Edges used to make KG-Bioportal",
    hole=.3
)
fig2.update_traces(textposition='inside', textinfo='percent+label')
fig2.update_layout(uniformtext_minsize=14, uniformtext_mode='hide')
fig2.write_html("fig2.html", include_plotlyjs='cdn')

