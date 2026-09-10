"""The top of a graph's hierarchy, laid out for review (#169).

Where the seed table stops, a person -- or an agent -- has to read an
ontology's roots and say what is beneath them. This module writes what they
need to read: the top-level terms ranked by how many uncategorized nodes hang
off each, their children ranked the same way, and a few labels from beneath
each child. It is the packet the entries in ``reviewed_roots.yaml`` were made
from, and it is deterministic, so a reviewer's verdict can be checked against
the same view later.

Runs over the node and edge files KGX wrote, the way ``categories`` does, and
reads the hierarchy through the same predicates.
"""

import collections
import io
import os
import tarfile
from typing import Dict, Iterable, List, Optional, Set, Tuple

import yaml

from kg_bioportal.categories import HIERARCHY_PREDICATES, NAMED_THING, _columns

# How much of the top to show. Enough to see the shape of an ontology, not so
# much that a 200,000-node graph becomes a 200,000-line packet.
TOP_ROOTS = 8
TOP_CHILDREN = 12
SAMPLE = 6


def _is_uncategorized(category: str) -> bool:
    return not category or category == NAMED_THING


def read_hierarchy(
    node_file: str, edge_file: str
) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, List[str]], Dict[str, List[str]]]:
    """``(nodes, children, parents)``: id -> (name, category), and the hierarchy both ways."""
    nodes: Dict[str, Tuple[str, str]] = {}
    for node_id, name, category in _columns(node_file, "id", "name", "category"):
        if node_id:
            nodes[node_id] = (name, category)
    children: Dict[str, List[str]] = collections.defaultdict(list)
    parents: Dict[str, List[str]] = collections.defaultdict(list)
    for subject, predicate, obj in _columns(edge_file, "subject", "predicate", "object"):
        if not subject or not obj or subject == obj:
            continue
        parent_end = HIERARCHY_PREDICATES.get(predicate)
        if parent_end == "object":
            parent, child = obj, subject
        elif parent_end == "subject":
            parent, child = subject, obj
        else:
            continue
        children[parent].append(child)
        parents[child].append(parent)
    return nodes, children, parents


def descendants(children: Dict[str, List[str]], start: str) -> Set[str]:
    """Everything beneath ``start``, cycles included once."""
    seen: Set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for child in children.get(node, ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def review_packet(
    node_file: str,
    edge_file: str,
    ontology_name: str = "",
    top_roots: int = TOP_ROOTS,
    top_children: int = TOP_CHILDREN,
    sample: int = SAMPLE,
) -> Dict[str, object]:
    """What a reviewer reads: the roots, their children, and what is beneath.

    A root here is a term with narrower terms and no broader one. Roots and
    children are ranked by the uncategorized nodes beneath them, because those
    are the ones a review can still do something about; a root whose subtree is
    already categorized is not worth anyone's time and is left out.
    """
    nodes, children, parents = read_hierarchy(node_file, edge_file)

    def name(node: str) -> str:
        return nodes.get(node, ("", ""))[0]

    def category(node: str) -> str:
        return nodes.get(node, ("", ""))[1]

    def weigh(node: str) -> Tuple[int, int]:
        below = descendants(children, node)
        return sum(1 for n in below if _is_uncategorized(category(n))), len(below)

    total = len(nodes)
    uncategorized = sum(1 for _, cat in nodes.values() if _is_uncategorized(cat))
    packet: Dict[str, object] = {
        "ontology": ontology_name,
        "nodes": total,
        "uncategorized": uncategorized,
        "hierarchy_edges": sum(len(v) for v in children.values()),
        "roots": [],
    }

    tops = [n for n in children if not parents.get(n)]
    ranked = sorted(((weigh(t), t) for t in tops), key=lambda x: (-x[0][0], -x[0][1], x[1]))
    reach: Set[str] = set()
    for (open_below, below), top in ranked[:top_roots]:
        if not open_below:
            break
        kids = children.get(top, [])
        kid_ranked = sorted(
            ((weigh(k), k) for k in kids), key=lambda x: (-x[0][0], -x[0][1], x[1])
        )
        entry: Dict[str, object] = {
            "id": top,
            "label": name(top),
            "category": category(top),
            "descendants": below,
            "uncategorized_descendants": open_below,
            "n_children": len(kids),
            "children": [
                {
                    "id": kid,
                    "label": name(kid),
                    "category": category(kid),
                    "descendants": kid_below,
                    "uncategorized_descendants": kid_open,
                    "n_children": len(children.get(kid, ())),
                    "sample": [name(g) or g for g in children.get(kid, ())[:sample]],
                }
                for (kid_open, kid_below), kid in kid_ranked[:top_children]
            ],
        }
        packet["roots"].append(entry)
        reach |= {n for n in descendants(children, top) if _is_uncategorized(category(n))}
    packet["reachable_from_roots"] = len(reach)
    return packet


def open_graph(path: str, workdir: str) -> Tuple[str, str]:
    """The node and edge files of a graph, unpacking a ``.tar.gz`` if given one."""
    if os.path.isdir(path):
        files = sorted(os.listdir(path))
        node_file = next(os.path.join(path, f) for f in files if f.endswith("_nodes.tsv"))
        edge_file = next(os.path.join(path, f) for f in files if f.endswith("_edges.tsv"))
        return node_file, edge_file
    if path.endswith(".tar.gz") or path.endswith(".tgz"):
        with tarfile.open(path) as tar:
            members = [m for m in tar.getmembers() if m.name.endswith(".tsv")]
            for member in members:
                member.name = os.path.basename(member.name)
            try:
                tar.extractall(workdir, members=members, filter="data")
            except TypeError:  # Python < 3.12 has no filter argument
                tar.extractall(workdir, members=members)
        return open_graph(workdir, workdir)
    raise ValueError(f"{path}: expected a directory of KGX TSVs or a .tar.gz of them")


def format_packet(packet: Dict[str, object]) -> str:
    """The packet as YAML, which is also what the reviewed-roots file is."""
    return yaml.safe_dump(packet, sort_keys=False, allow_unicode=True, width=120)
