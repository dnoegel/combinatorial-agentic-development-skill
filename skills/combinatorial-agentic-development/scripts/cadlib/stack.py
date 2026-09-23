"""Stack placement: turn the node dependency graph into branches.

A git branch has exactly one parent, while a node can depend on several
nodes. Placement keeps every dependency reachable:

linear  every node sits on the previous node in topological order.
tree    every node sits on its deepest dependency. When dependencies live on
        different lanes, one lane is grafted onto the other if every moved
        node keeps its own dependencies. Of the possible grafts, the one that
        stacks the fewest nodes on code they do not need wins. If even the
        best graft would do that to more than `max_coupling` nodes, the node
        starts in a later wave instead, so unrelated options stay independent. If that is impossible, the node
        starts from the base branch in a later wave, after its dependencies
        have merged.

Progress matters: merged nodes count as part of the base branch, and lanes
that contain started work (branched or MR open) are never moved.

Placement is deterministic for a given plan.
"""

import itertools
import re
import shlex
from dataclasses import dataclass, field

__all__ = ["Placement", "Stack", "place", "branch_slug", "steps"]


@dataclass
class Placement:
    node: str
    branch: str
    parent: object  # node id or None for the base branch
    parent_branch: str
    wave: int
    waits_for: list = field(default_factory=list)
    grafted_for: object = None  # node that needed this branch moved onto another lane


@dataclass
class Stack:
    layout: str
    base_branch: str
    placements: dict
    order: list  # creation and merge order

    @property
    def waves(self):
        return max((p.wave for p in self.placements.values()), default=0) + 1

    @property
    def lanes(self):
        parents = {p.parent for p in self.placements.values()}
        return sum(1 for nid in self.placements if nid not in parents)

    def children(self, node_id):
        return [n for n in self.order if self.placements[n].parent == node_id]


def branch_slug(node_id):
    if node_id == "base":
        return "base"
    kind, _, rest = node_id.partition(".")
    slug = rest.replace(".", "-") if kind in ("dim", "opt", "ix") else node_id
    return re.sub(r"[^a-z0-9-]+", "-", slug.lower().replace("_", "-")).strip("-")


def _branches(plan, prefix):
    names = {}
    used = set()
    for node in plan.nodes:
        slug = branch_slug(node.id)
        if slug in used:
            slug = f"{slug}-{node.kind}"
        used.add(slug)
        names[node.id] = f"{prefix}/{slug}" if prefix else slug
    return names


def place(plan, layout="tree", base_branch="main", prefix="", state=None, max_coupling=2):
    state = state or {}
    merged = {n for n, v in state.items() if (v or {}).get("status") == "merged"}
    started = {n for n, v in state.items() if (v or {}).get("status") in ("branched", "mr-open")}
    deps = {n.id: list(n.depends_on) for n in plan.nodes}
    rank = {nid: i for i, nid in enumerate(plan.order)}
    parent = {}
    wave = {}
    waits = {}
    grafted = {}

    # reach: everything that builds on a node (it moves along when the node moves).
    # needs: everything a node builds on. A graft "costs" the nodes that end up
    # stacked on code they do not need.
    reach = {n.id: {n.id} for n in plan.nodes}
    for nid in reversed(plan.order):
        for other in plan.nodes:
            if nid in other.depends_on:
                reach[nid] |= reach[other.id]
    needs = {nid: set() for nid in plan.order}
    for nid in plan.order:
        for d in deps[nid]:
            needs[nid] |= {d} | needs[d]

    def chain(x, par=None):
        par = parent if par is None else par
        out = []
        while x is not None:
            out.append(x)
            x = par[x]
        return out

    def subtree(u, par):
        return [n for n in par if u in chain(n, par)]

    def attempt(nid, order):
        """Graft the other dependencies' lanes under the first one. Returns (cost, parents, grafts, tip)."""
        par = dict(parent)
        grafts = {}
        cost = 0
        tip = order[0]
        for u in order[1:]:
            tip_chain = chain(tip, par)
            if u in merged or u in tip_chain or wave[u] < wave[tip]:
                continue
            if wave[u] != wave[tip]:
                return None
            root = u  # the top of u's lane: the ancestor just below the tip's chain
            while par[root] is not None and par[root] not in tip_chain:
                root = par[root]
            moved = subtree(root, par)
            if any(m in started for m in moved):
                return None
            base_chain = set(tip_chain)
            for m in moved:
                path = {x for x in chain(m, par) if x in moved}
                for dep in deps[m]:
                    if dep in merged or dep in base_chain or dep in path or wave[dep] < wave[tip]:
                        continue
                    return None
            par[root] = tip
            grafts[root] = nid
            coupled = set().union(*(reach[m] for m in moved))
            cost += sum(1 for x in coupled if tip not in needs[x])
            tip = u
        return cost, par, grafts, tip

    def try_place(nid, ds):
        ranked = sorted(ds, key=lambda d: (wave[d], d in started, len(chain(d)), rank[d]), reverse=True)
        orders = list(itertools.permutations(ranked)) if len(ranked) <= 4 else [tuple(ranked)]
        best = None
        for order in orders:
            outcome = attempt(nid, order)
            if outcome is not None and (best is None or outcome[0] < best[0]):
                best = outcome
        if best is None or best[0] > max_coupling:
            return False
        _, par, grafts, tip = best
        parent.clear()
        parent.update(par)
        grafted.update(grafts)
        parent[nid] = tip
        wave[nid] = wave[tip]
        return True

    # Started branches keep the parent they were built on (recorded as `onto`),
    # as long as that parent still covers their dependencies.
    names_early = _branches(plan, prefix)
    by_branch = {b: n for n, b in names_early.items()}
    pins = {}
    for nid in plan.order:
        entry = state.get(nid) or {}
        if nid in started and entry.get("onto"):
            onto = entry["onto"]
            if onto == base_branch:
                pins[nid] = None
            elif by_branch.get(onto) not in (None, nid):
                pins[nid] = by_branch[onto]
    order = _order_with_pins(plan.order, deps, pins, rank)

    def pinned(nid):
        par = pins[nid]
        if par is not None and par not in parent:
            return False
        ancestors = set(chain(par)) if par is not None else set()
        base_wave = wave[par] if par is not None else 0
        for d in deps[nid]:
            if d in merged or d in ancestors or (d in wave and wave[d] < base_wave):
                continue
            return False
        parent[nid], wave[nid] = par, base_wave
        return True

    prev = None
    for nid in order:
        ds = deps[nid]
        if layout != "linear" and nid in pins and pinned(nid):
            continue
        if layout == "linear":
            parent[nid], wave[nid] = prev, 0
            prev = nid
            continue
        if not ds:
            parent[nid], wave[nid] = None, 0
            continue
        saved = dict(parent), dict(wave), dict(grafted)
        if not try_place(nid, ds):
            parent.clear()
            parent.update(saved[0])
            wave.clear()
            wave.update(saved[1])
            grafted.clear()
            grafted.update(saved[2])
            parent[nid] = None
            wave[nid] = 1 + max(wave[d] for d in ds if d not in merged)
            waits[nid] = list(ds)

    # Creation order: parents first, then wave, then plan order.
    remaining = set(parent)
    order = []
    while remaining:
        ready = [n for n in remaining if parent[n] is None or parent[n] in order]
        pick = min(ready, key=lambda n: (wave[n], rank[n]))
        order.append(pick)
        remaining.remove(pick)

    names = _branches(plan, prefix)
    placements = {
        nid: Placement(
            node=nid,
            branch=names[nid],
            parent=parent[nid],
            parent_branch=names[parent[nid]] if parent[nid] else base_branch,
            wave=wave[nid],
            waits_for=waits.get(nid, []),
            grafted_for=grafted.get(nid),
        )
        for nid in order
    }
    return Stack(layout=layout, base_branch=base_branch, placements=placements, order=order)


def _order_with_pins(order, deps, pins, rank):
    """Plan order, adjusted so a pinned parent is placed before its child. Pins that would cycle are dropped."""
    edges = {n: set(deps[n]) for n in order}
    for child, par in list(pins.items()):
        if par is None:
            continue
        edges[child].add(par)
        # drop the pin if it creates a cycle
        seen, stack = set(), [par]
        while stack:
            cur = stack.pop()
            if cur == child:
                edges[child].discard(par)
                del pins[child]
                break
            if cur not in seen:
                seen.add(cur)
                stack.extend(edges.get(cur, ()))
    remaining = {n: set(e) for n, e in edges.items()}
    out = []
    while remaining:
        ready = sorted((n for n, e in remaining.items() if not e), key=rank.get)
        pick = ready[0]
        out.append(pick)
        del remaining[pick]
        for e in remaining.values():
            e.discard(pick)
    return out


def effective_onto(stack, state, node_id):
    """Branch a node should target now: its parent, or the base branch once the parent merged."""
    p = stack.placements[node_id]
    if p.parent is None or state.get(p.parent, {}).get("status") == "merged":
        return stack.base_branch
    return p.parent_branch


def _q(text):
    return shlex.quote(text)


def steps(plan, stack, state, remote=True):
    """Dry-run git steps, in stack order, for every node that has no branch yet.

    `state` maps node id to {"status": ...} as read from git. Without a remote,
    root branches start from the local base branch.
    """
    out = []
    base = stack.base_branch
    for nid in stack.order:
        p = stack.placements[nid]
        status = (state.get(nid) or {}).get("status", "planned")
        onto = effective_onto(stack, state, nid)
        start = (f"origin/{base}" if remote else base) if onto == base else onto
        entry = {"node": nid, "title": plan.by_id[nid].title, "branch": p.branch, "target": onto,
                 "wave": p.wave, "status": status, "commands": []}
        if status == "planned":
            entry["commands"] = [
                f"git switch -c {_q(p.branch)} {_q(start)}",
                f"git update-ref refs/cad/base/{p.branch} {_q(start)}",
                f"# implement {nid} (cad.py brief <doc> {nid}), run its tests, commit",
            ]
        out.append(entry)
    return out
