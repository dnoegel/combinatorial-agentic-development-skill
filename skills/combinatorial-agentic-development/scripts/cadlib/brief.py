"""Self-contained instructions for implementing one node.

A brief is what you hand to a (possibly cheaper) model or a teammate: the
node's scope, where to branch, which files it owns, what it must not touch,
how to prove it works, and what "done" means. It is deliberately short.
"""

from .render import GUIDANCE
from .stack import effective_onto

__all__ = ["brief", "next_node", "commit_subject"]


def commit_subject(spec, node):
    if node.kind == "option":
        dim_id, option = node.options[0]
        dim = spec.dimensions[dim_id]
        label = dim.option(option).label
        return f"Add {label[:1].lower() + label[1:]} {dim.label[:1].lower() + dim.label[1:]}"
    return node.title


def next_node(stack, statuses):
    """First node in stack order without a branch whose parent is ready."""
    for nid in stack.order:
        if statuses.get(nid, "planned") != "planned":
            continue
        parent = stack.placements[nid].parent
        if parent is None or statuses.get(parent, "planned") != "planned":
            return nid
    return None


def brief(result, node_id, statuses, doc_path, start_ref):
    spec, plan, stack = result.spec, result.plan, result.stack
    node = plan.by_id[node_id]
    p = stack.placements[node_id]
    onto = effective_onto(stack, {k: {"status": v} for k, v in statuses.items()}, node_id)
    start = start_ref if onto == stack.base_branch else onto
    others = sorted({f for n in plan.nodes if n.id != node_id for f in n.files} - set(node.files))
    test_cmd = spec.verify.get("test", "the project's test command")
    probe = spec.verify.get("probe")

    L = [f"# Brief: `{node_id}`, {node.title}", ""]
    L.append(f"Part of the {spec.title} plan ({doc_path}). The plan is approved; do not edit it.")
    L += [
        "", "## Branch", "", "```bash",
        f"git switch -c {p.branch} {start}",
        f"git update-ref refs/cad/base/{p.branch} {start}   # remembers the fork point for later restacks",
        "```", "",
    ]
    if p.waits_for:
        L.append(f"Start only after {', '.join(f'`{w}`' for w in p.waits_for)} are merged into `{stack.base_branch}`.")
        L.append("")
    L += ["## Goal", "", node.purpose, "", f"**Scope.** {node.scope}", ""]
    if node.kind != "base":
        L.append(f"**Decisions.** {', '.join(f'`{d}`' for d in node.decisions)}")
        L.append("")
    if node.depends_on:
        L.append(f"**Already available on your parent branch:** {', '.join(f'`{d}`' for d in node.depends_on)}.")
        L.append("")
    L += ["## Files", ""]
    L.append(f"- Owns: {', '.join(f'`{f}`' for f in node.files)}" if node.files else "- Owns: new files for this node only; keep them in the node's own module or directory.")
    if others:
        L.append(f"- Do not edit (owned by other nodes): {', '.join(f'`{f}`' for f in others)}")
    L.append("- Never edit the planning document.")
    L += ["", "## Guidance", "", node.guidance or GUIDANCE[node.kind], ""]
    L += ["## Tests", ""] + [f"- {t}" for t in node.tests]
    L += ["", "## Done when", ""] + [f"- [ ] {a}" for a in node.acceptance]
    L.append(f"- [ ] `{test_cmd}` passes on `{p.branch}`.")
    if probe:
        L.append(f"- [ ] The probe (`{probe}`) reports this node's options when they are selected.")
    L += [
        "",
        "## Commit",
        "",
        f"Subject: `{commit_subject(spec, node)}` (imperative, at most 72 characters).",
        "Body: a blank line, then short bullet points of what changed. No tool or agent attribution.",
        "",
        "## Rules",
        "",
        "- Stay on this branch. Do not push, do not create other branches, do not rebase other branches.",
        "- Work that belongs to another node waits for that node.",
        "- If something in this brief cannot be done as written, stop and report it instead of working around it.",
        "- Report: the commit hash, the test output summary, and any deviation from this brief.",
    ]
    return "\n".join(L) + "\n"
