#!/usr/bin/env python3
"""
build_site.py — generate a BioPortal-style static site for knowledge graphs
from the KG-Registry JSON-LD.

Input : kgs.jsonld  (https://kghub.org/kg-registry/registry/kgs.jsonld)
        We use only resources whose category == "KnowledgeGraph".
Output: site/
          index.html                      (browse page — all KGs)
          resource/<id>/index.html        (one summary page per KG)

No third-party dependencies. CSS is inlined into every page so each page is
self-contained and portable (drops straight into GitHub Pages / kg-bioportal
docs/ with no asset wiring).

Usage:
    python build_site.py                 # uses ./kgs.jsonld, writes ./site
    python build_site.py IN.jsonld OUT   # explicit paths
    python build_site.py --fetch         # download the JSON-LD first
"""
import json, os, sys, html, shutil, urllib.request

REGISTRY_URL = "https://kghub.org/kg-registry/registry/kgs.jsonld"

# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #
def esc(s):
    return html.escape(str(s), quote=True) if s is not None else ""

def humansize(n):
    """Bytes -> '220.2 MB' (base 1024, matching KG-Registry)."""
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024

def commafy(n):
    return f"{n:,}" if isinstance(n, int) else "—"

def abbrev(n):
    """1582279 -> '1.6M'."""
    if not isinstance(n, int):
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)

def short_cat(c):
    """'biolink:PhenotypicFeature' -> 'PhenotypicFeature'."""
    return c.split(":", 1)[1] if ":" in c else c

def graph_products(r):
    return [p for p in r.get("products", []) if p.get("category") == "GraphProduct"]

def primary_graph_product(r):
    """The graph product that best represents the graph's size."""
    gps = graph_products(r)
    if not gps:
        return None
    counted = [p for p in gps if isinstance(p.get("node_count"), int)]
    if counted:
        return max(counted, key=lambda p: p.get("node_count", 0))
    return gps[0]

def kg_metrics(r):
    """Return (nodes, edges, n_categories, n_predicates, categories, predicates)."""
    nodes = edges = None
    cats, preds = [], []
    for p in graph_products(r):
        if isinstance(p.get("node_count"), int):
            nodes = max(nodes or 0, p["node_count"])
        if isinstance(p.get("edge_count"), int):
            edges = max(edges or 0, p["edge_count"])
        if p.get("node_categories"):
            cats = p["node_categories"] if len(p["node_categories"]) > len(cats) else cats
        if p.get("predicates"):
            preds = p["predicates"] if len(p["predicates"]) > len(preds) else preds
    return nodes, edges, (len(cats) or None), (len(preds) or None), cats, preds

def kg_formats(r):
    seen = []
    for p in graph_products(r):
        f = p.get("format")
        if f and f not in seen:
            seen.append(f)
    return seen

FMT_CLASS = {  # map a format string to a chip color class
    "kgx": "kgx", "kgx-jsonl": "jsonl", "json": "jsonl", "jsonld": "jsonl",
    "rdfxml": "rdf", "ttl": "rdf", "ntriples": "rdf", "nquads": "rdf",
    "neo4j": "neo4j", "duckdb": "duckdb", "sqlite": "duckdb", "mixed": "duckdb",
}
def fmt_class(f):
    return FMT_CLASS.get(f, "kgx")

# --------------------------------------------------------------------------- #
#  unified item model (KG-Registry KGs + transformed BioPortal ontologies)
# --------------------------------------------------------------------------- #
# Where a transformed ontology's KGX artifact lives (a release asset).
RELEASE_ASSET = "https://github.com/ncbo/kg-bioportal/releases/latest/download/{id}.tar.gz"

def kg_to_item(r):
    """Normalize a KG-Registry knowledge graph into a browse item."""
    nodes, edges, *_ = kg_metrics(r)
    rid = r["id"]
    name = r.get("name") or rid
    desc = (r.get("description") or "").strip()
    doms = r.get("domains") or []
    status = r.get("activity_status", "")
    return {
        "source": "kg-registry", "source_label": "KG project", "source_cls": "kgreg",
        "id": rid, "acr": rid.upper(), "name": name,
        "blurb": (desc[:110] + "…") if len(desc) > 110 else desc,
        "nodes": nodes, "edges": edges, "fmts": kg_formats(r), "domains": doms,
        "status_label": status or "—", "status_cls": "ok" if status == "active" else "warn",
        "updated": (r.get("last_modified_date") or "")[:10],
        "href": f"resource/{rid}/", "has_page": True, "version": "",
    }

def onto_to_item(o, transform_date):
    """Normalize a transformed BioPortal ontology (onto_stats entry) into a browse item."""
    oid = o["id"]
    status = o.get("status", "")
    ok = status == "OK"
    name = o.get("name") or oid
    ver = (o.get("version") or "").strip()
    ver = "" if ver in ("NA", "") else ver
    nodes = o.get("nodecount") if ok and isinstance(o.get("nodecount"), int) else None
    edges = o.get("edgecount") if ok and isinstance(o.get("edgecount"), int) else None
    blurb = "BioPortal ontology transformed to KGX"
    if not ok:
        blurb += f" — {status.lower()}" + (f" ({o.get('reason')})" if o.get("reason") else "")
    return {
        "source": "bioportal", "source_label": "BioPortal → KGX", "source_cls": "bp",
        "id": oid, "acr": oid.upper(), "name": name,
        "blurb": blurb,
        "nodes": nodes, "edges": edges, "fmts": ["kgx"] if ok else [], "domains": [],
        "status_label": status or "—", "status_cls": "ok" if ok else "warn",
        "updated": transform_date or "",
        "href": f"resource/{oid}/" if ok else "", "has_page": ok, "version": ver,
        "download_url": RELEASE_ASSET.format(id=oid),
        "bioportal_url": f"{BP}/ontologies/{oid}",
        "submission_id": o.get("submission_id", "NA"),
        "reason": o.get("reason", ""), "transform_date": transform_date or "",
    }

def load_ontologies(path):
    """Load onto_stats.yaml -> list of entries. Needs PyYAML (present in the CI build)."""
    if not path or not os.path.exists(path):
        return []
    try:
        import yaml  # available in the Pages build (installed for make_viz.py)
    except ImportError:
        print("PyYAML not available; skipping transformed-ontology entries.")
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("ontologies", [])

# --------------------------------------------------------------------------- #
#  shared chrome
# --------------------------------------------------------------------------- #
def css():
    return CSS  # defined at bottom

def head(title):
    return f"<!doctype html><html lang=en><head><meta charset=utf-8>" \
           f"<meta name=viewport content='width=device-width,initial-scale=1'>" \
           f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"

BP = "https://bioportal.bioontology.org"  # link out to the real BioPortal services

def nav(root):
    def ext(href, label):
        return (f'<a href="{href}" target="_blank" rel="noopener" class="ext">'
                f'{label}<svg class="extmark" width=9 height=9 viewBox="0 0 24 24" fill=none '
                f'stroke=currentColor stroke-width=2.6><path d="M7 17L17 7M9 7h8v8"/></svg></a>')
    return f"""
<div class="nav"><div class="nav-in">
  <a class="brand" href="{root}index.html">KG&#8209;<span class="kg">Bio</span>Portal</a>
  <nav class="navlinks">
    <a href="{root}index.html" class="on">Browse</a>
    {ext(f"{BP}/search", "Search")}
    {ext(f"{BP}/mappings", "Mappings")}
    {ext(f"{BP}/recommender", "Recommender")}
    {ext(f"{BP}/annotator", "Annotator")}
  </nav>
  <div class="nav-spacer"></div>
  <div class="navsearch">
    <svg width=14 height=14 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.4><circle cx=11 cy=11 r=7/><path d="M21 21l-4.3-4.3"/></svg>
    <input placeholder="Search graphs &amp; nodes" aria-label=Search>
  </div>
  <a class="navlogin" href="#">Log in</a>
</div></div>
<div class="protobar"><div class="protobar-in">
  <span class="proto-pill">Prototype</span>
  KG&#8209;aware adaptation of the BioPortal interface. Graph pages generated from live KG&#8209;Registry metadata; tool links go to the live <a href="{BP}" target="_blank" rel="noopener">BioPortal</a>.
</div></div>"""

def footer():
    return """
<footer><div class="foot-in">
  <div><b>KG&#8209;BioPortal</b> — prototype · a KG-aware adaptation of NCBO BioPortal</div>
  <div>Metadata generated from KG&#8209;Registry · Built on the BioPortal / KG&#8209;Hub stack</div>
</div></footer></body></html>"""

# --------------------------------------------------------------------------- #
#  browse page
# --------------------------------------------------------------------------- #
def render_browse(items, kg_count, onto_count):
    """Render the unified browse page over normalized items (KGs + ontologies)."""
    from collections import Counter
    dom_counts = Counter()
    src_counts = Counter()
    for it in items:
        src_counts[it["source"]] += 1
        for d in it["domains"]:
            dom_counts[d] += 1
    top_domains = [d for d, _ in dom_counts.most_common(12)]

    rows = []
    for it in sorted(items, key=lambda x: x["name"].lower()):
        acr, name, href = it["acr"], it["name"], it["href"]
        fmt_chips = "".join(
            f'<span class="fmt {fmt_class(f)}">{esc(f)}</span>' for f in it["fmts"][:3]
        )
        # chips: always the source badge, then domains (KGs) or a version chip (ontologies)
        chips = f'<span class="src-chip {it["source_cls"]}">{esc(it["source_label"])}</span>'
        chips += "".join(f'<span class="chip sm">{esc(d)}</span>' for d in it["domains"][:3])
        if it["version"]:
            chips += f'<span class="chip sm ver">v{esc(it["version"])}</span>'
        search_blob = esc(" ".join([name, acr, it["id"], it["source_label"]] + it["domains"] + it["fmts"]).lower())
        acr_html = (f'<a class="acr-link" href="{esc(href)}">{esc(acr)}</a>'
                    if href else f'<span class="acr-link muted">{esc(acr)}</span>')
        click = f"onclick=\"location.href='{esc(href)}'\"" if href else ""

        rows.append(f"""<tr class="krow" data-search="{search_blob}"
             data-domains="{esc('|'.join(it['domains']))}" data-source="{esc(it['source'])}" {click}>
          <td class="c-name">
            {acr_html}
            <div class="nm">{esc(name)}</div>
            <div class="blurb">{esc(it['blurb'])}</div>
            <div class="row-chips">{chips}</div>
          </td>
          <td class="c-num num">{abbrev(it['nodes'])}</td>
          <td class="c-num num">{abbrev(it['edges'])}</td>
          <td class="c-fmt">{fmt_chips or '<span class="muted">—</span>'}</td>
          <td class="c-status"><span class="stat {it['status_cls']}">{esc(it['status_label'])}</span></td>
          <td class="c-num num muted">{esc(it['updated'])}</td>
        </tr>""")

    src_order = [("kg-registry", "KG project", "kgreg"), ("bioportal", "BioPortal → KGX", "bp")]
    src_facets = "".join(
        f'<button class="facet" data-source="{sid}">{esc(label)}'
        f'<span class="fc">{src_counts.get(sid, 0)}</span></button>'
        for sid, label, _ in src_order if src_counts.get(sid)
    )
    dom_facets = "".join(
        f'<button class="facet" data-domain="{esc(d)}">{esc(d)}'
        f'<span class="fc">{dom_counts[d]}</span></button>' for d in top_domains
    )

    return head("Browse Graphs · KG-BioPortal") + nav("") + f"""
<div class="wrap">
  <div class="crumbs"><a href="index.html">Home</a><span>/</span>Graphs</div>
  <div class="browse-head">
    <div>
      <h1>Browse Graphs</h1>
      <p class="sub"><b class="num">{len(items)}</b> graphs · <b class="num">{kg_count}</b> KG projects (KG&#8209;Registry) + <b class="num">{onto_count}</b> transformed BioPortal ontologies</p>
    </div>
    <div class="browse-search">
      <svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.2 style="opacity:.5;flex:none"><circle cx=11 cy=11 r=7/><path d="M21 21l-4.3-4.3"/></svg>
      <input id="q" placeholder="Filter by name, domain, or format…" aria-label="Filter graphs">
    </div>
  </div>

  <div class="browse-grid">
    <aside class="facets">
      <h3>Source</h3>
      <div class="facet-list">{src_facets}</div>
      <h3 style="margin-top:18px">Domains</h3>
      <div class="facet-list">{dom_facets}</div>
      <button class="facet-clear" id="clearf">Clear filters</button>
    </aside>

    <div class="tbl-scroll">
      <table class="browse-tbl">
        <thead><tr>
          <th>Graph</th><th class="num">Nodes</th><th class="num">Edges</th>
          <th>Formats</th><th>Status</th><th class="num">Updated</th>
        </tr></thead>
        <tbody id="krows">
          {''.join(rows)}
        </tbody>
      </table>
      <p class="noresults" id="noresults" hidden>No graphs match your filters.</p>
    </div>
  </div>
</div>
<script>
(function(){{
  var q=document.getElementById('q'), rows=[].slice.call(document.querySelectorAll('.krow'));
  var facets=[].slice.call(document.querySelectorAll('.facet'));
  var activeDom=null, activeSrc=null, nr=document.getElementById('noresults');
  function apply(){{
    var term=(q.value||'').trim().toLowerCase(), shown=0;
    rows.forEach(function(r){{
      var okT=!term||r.dataset.search.indexOf(term)>-1;
      var okD=!activeDom||('|'+r.dataset.domains+'|').indexOf('|'+activeDom+'|')>-1;
      var okS=!activeSrc||r.dataset.source===activeSrc;
      var vis=okT&&okD&&okS; r.hidden=!vis; if(vis)shown++;
    }});
    nr.hidden=shown>0;
  }}
  q.addEventListener('input',apply);
  facets.forEach(function(f){{f.addEventListener('click',function(){{
    var isSrc=f.hasAttribute('data-source');
    var group=facets.filter(function(x){{return x.hasAttribute('data-source')===isSrc;}});
    var val=isSrc?f.dataset.source:f.dataset.domain;
    var cur=isSrc?activeSrc:activeDom;
    if(cur===val){{ if(isSrc)activeSrc=null; else activeDom=null; f.classList.remove('on'); }}
    else{{ group.forEach(function(x){{x.classList.remove('on');}}); f.classList.add('on');
           if(isSrc)activeSrc=val; else activeDom=val; }}
    apply();
  }});}});
  document.getElementById('clearf').addEventListener('click',function(){{
    activeDom=null;activeSrc=null;q.value='';facets.forEach(function(x){{x.classList.remove('on');}});apply();
  }});
}})();
</script>
""" + footer()

# --------------------------------------------------------------------------- #
#  resource (summary) page
# --------------------------------------------------------------------------- #
def render_resource(r, reverse_index):
    rid = r["id"]
    name = r.get("name") or rid
    acr = rid.upper()
    desc = (r.get("description") or "").strip()
    nodes, edges, ncat, npred, cats, preds = kg_metrics(r)
    doms = r.get("domains") or []
    fmts = kg_formats(r)
    status = r.get("activity_status", "")
    lic = (r.get("license") or {}).get("label")
    homepage = r.get("homepage_url")
    repo = r.get("repository")
    infores = r.get("infores_id")
    taxa = r.get("taxon") or []
    pubs = r.get("publications") or []

    # header chips
    chips = []
    for d in doms:
        chips.append(f'<span class="chip">{esc(d)}</span>')
    if lic:
        chips.append(f'<span class="chip">{esc(lic)}</span>')
    for f in fmts[:4]:
        chips.append(f'<span class="chip">{esc(f)}</span>')
    chips_html = "".join(chips)

    st_cls = "ok" if status == "active" else "warn"
    status_pill = f'<span class="status {st_cls}"><span class="dot"></span>{esc(status or "—")}</span>'

    # metrics grid
    def metric(cls, v, k):
        return f'<div class="metric {cls}"><div class="v">{v}</div><div class="k">{k}</div></div>'
    metrics = (
        metric("node", commafy(nodes), "Nodes") +
        metric("edge", commafy(edges), "Edges") +
        metric("cat", (ncat if ncat else "—"), "Node categories") +
        metric("pred", (npred if npred else "—"), "Predicate types")
    )

    # category & predicate chip clouds (real sets, no invented proportions)
    cat_cloud = "".join(f'<span class="tok cat">{esc(short_cat(c))}</span>' for c in cats)
    pred_cloud = "".join(f'<span class="tok pred">{esc(short_cat(p))}</span>' for p in sorted(preds)[:24])
    pred_more = f'<span class="tok more">+{len(preds)-24} more</span>' if len(preds) > 24 else ""

    # products
    prod_rows = []
    for p in graph_products(r):
        f = p.get("format", "")
        url = p.get("product_url", "#")
        fname = url.rsplit("/", 1)[-1] if url and url != "#" else p.get("id", "")
        size = humansize(p.get("product_file_size"))
        prod_rows.append(f"""<div class="prod">
          <span class="fmt {fmt_class(f)}">{esc(f or '—')}</span>
          <div class="prod-main"><div class="t">{esc(p.get('name') or p.get('id'))}</div>
            <div class="f">{esc(fname)}</div></div>
          <span class="prod-size">{esc(size)}</span>
          <a class="dl" href="{esc(url)}" aria-label="Download"><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.1><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M5 19h14"/></svg></a>
        </div>""")
    products_html = "".join(prod_rows) or '<p class="muted">No graph distributions listed.</p>'

    # contacts
    people = []
    for c in (r.get("contacts") or []):
        label = c.get("label", "")
        details = c.get("contact_details", [])
        email = next((d["value"] for d in details if d.get("contact_type") == "email"), None)
        gh = next((d["value"] for d in details if d.get("contact_type") == "github"), None)
        orcid = c.get("orcid")
        meta = []
        if email:
            meta.append(f'<a href="mailto:{esc(email)}">{esc(email)}</a>')
        bits = []
        if orcid:
            bits.append(f'ORCID <span class="mono">{esc(orcid)}</span>')
        if gh:
            bits.append(f'GitHub <span class="mono">@{esc(gh)}</span>')
        people.append(
            f'<div class="person"><span class="nm">{esc(label)}</span>' +
            (f'<span class="mt">{meta[0]}</span>' if meta else "") +
            (f'<span class="mt">{" · ".join(bits)}</span>' if bits else "") +
            "</div>"
        )
    contacts_html = "".join(people) or '<p class="muted">No contacts listed.</p>'

    # related — resources that draw from this KG (reverse had-primary-source)
    rel = reverse_index.get(rid, [])
    rel_html = ""
    if rel:
        items = "".join(
            f'<div class="rel"><span class="rn">{esc(x["name"])}</span>'
            f'<span class="rk">{esc(x["id"])}</span>'
            f'<span class="rd">had primary source</span></div>' for x in rel[:8]
        )
        rel_html = f'<div class="card"><h3>Used by</h3><div class="body">{items}</div></div>'

    # details rows
    def drow(lab, val_html):
        return f'<div class="row"><span class="lab">{esc(lab)}</span><span class="val">{val_html}</span></div>'
    details = [drow("Acronym", f'<span class="mono">{esc(acr)}</span>')]
    details.append(drow("Registry ID", f'<span class="mono">{esc(rid)}</span>'))
    details.append(drow("Status", esc(status or "—")))
    if lic:
        details.append(drow("License", esc(lic)))
    if doms:
        details.append(drow("Domains", esc(", ".join(doms))))
    if homepage:
        host = homepage.split("//")[-1].split("/")[0]
        details.append(drow("Homepage", f'<a href="{esc(homepage)}">{esc(host)}</a>'))
    if repo:
        rlabel = repo.rstrip("/").rsplit("/", 1)[-1]
        details.append(drow("Repository", f'<a href="{esc(repo)}">{esc(rlabel)}</a>'))
    if infores:
        details.append(drow("Infores", f'<span class="mono">{esc(infores)}</span>'))
    if taxa:
        details.append(drow("Taxa", esc(", ".join(str(t) for t in taxa[:4]))))
    if pubs:
        p0 = pubs[0]
        purl = p0.get("id") or p0.get("url") or "#"
        plabel = p0.get("label") or p0.get("name") or "Publication"
        details.append(drow("Publication", f'<a href="{esc(purl)}">{esc(plabel)}</a>'))
    details_html = "".join(details)

    added = (r.get("creation_date") or "")[:10]
    updated = (r.get("last_modified_date") or "")[:10]
    dl_url = (primary_graph_product(r) or {}).get("product_url", "#")

    return head(f"{acr} · KG-BioPortal") + nav("../../") + f"""
<div class="wrap">
  <div class="crumbs"><a href="../../index.html">Home</a><span>/</span>
    <a href="../../index.html">Knowledge Graphs</a><span>/</span>{esc(acr)}</div>

  <div class="head">
    <div class="head-main">
      <div class="acr"><h1>{esc(acr)}</h1>{status_pill}</div>
      <p class="fullname">{esc(name)}</p>
      <div class="chips">{chips_html}</div>
    </div>
    <div class="head-cta">
      <a class="btn btn-primary" href="{esc(dl_url)}">
        <svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.2><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></svg>
        Download graph</a>
      <a class="btn btn-ghost" href="#">
        <svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2><circle cx=6 cy=6 r=2.4/><circle cx=18 cy=9 r=2.4/><circle cx=9 cy=18 r=2.4/><path d="M8 7l8 1.5M8.5 16l8-6"/></svg>
        Explore graph</a>
    </div>
  </div>

  <div class="tabs" role="tablist">
    <div class="tab on">Summary</div>
    <div class="tab">Nodes <span class="cnt">{abbrev(nodes)}</span></div>
    <div class="tab">Edges <span class="cnt">{abbrev(edges)}</span></div>
    <div class="tab">Schema</div><div class="tab">Mappings</div>
    <div class="tab">Notes</div><div class="tab">Widgets</div>
  </div>

  <div class="grid">
    <main>
      <section class="block">
        <div class="visline"><svg width=14 height=14 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx=12 cy=12 r=2.6/></svg> Visibility: <b>Public</b></div>
        <p class="lead">{esc(desc) or "No description provided."}</p>
      </section>

      <section class="block">
        <p class="eyebrow">Graph at a glance</p>
        <div class="metrics">{metrics}</div>
        {'' if (nodes or edges) else '<p class="muted mt">Node and edge counts are not reported in the registry for this graph.</p>'}
      </section>

      {f'''<section class="block">
        <p class="eyebrow">Node categories <span class="eb-count">{ncat}</span></p>
        <div class="cloud">{cat_cloud}</div>
      </section>''' if cats else ''}

      {f'''<section class="block">
        <p class="eyebrow">Predicate types <span class="eb-count">{npred}</span></p>
        <div class="cloud">{pred_cloud}{pred_more}</div>
      </section>''' if preds else ''}

      <section class="block">
        <p class="eyebrow">Products &amp; downloads</p>
        <div class="prod-list">{products_html}</div>
      </section>
    </main>

    <aside class="side">
      <div class="card"><h3>Details</h3><div class="body">{details_html}</div></div>
      <div class="card"><h3>Contacts</h3><div class="body">{contacts_html}</div></div>
      {rel_html}
      <div class="card"><h3>Provenance</h3><div class="body">
        <div class="row"><span class="lab">Added</span><span class="val num">{esc(added)}</span></div>
        <div class="row"><span class="lab">Updated</span><span class="val num">{esc(updated)}</span></div>
        <div class="row" style="border:0"><span class="lab">Source</span><span class="val">KG&#8209;Registry</span></div>
        <div class="uploaded" style="padding-top:9px"><a href="https://github.com/Knowledge-Graph-Hub/kg-registry/issues/new">Request an update &#8599;</a></div>
      </div></div>
    </aside>
  </div>
</div>
""" + footer()

# --------------------------------------------------------------------------- #
#  ontology resource page (transformed BioPortal ontology)
# --------------------------------------------------------------------------- #
def render_ontology_resource(it):
    """Summary page for a transformed BioPortal ontology (from onto_stats)."""
    acr, name = it["acr"], it["name"]
    nodes, edges = it["nodes"], it["edges"]
    ver = it["version"]
    date = it["transform_date"]
    sub = it["submission_id"]

    def metric(cls, v, k):
        return f'<div class="metric {cls}"><div class="v">{v}</div><div class="k">{k}</div></div>'
    metrics = (
        metric("node", commafy(nodes), "Nodes") +
        metric("edge", commafy(edges), "Edges") +
        metric("cat", esc(ver or "—"), "Version") +
        metric("pred", esc(date or "—"), "Transformed")
    )

    chips = ('<span class="chip">KGX</span>'
             '<span class="chip">BioPortal &rarr; KGX</span>')
    if ver:
        chips += f'<span class="chip">v{esc(ver)}</span>'

    def drow(lab, val_html):
        return f'<div class="row"><span class="lab">{esc(lab)}</span><span class="val">{val_html}</span></div>'
    details = "".join([
        drow("Acronym", f'<span class="mono">{esc(acr)}</span>'),
        drow("Status", esc(it["status_label"])),
        drow("Version", esc(ver or "—")),
        drow("Submission", f'<span class="mono">{esc(sub)}</span>'),
        drow("Transformed", esc(date or "—")),
        drow("Source", "BioPortal, transformed to KGX"),
        drow("BioPortal", f'<a href="{esc(it["bioportal_url"])}" target="_blank" rel="noopener">ontologies/{esc(acr)}</a>'),
    ])

    fname = f"{it['id']}.tar.gz"
    return head(f"{acr} · KG-BioPortal") + nav("../../") + f"""
<div class="wrap">
  <div class="crumbs"><a href="../../index.html">Home</a><span>/</span>
    <a href="../../index.html">Graphs</a><span>/</span>{esc(acr)}</div>

  <div class="head">
    <div class="head-main">
      <div class="acr"><h1>{esc(acr)}</h1><span class="status ok"><span class="dot"></span>{esc(it['status_label'])}</span></div>
      <p class="fullname">{esc(name)}</p>
      <div class="chips">{chips}</div>
    </div>
    <div class="head-cta">
      <a class="btn btn-primary" href="{esc(it['download_url'])}">
        <svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.2><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></svg>
        Download KGX</a>
      <a class="btn btn-ghost" href="{esc(it['bioportal_url'])}" target="_blank" rel="noopener">
        <svg width=16 height=16 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.2><path d="M7 17L17 7M9 7h8v8"/></svg>
        View on BioPortal</a>
    </div>
  </div>

  <div class="tabs" role="tablist">
    <div class="tab on">Summary</div>
    <div class="tab">Nodes <span class="cnt">{abbrev(nodes)}</span></div>
    <div class="tab">Edges <span class="cnt">{abbrev(edges)}</span></div>
    <div class="tab">Mappings</div><div class="tab">Notes</div>
  </div>

  <div class="grid">
    <main>
      <section class="block">
        <div class="visline"><svg width=14 height=14 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx=12 cy=12 r=2.6/></svg> Visibility: <b>Public</b></div>
        <p class="lead">A KGX transformation of the BioPortal ontology <b>{esc(name)}</b> ({esc(acr)}), produced by KG&#8209;Bioportal. Nodes are ontology classes; edges are the relations between them.</p>
      </section>

      <section class="block">
        <p class="eyebrow">Graph at a glance</p>
        <div class="metrics">{metrics}</div>
      </section>

      <section class="block">
        <p class="eyebrow">Products &amp; downloads</p>
        <div class="prod-list">
          <div class="prod">
            <span class="fmt kgx">KGX</span>
            <div class="prod-main"><div class="t">KGX nodes &amp; edges</div><div class="f">{esc(fname)}</div></div>
            <a class="dl" href="{esc(it['download_url'])}" aria-label="Download KGX"><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2.1><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M5 19h14"/></svg></a>
          </div>
        </div>
        <p class="muted mt">From the latest transform release. Contains <span class="mono">{esc(acr)}_nodes.tsv</span> and <span class="mono">{esc(acr)}_edges.tsv</span>.</p>
      </section>
    </main>

    <aside class="side">
      <div class="card"><h3>Details</h3><div class="body">{details}</div></div>
      <div class="card"><h3>Provenance</h3><div class="body">
        <div class="row"><span class="lab">Transformed</span><span class="val num">{esc(date or '—')}</span></div>
        <div class="row" style="border:0"><span class="lab">Pipeline</span><span class="val">KG&#8209;Bioportal (ROBOT &rarr; KGX)</span></div>
      </div></div>
    </aside>
  </div>
</div>
""" + footer()

# --------------------------------------------------------------------------- #
#  build
# --------------------------------------------------------------------------- #
def build_reverse_index(kgs, all_by_id):
    """Map KG id -> [resources that list it as a primary source]."""
    idx = {}
    id_set = {r["id"] for r in kgs}
    for r in all_by_id.values():
        for p in r.get("products", []):
            for src in p.get("original_source", []):
                s = src.get("source")
                if s in id_set and s != r["id"]:
                    idx.setdefault(s, [])
                    if not any(e["id"] == r["id"] for e in idx[s]):
                        idx[s].append({"id": r["id"], "name": r.get("name") or r["id"]})
    return idx

def read_transform_date(onto_path):
    """Read site-wide transform_date from total_stats.yaml beside onto_stats.yaml."""
    if not onto_path:
        return ""
    total = os.path.join(os.path.dirname(onto_path) or ".", "total_stats.yaml")
    if not os.path.exists(total):
        return ""
    try:
        import yaml
    except ImportError:
        return ""
    with open(total) as f:
        return str((yaml.safe_load(f) or {}).get("transform_date", "") or "")

def main():
    argv = sys.argv[1:]
    onto_path = None
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--onto-stats":
            onto_path = argv[i + 1] if i + 1 < len(argv) else None
            i += 2
            continue
        if a.startswith("--"):
            i += 1
            continue
        pos.append(a)
        i += 1
    src = pos[0] if pos else "kgs.jsonld"
    out = pos[1] if len(pos) > 1 else "site"

    if "--fetch" in argv or not os.path.exists(src):
        print(f"fetching {REGISTRY_URL} -> {src}")
        urllib.request.urlretrieve(REGISTRY_URL, src)

    data = json.load(open(src))
    resources = data["resources"]
    all_by_id = {r["id"]: r for r in resources if "id" in r}
    kgs = [r for r in resources if r.get("category") == "KnowledgeGraph"]
    reverse_index = build_reverse_index(kgs, all_by_id)

    # Normalize both sources into unified browse items.
    kg_items = [kg_to_item(r) for r in kgs]
    transform_date = read_transform_date(onto_path)
    onto_entries = load_ontologies(onto_path)
    onto_items = [onto_to_item(o, transform_date) for o in onto_entries]
    items = kg_items + onto_items

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)

    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(render_browse(items, len(kg_items), len(onto_items)))

    # KG-Registry resource pages (rich).
    for r in kgs:
        d = os.path.join(out, "resource", r["id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(render_resource(r, reverse_index))

    # Transformed-ontology resource pages (only successful ones get a page).
    onto_pages = 0
    for it in onto_items:
        if not it["has_page"]:
            continue
        d = os.path.join(out, "resource", it["id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(render_ontology_resource(it))
        onto_pages += 1

    onto_skipped = len(onto_items) - onto_pages
    print(
        f"built browse index ({len(items)} rows) + {len(kgs)} KG pages "
        f"+ {onto_pages} ontology pages ({onto_skipped} ontologies listed without a page) -> {out}/"
    )

# --------------------------------------------------------------------------- #
#  styles (inlined into every page)
# --------------------------------------------------------------------------- #
CSS = r"""
/* Palette matched to the live BioPortal theme (theme-variables.scss.erb):
   primary #234979 · hover #2B5892 · secondary/gold #ffc107 · login #C58612
   light #F0F5F6 · panel #f5fafa · section #e2ebf0 · table line #c1dad7 */
:root{--page:#ffffff;--panel:#f5fafa;--panel-2:#e2ebf0;--ink:#1f2d3d;--ink-soft:#4f4f4f;
--ink-faint:#888888;--border:#cdd9dd;--border-strong:#b7c6cb;--nav:#234979;--nav-ink:#ffffff;
--nav-ink-soft:#b9cbe0;--primary:#234979;--primary-hover:#2b5892;--link:#234979;--node:#3875d7;
--edge:#c58612;--accent:#c58612;--chip:#e2ebf0;--chip-ink:#234979;--prod:#2f8f4e;--warn:#9a6a00;
--shadow:0 1px 2px rgba(31,45,61,.07),0 2px 8px rgba(31,45,61,.06);
--mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--c-chem:#6f4bb0;--c-var:#c58612;}
@media(prefers-color-scheme:dark){:root{--page:#0f1722;--panel:#16212e;--panel-2:#1b2836;
--ink:#e6edf3;--ink-soft:#aeb9c4;--ink-faint:#8493a0;--border:#28384a;--border-strong:#33465b;
--nav:#16304f;--nav-ink-soft:#9db3d0;--primary:#5b8cc9;--primary-hover:#77a2d8;--link:#7aa8de;
--node:#6ea3ea;--edge:#d9a441;--accent:#d69a2e;--chip:#1e3350;--chip-ink:#bcd3ef;--prod:#43b96a;--warn:#d6a25c;
--c-chem:#9f86d8;--c-var:#d9a441;--shadow:0 1px 2px rgba(0,0,0,.4),0 2px 10px rgba(0,0,0,.3);}}
:root[data-theme="light"]{--page:#ffffff;--panel:#f5fafa;--panel-2:#e2ebf0;--ink:#1f2d3d;--ink-soft:#4f4f4f;
--ink-faint:#888888;--border:#cdd9dd;--border-strong:#b7c6cb;--nav:#234979;--nav-ink-soft:#b9cbe0;
--primary:#234979;--primary-hover:#2b5892;--link:#234979;--node:#3875d7;--edge:#c58612;--accent:#c58612;
--chip:#e2ebf0;--chip-ink:#234979;--prod:#2f8f4e;--warn:#9a6a00;--c-chem:#6f4bb0;--c-var:#c58612;}
:root[data-theme="dark"]{--page:#0f1722;--panel:#16212e;--panel-2:#1b2836;--ink:#e6edf3;--ink-soft:#aeb9c4;
--ink-faint:#8493a0;--border:#28384a;--border-strong:#33465b;--nav:#16304f;--nav-ink-soft:#9db3d0;
--primary:#5b8cc9;--primary-hover:#77a2d8;--link:#7aa8de;--node:#6ea3ea;--edge:#d9a441;--accent:#d69a2e;
--chip:#1e3350;--chip-ink:#bcd3ef;--prod:#43b96a;--warn:#d6a25c;--c-chem:#9f86d8;--c-var:#d9a441;}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:3px}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}.mono{font-family:var(--mono)}
.muted{color:var(--ink-faint)}.mt{margin-top:8px}
.nav{background:var(--nav);color:var(--nav-ink);border-bottom:1px solid rgba(255,255,255,.06)}
.nav-in{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:22px;padding:0 22px;height:54px}
.brand{display:flex;align-items:baseline;gap:2px;font-weight:700;font-size:18px;letter-spacing:-.2px;color:#fff}
.brand:hover{text-decoration:none}.brand .kg{color:var(--primary);font-weight:800}
.navlinks{display:flex;gap:2px;margin-left:6px}
.navlinks a{color:var(--nav-ink-soft);padding:6px 10px;border-radius:6px;font-size:13.5px;font-weight:500}
.navlinks a:hover{color:#fff;background:rgba(255,255,255,.07);text-decoration:none}
.navlinks a.on{color:#fff;background:rgba(255,255,255,.10)}
.navlinks a.ext{display:inline-flex;align-items:center;gap:3px}
.extmark{opacity:.55;flex:none}
.nav-spacer{flex:1}
.navsearch{display:flex;align-items:center;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.12);border-radius:7px;padding:5px 9px;gap:7px;width:190px}
.navsearch input{background:transparent;border:0;color:#fff;font-size:13px;width:100%;outline:none}
.navsearch input::placeholder{color:var(--nav-ink-soft)}.navsearch svg{opacity:.7;flex:none}
.navlogin{background:var(--accent);color:#fff;font-size:13px;font-weight:600;padding:6px 14px;border-radius:6px}
.navlogin:hover{filter:brightness(1.08);text-decoration:none}
.protobar{background:repeating-linear-gradient(135deg,#d98a2b22,#d98a2b22 12px,#d98a2b11 12px,#d98a2b11 24px);border-bottom:1px solid var(--border)}
.protobar-in{max-width:1180px;margin:0 auto;padding:6px 22px;font-size:12.5px;color:var(--ink-soft);display:flex;align-items:center;gap:8px}
.proto-pill{background:var(--edge);color:#fff;font-weight:700;font-size:10.5px;letter-spacing:.5px;padding:2px 7px;border-radius:4px;text-transform:uppercase}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px}
.crumbs{padding:14px 0 4px;font-size:12.5px;color:var(--ink-faint)}
.crumbs a{color:var(--ink-soft)}.crumbs span{margin:0 7px;opacity:.5}
h1{margin:0;font-size:30px;letter-spacing:-.6px;font-weight:800;text-wrap:balance}
/* browse */
.browse-head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap;padding:6px 0 18px}
.browse-head .sub{margin:6px 0 0;color:var(--ink-soft)}
.browse-search{display:flex;align-items:center;gap:9px;background:var(--panel);border:1px solid var(--border);border-radius:9px;padding:10px 13px;min-width:300px;flex:1;max-width:420px}
.browse-search input{border:0;background:transparent;color:var(--ink);font-size:14px;width:100%;outline:none}
.browse-grid{display:grid;grid-template-columns:210px 1fr;gap:22px;padding-bottom:60px;align-items:start}
@media(max-width:820px){.browse-grid{grid-template-columns:1fr}}
.facets{position:sticky;top:16px}
.facets h3{font-size:11.5px;letter-spacing:.6px;text-transform:uppercase;color:var(--ink-faint);margin:0 0 10px}
.facet-list{display:flex;flex-direction:column;gap:4px}
.facet{display:flex;justify-content:space-between;align-items:center;background:transparent;border:1px solid transparent;
color:var(--ink-soft);font-family:inherit;font-size:13.5px;padding:6px 10px;border-radius:7px;cursor:pointer;text-align:left}
.facet:hover{background:var(--panel);color:var(--ink)}
.facet.on{background:var(--chip);color:var(--chip-ink);font-weight:600;border-color:color-mix(in srgb,var(--chip-ink) 20%,transparent)}
.facet .fc{font-family:var(--mono);font-size:11.5px;color:var(--ink-faint)}
.facet.on .fc{color:var(--chip-ink)}
.facet-clear{margin-top:12px;background:transparent;border:0;color:var(--link);font-size:12.5px;cursor:pointer;font-family:inherit;padding:4px 10px}
.browse-tbl{border-collapse:collapse;width:100%;font-size:14px;min-width:680px}
.browse-tbl thead th{position:sticky;top:0;background:var(--panel-2);text-align:left;font-size:11.5px;letter-spacing:.4px;
text-transform:uppercase;color:var(--ink-soft);font-weight:700;padding:10px 14px;border-bottom:1px solid var(--border)}
.browse-tbl tbody td{padding:12px 14px;border-bottom:1px solid var(--border);vertical-align:top}
.krow{cursor:pointer}.krow:hover{background:var(--panel)}
.c-name{max-width:440px}
.acr-link{font-family:var(--mono);font-weight:700;font-size:13px;letter-spacing:.2px}
.c-name .nm{font-weight:600;margin-top:1px}
.c-name .blurb{color:var(--ink-faint);font-size:12.5px;margin-top:3px;line-height:1.4}
.row-chips{margin-top:7px;display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.chip.sm{font-size:10.5px;padding:2px 8px}
.chip.sm.ver{font-family:var(--mono);text-transform:none}
.src-chip{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.3px;padding:2px 8px;border-radius:999px;border:1px solid transparent;white-space:nowrap}
.src-chip.kgreg{background:color-mix(in srgb,var(--c-chem) 15%,transparent);color:var(--c-chem);border-color:color-mix(in srgb,var(--c-chem) 30%,transparent)}
.src-chip.bp{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary);border-color:color-mix(in srgb,var(--primary) 32%,transparent)}
.c-num{white-space:nowrap}.c-fmt{white-space:nowrap}
.c-fmt .fmt{margin:0 3px 3px 0}
.stat{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.3px;padding:3px 9px;border-radius:999px}
.stat.ok{background:color-mix(in srgb,var(--prod) 15%,transparent);color:var(--prod)}
.stat.warn{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
.noresults{padding:26px;text-align:center;color:var(--ink-faint)}
/* resource */
.head{display:flex;align-items:flex-start;gap:18px;padding:8px 0 16px;flex-wrap:wrap}
.head-main{flex:1;min-width:280px}
.acr{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.status{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:11.5px;padding:4px 10px;border-radius:999px;text-transform:uppercase;letter-spacing:.4px}
.status.ok{background:color-mix(in srgb,var(--prod) 16%,transparent);color:var(--prod)}
.status.warn{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
.status .dot{width:7px;height:7px;border-radius:50%;background:currentColor}
.fullname{margin:6px 0 0;color:var(--ink-soft);font-size:17px}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}
.chip{background:var(--chip);color:var(--chip-ink);font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px;border:1px solid color-mix(in srgb,var(--chip-ink) 18%,transparent)}
.head-cta{display:flex;flex-direction:column;gap:9px;min-width:200px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;font-weight:600;font-size:14px;padding:10px 16px;border-radius:8px;border:1px solid transparent;cursor:pointer;font-family:inherit}
.btn:hover{text-decoration:none}
.btn-primary{background:var(--primary);color:#fff;box-shadow:var(--shadow)}.btn-primary:hover{background:var(--primary-hover)}
.btn-ghost{background:var(--page);color:var(--ink);border-color:var(--border-strong)}.btn-ghost:hover{background:var(--panel)}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-top:2px;overflow-x:auto}
.tab{padding:11px 15px;font-size:14px;font-weight:600;color:var(--ink-soft);border-bottom:2px solid transparent;white-space:nowrap;cursor:pointer}
.tab:hover{color:var(--ink)}.tab.on{color:var(--primary);border-bottom-color:var(--primary)}
.tab .cnt{font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);margin-left:6px}
.grid{display:grid;grid-template-columns:1fr 320px;gap:26px;padding:24px 0 60px;align-items:start}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
section.block{margin-bottom:26px}
.eyebrow{font-size:11.5px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:var(--ink-faint);margin:0 0 10px}
.eb-count{font-family:var(--mono);color:var(--ink-soft);margin-left:4px}
.lead{font-size:15.5px;margin:0;max-width:64ch}
.visline{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-soft);margin-bottom:12px}
.visline b{color:var(--ink)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:640px){.metrics{grid-template-columns:repeat(2,1fr)}}
.metric{background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:14px}
.metric .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:22px;font-weight:700;letter-spacing:-.5px}
.metric .k{font-size:12px;color:var(--ink-soft);margin-top:3px}
.metric.node{border-top:3px solid var(--node)}.metric.edge{border-top:3px solid var(--edge)}
.metric.cat{border-top:3px solid var(--c-chem)}.metric.pred{border-top:3px solid var(--primary)}
.cloud{display:flex;flex-wrap:wrap;gap:6px}
.tok{font-size:12px;padding:4px 9px;border-radius:6px;border:1px solid var(--border);background:var(--panel)}
.tok.cat{color:var(--c-chem);border-color:color-mix(in srgb,var(--c-chem) 30%,transparent)}
.tok.pred{color:var(--ink-soft);font-family:var(--mono);font-size:11.5px}
.tok.more{color:var(--ink-faint);background:transparent;border-style:dashed}
.prod-list{display:flex;flex-direction:column;gap:9px}
.prod{display:flex;align-items:center;gap:13px;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.prod:hover{border-color:var(--border-strong)}
.fmt{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.3px;padding:4px 8px;border-radius:5px;flex:none;text-transform:uppercase;min-width:60px;text-align:center;display:inline-block}
.fmt.kgx{background:color-mix(in srgb,var(--node) 15%,transparent);color:var(--node)}
.fmt.jsonl{background:color-mix(in srgb,var(--edge) 16%,transparent);color:var(--edge)}
.fmt.rdf{background:color-mix(in srgb,var(--c-chem) 15%,transparent);color:var(--c-chem)}
.fmt.neo4j{background:color-mix(in srgb,var(--primary) 15%,transparent);color:var(--primary)}
.fmt.duckdb{background:color-mix(in srgb,var(--c-var) 18%,transparent);color:var(--c-var)}
.prod-main{flex:1;min-width:0}.prod-main .t{font-weight:600;font-size:14px}
.prod-main .f{font-family:var(--mono);font-size:12px;color:var(--ink-faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prod-size{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:12.5px;color:var(--ink-soft);flex:none}
.dl{flex:none;color:var(--primary);display:inline-flex;padding:6px;border-radius:6px}
.dl:hover{background:color-mix(in srgb,var(--primary) 12%,transparent)}
.tbl-scroll{overflow-x:auto;border:1px solid var(--border);border-radius:10px}
.side{position:sticky;top:16px;display:flex;flex-direction:column;gap:16px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden}
.card h3{margin:0;padding:12px 15px;font-size:12.5px;letter-spacing:.5px;text-transform:uppercase;color:var(--ink-soft);border-bottom:1px solid var(--border);background:var(--panel-2)}
.card .body{padding:6px 15px 13px}
.row{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13.5px}
.row:last-child{border-bottom:0}
.row .lab{color:var(--ink-faint);width:92px;flex:none;font-size:12.5px}
.row .val{color:var(--ink);min-width:0;overflow-wrap:anywhere}
.person{display:flex;flex-direction:column;gap:2px;padding:9px 0;border-bottom:1px solid var(--border)}
.person:last-child{border-bottom:0}.person .nm{font-weight:600;font-size:13.5px}
.person .mt{font-size:12px;color:var(--ink-faint)}.person .mt a{color:var(--link)}
.rel{display:flex;flex-direction:column;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}
.rel:last-child{border-bottom:0}.rel .rn{font-weight:600}
.rel .rk{font-size:11.5px;color:var(--ink-faint);font-family:var(--mono)}
.rel .rd{font-size:11.5px;color:var(--edge);font-weight:600;margin-top:2px}
.uploaded{font-size:12px;color:var(--ink-faint)}
footer{border-top:1px solid var(--border);background:var(--panel);color:var(--ink-soft)}
.foot-in{max-width:1180px;margin:0 auto;padding:22px;font-size:12.5px;display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
footer b{color:var(--ink)}
"""

if __name__ == "__main__":
    main()
