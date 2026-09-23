"""Stack placement: turn the node dependency graph into branches.

A git branch has exactly one parent, while a node can depend on several
nodes. Placement keeps every dependency reachable:

linear  every node sits on the previous node in topological order.
tree    every node sits on its deepest dependency. When dependencies live on
        different lanes, one lane is grafted onto the other if every moved
        node keeps its own dependencies. If that is impossible, the node
        starts from the base branch in a later wave, after its dependencies
        have merged.

Progress matters: merged nodes count as part of the base branch, and lanes
that contain started work (branched or MR open) are never moved.

Placement is deterministic for a given plan.
"""

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

    def depth(self, node_id):
        depth = 0
        cur = node_id
        while cur is not None:
            depth += 1
            cur = self.placements[cur].parent
        return depth

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


def place(plan, layout="tree", base_branch="main", prefix="", state=None):
    state = state or {}
    merged = {n for n, v in state.items() if (v or {}).get("status") == "merged"}
    started = {n for n, v in state.items() if (v or {}).get("status") in ("branched", "mr-open")}
    deps = {n.id: list(n.depends_on) for n in plan.nodes}
    rank = {nid: i for i, nid in enumerate(plan.order)}
    parent = {}
    wave = {}
    waits = {}
    grafted = {}

    def chain(x):
        out = []
        while x is not None:
            out.append(x)
            x = parent[x]
        return out

    def covered(dep, x):
        return dep in merged or dep in chain(x) or wave[dep] < wave[x]

    def subtree(u):
        return [n for n in parent if u in chain(n)]

    def try_place(nid, ds):
        ranked = sorted(ds, key=lambda d: (wave[d], d in started, len(chain(d)), rank[d]), reverse=True)
        tip = ranked[0]
        for u in ranked[1:]:
            if covered(u, tip):
                continue
            if wave[u] != wave[tip]:
                return False
            moved = subtree(u)
            if any(m in started for m in moved):
                return False
            base_chain = set(chain(tip))
            for s in moved:
                path = set(x for x in chain(s) if x in moved)
                for dep in deps[s]:
                    if dep in merged or dep in base_chain or dep in path or wave[dep] < wave[tip]:
                        continue
                    return False
            parent[u] = tip
            grafted[u] = nid
            tip = u
        parent[nid] = tip
        wave[nid] = wave[tip]
        return True

    prev = None
    for nid in plan.order:
        ds = deps[nid]
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


def effective_onto(stack, state, node_id):
    """Branch a node should target now: its parent, or the base branch once the parent merged."""
    p = stack.placements[node_id]
    if p.parent is None or state.get(p.parent, {}).get("status") == "merged":
        return stack.base_branch
    return p.parent_branch


def _q(text):
    return shlex.quote(text)


def steps(plan, stack, state, platform, descriptions_dir=".cad/mr", remote=True):
    """Describe the dry-run steps for every node, respecting recorded progress.

    `state` maps node id to {status, mr, restack_from}. Without a remote, root
    branches start from the local base branch and push/MR commands are left out.
    Returns a list of dicts with a `node`, `action` and `commands` list.
    """
    out = []
    base = stack.base_branch
    if not remote:
        platform = "none"
    by_id = plan.by_id
    for nid in stack.order:
        p = stack.placements[nid]
        node = by_id[nid]
        st = state.get(nid, {})
        status = st.get("status", "planned")
        parent_status = state.get(p.parent, {}).get("status") if p.parent else None
        onto = base if parent_status == "merged" or p.parent is None else p.parent_branch
        start = (f"origin/{base}" if remote else base) if onto == base else onto
        entry = {
            "node": nid,
            "title": node.title,
            "branch": p.branch,
            "target": onto,
            "wave": p.wave,
            "status": status,
            "action": "",
            "commands": [],
        }
        desc = f"{descriptions_dir}/{p.branch.replace('/', '__')}.md"
        if status == "merged":
            entry["action"] = "done"
        elif status == "planned":
            entry["action"] = "create"
            entry["commands"] = [
                f"git switch -c {_q(p.branch)} {_q(start)}",
                f"git update-ref refs/cad/base/{p.branch} {_q(start)}",
                f"# implement {nid} (cad.py brief <doc> {nid}), run its tests, commit",
            ]
            if remote:
                entry["commands"].append(f"git push -u origin {_q(p.branch)}")
            if platform == "gitlab":
                entry["commands"].append(
                    f"glab mr create --draft --source-branch {_q(p.branch)} --target-branch {_q(onto)} "
                    f"--title {_q(node.title)} --description \"$(cat {_q(desc)})\" --yes"
                )
            elif platform == "github":
                entry["commands"].append(
                    f"gh pr create --draft --head {_q(p.branch)} --base {_q(onto)} "
                    f"--title {_q(node.title)} --body-file {_q(desc)}"
                )
        else:
            old = st.get("restack_from")
            if old or parent_status == "merged":
                entry["action"] = "restack"
                old_base = old or p.parent_branch
                if parent_status == "merged":
                    old_base = p.parent_branch
                entry["commands"] = [f"git rebase --onto {_q(start)} {_q(old_base)} {_q(p.branch)}"]
                if remote:
                    entry["commands"] = ["git fetch origin"] + entry["commands"] + [
                        f"git push --force-with-lease origin {_q(p.branch)}"
                    ]
                mr = st.get("mr")
                if status == "mr-open" and mr:
                    if platform == "gitlab":
                        entry["commands"].append(f"glab mr update {_q(str(mr).lstrip('!#'))} --target-branch {_q(onto)}")
                    elif platform == "github":
                        entry["commands"].append(f"gh pr edit {_q(str(mr).lstrip('!#'))} --base {_q(onto)}")
            else:
                entry["action"] = "keep"
        out.append(entry)
    return out
