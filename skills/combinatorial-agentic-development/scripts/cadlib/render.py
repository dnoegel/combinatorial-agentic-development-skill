"""Rendering: terminal receipt, Markdown sections, Mermaid diagrams, MR text."""

import re

from .stack import effective_onto

__all__ = [
    "receipt", "generated_markdown", "decision_diagram", "constraint_map",
    "stack_diagram", "mr_description",
]

PLACEHOLDER = "_to fill in from the repository_"
MODE_TEXT = {
    "exhaustive": "every valid variant is a test scenario",
    "pairwise": "every pair of option values that can occur together is tested at least once",
    "twise": "every combination of {t} option values that can occur together is tested at least once",
    "selected": "only the variants listed in the spec are targeted",
}
HONESTY = {
    "exhaustive": "The test matrix contains every valid variant.",
    "pairwise": (
        "Pairwise coverage tests every pair of decisions, not every product. "
        "{untested} of {valid} valid variants are configurable but have no dedicated scenario."
    ),
    "twise": (
        "{t}-wise coverage tests every combination of {t} decisions, not every product. "
        "{untested} of {valid} valid variants are configurable but have no dedicated scenario."
    ),
    "selected": (
        "Only the selected variants are targeted. {configurable} of {valid} valid variants can be "
        "configured from the implemented options; {untested} of them have no dedicated scenario."
    ),
}
GUIDANCE = {
    "base": (
        "Prefer one configuration object over scattered flags. Validate it at startup with the same "
        "rules as the constraint table, so an invalid combination fails fast and loudly. Own the "
        "composition root here and let it discover option modules at runtime, so parallel option "
        "branches never touch the same file. Add the probe now: it proves later that every option "
        "is wired in."
    ),
    "dimension": (
        "Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. "
        "A no-op option is a real implementation of the interface; keep if-statements out of the call sites."
    ),
    "option": (
        "Touch only the new implementation and its registration. If the interface has to change, "
        "that change belongs in the abstraction node."
    ),
    "interaction": (
        "Keep the glue at the composition root or in a small coordinator, so each option still "
        "works without the other."
    ),
    "followup": (
        "Change only what the contract changes list. The original node is merged, so this is a normal "
        "new commit on top of the base branch; never rewrite merged history."
    ),
}
RISK_TEXT = {
    "base": "Touches wiring shared by every variant.",
    "dimension": "Every option of this dimension builds on the interface introduced here.",
    "option": "Isolated to one option behind an interface.",
    "interaction": "Couples options; regressions only show up in combined scenarios.",
    "followup": "Changes code that is already merged and that other nodes build on.",
}


def _n(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _mid(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _label(text):
    return str(text).replace('"', "#quot;")


def _dim_label(spec, d):
    return spec.dimensions[d].label


# ---------------------------------------------------------------- diagrams

def decision_diagram(spec, space, max_nodes=60):
    """Reduced decision diagram of the valid variants.

    Every path from left to right is exactly one valid variant. Subtrees with
    identical continuations are merged, and decisions that do not apply are
    skipped, so the diagram stays small while losing nothing.
    """
    dims = space.dims
    memo = {}
    nodes = []  # (id, level)
    edges = {}  # (src, dst) -> [values]

    def build(level, suffixes):
        if level == len(dims):
            return "done"
        key = (level, suffixes)
        if key in memo:
            return memo[key]
        groups = {}
        for s in suffixes:
            groups.setdefault(s[0], set()).add(s[1:])
        if list(groups) == [None]:
            result = build(level + 1, frozenset(groups[None]))
            memo[key] = result
            return result
        nid = f"n{len(nodes)}"
        nodes.append((nid, level))
        memo[key] = nid
        order = spec.dimensions[dims[level]].option_ids
        for value in sorted(groups, key=lambda v: order.index(v) if v in order else -1):
            child = build(level + 1, frozenset(groups[value]))
            if value is None:
                value = "n/a"
            edges.setdefault((nid, child), []).append(value)
        return nid

    if not space.valid:
        return None
    build(0, frozenset(space.valid))
    if len(nodes) > max_nodes:
        return None
    lines = ["flowchart LR"]
    for nid, level in nodes:
        lines.append(f'  {nid}(["{_label(_dim_label(spec, dims[level]))}"])')
    lines.append(f'  done(["{len(space.valid)} valid variants"])')
    rank = {nid: i for i, (nid, _) in enumerate(nodes)}
    for (src, dst), values in sorted(edges.items(), key=lambda e: (rank[e[0][0]], rank.get(e[0][1], len(rank)))):
        label = " / ".join(values)
        arrow = "-.->" if values == ["n/a"] else "-->"
        lines.append(f'  {src} {arrow}|"{_label(label)}"| {dst}')
    lines.append("  classDef valid fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20")
    lines.append("  class done valid")
    return "\n".join(lines)


def _opt_id(d, o):
    return f"o_{_mid(d)}__{_mid(o)}"


def constraint_map(spec, space, plan):
    """Dimensions as boxes, options inside, constraints as edges."""
    if not spec.constraints and not any(d.applies_when for d in spec.dimensions.values()):
        return None
    lines = ["flowchart LR"]
    noop, dead, out = [], [], []
    for d, dim in spec.dimensions.items():
        lines.append(f'  subgraph d_{_mid(d)}["{_label(dim.label)}"]')
        lines.append("    direction TB")
        for o in dim.options:
            oid = _opt_id(d, o.id)
            lines.append(f'    {oid}["{_label(o.id)}"]')
            if o.id in space.dead_options.get(d, []) or d in space.dead_dimensions:
                dead.append(oid)
            elif o.id in plan.out_of_scope.get(d, []):
                out.append(oid)
            elif o.noop:
                noop.append(oid)
        lines.append("  end")

    def endpoints(node, positive_values=True):
        """Option ids for the positive reading of each atom in `node`."""
        out_ids = []
        for atom, negated in node.atoms():
            positive = (atom.op in ("==", "in")) != negated
            values = atom.values if positive else [o for o in spec.dimensions[atom.dim].option_ids if o not in atom.values]
            out_ids.extend(_opt_id(atom.dim, v) for v in values)
        return out_ids

    for c in spec.constraints:
        simple = (
            c.kind != "never" and c.when is not None
            and getattr(c.when, "op", None) == "==" and getattr(c.then, "op", None) in ("==", "!=")
        )
        if simple:
            src = _opt_id(c.when.dim, c.when.values[0])
            dst = _opt_id(c.then.dim, c.then.values[0])
            requires = (c.kind == "requires") == (c.then.op == "==")
            if requires:
                lines.append(f'  {src} -->|"{c.id} requires"| {dst}')
            else:
                lines.append(f'  {src} --x|"{c.id} excludes"| {dst}')
            continue
        hid = f"c_{_mid(c.id)}"
        lines.append(f'  {hid}{{{{"{_label(c.id)}"}}}}')
        if c.kind == "never":
            for oid in endpoints(c.then):
                lines.append(f"  {hid} --- {oid}")
            continue
        if c.when is not None:
            for oid in endpoints(c.when):
                lines.append(f"  {oid} --- {hid}")
        for atom, negated in c.then.atoms():
            positive = (atom.op in ("==", "in")) != negated
            requires = (c.kind == "requires") == positive
            for v in atom.values:
                arrow = f'-->|"requires"|' if requires else f'--x|"excludes"|'
                lines.append(f"  {hid} {arrow} {_opt_id(atom.dim, v)}")

    for d, dim in spec.dimensions.items():
        if dim.applies_when is None:
            continue
        for oid in endpoints(dim.applies_when):
            lines.append(f'  {oid} -.->|"enables"| d_{_mid(d)}')

    if noop:
        lines.append("  classDef noop stroke-dasharray:4 3")
        lines.append(f"  class {','.join(noop)} noop")
    if out:
        lines.append("  classDef out stroke-dasharray:2 2,color:#888")
        lines.append(f"  class {','.join(out)} out")
    if dead:
        lines.append("  classDef dead fill:#fdecea,stroke:#c0392b,color:#8e1b10")
        lines.append(f"  class {','.join(dead)} dead")
    return "\n".join(lines)


STATUS_CLASS = {
    "branched": "fill:#fff8e1,stroke:#f9a825",
    "mr-open": "fill:#e3f2fd,stroke:#1565c0",
    "merged": "fill:#e8f5e9,stroke:#2e7d32",
}


def stack_diagram(plan, stack, state):
    by_id = plan.by_id
    base = _mid(stack.base_branch)
    lines = ["flowchart TD", f'  {base}(["{_label(stack.base_branch)}"])']
    classes = {}
    for nid in stack.order:
        node = by_id[nid]
        sid = "s_" + _mid(nid)
        lines.append(f'  {sid}["{_label(node.title)}<br/><small>{_label(nid)}</small>"]')
        status = state.get(nid, {}).get("status", "planned")
        if status in STATUS_CLASS:
            classes.setdefault(status, []).append(sid)
    for nid in stack.order:
        p = stack.placements[nid]
        sid = "s_" + _mid(nid)
        if p.parent is None and p.wave > 0:
            waits = ", ".join(p.waits_for)
            lines.append(f'  {base} -.->|"wave {p.wave + 1}, after {_label(waits)}"| {sid}')
        elif p.parent is None:
            lines.append(f"  {base} --> {sid}")
        else:
            lines.append(f"  s_{_mid(p.parent)} --> {sid}")
    for status, ids in classes.items():
        name = _mid(status)
        lines.append(f"  classDef {name} {STATUS_CLASS[status]}")
        lines.append(f"  class {','.join(ids)} {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------- MR text

def mr_description(spec, node, stack, plan, doc_path=None):
    p = stack.placements[node.id]
    by_id = plan.by_id
    parent = by_id[p.parent].title if p.parent else None
    children = stack.children(node.id)
    lines = ["## Summary", f"- {node.purpose}"]
    if node.kind != "base":
        lines.append(f"- Decisions: {', '.join(f'`{d}`' for d in node.decisions)}")
    where = f" ({doc_path})" if doc_path else ""
    lines.append(f"- Part of the {spec.title} decision space{where}, node `{node.id}`.")
    lines += ["", "## Stack"]
    if p.parent:
        lines.append(f"- Based on `{p.parent_branch}` ({parent}). Merge that first.")
    elif p.waits_for:
        lines.append(f"- Based on `{stack.base_branch}` after {', '.join(f'`{w}`' for w in p.waits_for)} merged.")
    else:
        lines.append(f"- Based on `{stack.base_branch}`.")
    if children:
        lines.append(f"- Unblocks {', '.join(f'`{stack.placements[c].branch}`' for c in children)}.")
    lines += ["", "## Verification", "- Not run yet."]
    if node.scenarios:
        lines.append(f"- Scenarios to cover: {_scenario_list(node.scenarios)}.")
    lines += ["", "## Risks", f"- {node.risk.capitalize()}: {RISK_TEXT[node.kind]}"]
    return "\n".join(lines)


def _scenario_list(ids, limit=8):
    if len(ids) <= limit:
        return ", ".join(ids)
    return ", ".join(ids[:limit]) + f" and {len(ids) - limit} more"


# ---------------------------------------------------------------- receipt

def _counts_line(spec):
    return " × ".join(str(len(d.options)) for d in spec.dimensions.values())


def receipt(result):
    spec = result.spec
    out = [f"Combinatorial Agentic Development: {spec.feature}", ""]
    space = result.space
    if space is None:
        out.append("Nothing was generated.")
        for f in result.errors:
            out.append(f"  error    {f.text}")
        return "\n".join(out)
    w = 34
    out.append("Decision space")
    out.append(f"  {'Theoretical combinations':<{w}}{space.theoretical:>6}   ({_counts_line(spec)})")
    if space.collapsed:
        out.append(f"  {'Collapsed (decision does not apply)':<{w}}{space.collapsed:>6}")
    out.append(f"  {'Removed by constraints':<{w}}{space.invalid:>6}")
    out.append(f"  {'Valid variants':<{w}}{len(space.valid):>6}")
    out.append("")
    sc = result.scenarios
    if sc is not None:
        mode = spec.mode if spec.mode != "twise" else f"twise (t = {spec.strength})"
        out.append(f"Generation mode    {mode}: {MODE_TEXT[spec.mode].format(t=spec.strength)}")
        out.append(f"Test scenarios     {len(sc.variants)}")
    plan = result.plan
    if plan is not None:
        kinds = [n.kind for n in plan.nodes]
        out.append(
            f"Implementation     {_n(len(plan.nodes), 'node')}: {kinds.count('base')} foundation, "
            f"{_n(kinds.count('dimension'), 'abstraction')}, {_n(kinds.count('option'), 'option')}, "
            f"{_n(kinds.count('interaction'), 'interaction')}"
            + (f", {_n(kinds.count('followup'), 'follow-up')}" if kinds.count('followup') else "")
        )
        out.append(f"Configurable       {plan.configurable} of {len(space.valid)} valid variants")
        st = result.stack
        out.append(f"Stack              {st.layout}, {_n(st.lanes, 'lane')}, {_n(st.waves, 'wave')}")
    out.append("")
    status = {"ok": "ok", "error": "error", "needs-confirmation": "needs confirmation"}[result.status]
    out.append(f"Status  {status}")
    for c in result.confirmations:
        out.append(f"  - {c}")
    if result.suggestions:
        out.append(f"  Options: {', '.join(result.suggestions)}.")
    out.append("")
    if plan is not None:
        foundation = [n for n in plan.nodes if n.kind in ("base", "dimension")]
        variant = [n for n in plan.nodes if n.kind in ("option", "interaction", "followup")]
        width = max(len(n.id) for n in plan.nodes) + 2
        out.append("Shared foundation")
        for n in foundation:
            out.append(f"  {n.id:<{width}}{n.title}")
        if variant:
            out.append("Variant nodes")
            for n in variant:
                out.append(f"  {n.id:<{width}}{n.title}")
        out.append("Stack (branch on parent)")
        for nid in result.stack.order:
            p = result.stack.placements[nid]
            onto = p.parent or result.stack.base_branch
            extra = f"  (wave {p.wave + 1})" if p.wave else ""
            out.append(f"  {nid:<{width}}on {onto}{extra}")
        out.append("")
    if result.findings:
        out.append("Findings")
        for f in result.findings:
            out.append(f"  {f.level:<8} {_plain(f.text)}")
        out.append("")
    out.append("Product decisions made on your behalf: 0")
    return "\n".join(out)


def _plain(text):
    return text.replace("`", "")


# ---------------------------------------------------------------- markdown

def _fence(kind, body):
    return f"```{kind}\n{body}\n```"


def _variant_cell(value):
    return "n/a" if value is None else f"`{value}`"


def _node_block(spec, result, node, number, state, doc_path):
    plan, stack = result.plan, result.stack
    p = stack.placements[node.id]
    st = state.get(node.id, {})
    lines = [f"### {number}. {node.title}", "", node.purpose, ""]
    deps = ", ".join(f"`{d}`" for d in node.depends_on) or "nothing (starts the stack)"
    target = effective_onto(stack, state, node.id)
    onto = f"`{target}`" + (f" in wave {p.wave + 1}" if p.wave else "")
    if target != p.parent_branch:
        onto += f" (parent `{p.parent_branch}` is merged)"
    rows = [
        ("Node", f"`{node.id}` ({node.kind})"),
        ("Decisions", ", ".join(f"`{d}`" for d in node.decisions)),
        ("Scope", node.scope),
        ("Depends on", deps),
    ]
    why = list(node.notes_derived)
    if p.grafted_for:
        why.append(f"stacked on `{p.parent}` so that `{p.grafted_for}` can build on both")
    if p.waits_for:
        why.append(f"starts after {', '.join(f'`{w}`' for w in p.waits_for)} merged, because they sit on separate lanes")
    if why:
        rows.append(("Why", "; ".join(why)))
    rows += [
        ("Components", ", ".join(node.components) if node.components else PLACEHOLDER),
        ("Expected files", ", ".join(f"`{f}`" for f in node.files) if node.files else PLACEHOLDER),
        ("Risk / complexity", f"{node.risk} / {node.complexity}"),
        ("Branch", f"`{p.branch}` onto {onto}"),
        ("Status", st.get("status", "planned") + (f" ({st['mr']})" if st.get("mr") else "")),
    ]
    lines += ["| | |", "|---|---|"]
    for key, value in rows:
        lines.append(f"| {key} | {str(value).replace('|', '/')} |")
    lines += ["", f"**Guidance.** {node.guidance or GUIDANCE[node.kind]}", ""]
    if node.notes:
        lines += [f"**Notes.** {node.notes}", ""]
    if node.changes:
        lines += ["**Contract changes**"] + [f"- `{c}`" for c in node.changes] + [""]
    if st.get("needs_update"):
        lines += ["**Needs update (branch already started)**"] + [f"- `{c}`" for c in st["needs_update"]] + [""]
    lines.append("**Tests**")
    for t in node.tests:
        lines.append(f"- {t}")
    if node.scenarios:
        lines.append(f"- Scenarios: {_scenario_list(node.scenarios)}")
    lines += ["", "**Acceptance criteria**"]
    for a in node.acceptance:
        lines.append(f"- [ ] {a}")
    lines += [
        "",
        "<details><summary>MR description</summary>",
        "",
        _fence("markdown", mr_description(spec, node, stack, plan, doc_path)),
        "",
        "</details>",
        "",
    ]
    return lines


def generated_markdown(result, state=None, doc_path=None, doc_status="draft"):
    spec, space, sc, plan, stack = result.spec, result.space, result.scenarios, result.plan, result.stack
    state = state or {}
    dims = space.dims
    L = []

    L += ["## Decision space", ""]
    L += ["| | Count |", "|---|---:|"]
    L.append(f"| Theoretical combinations ({_counts_line(spec)}) | {space.theoretical} |")
    if space.collapsed:
        L.append(f"| Collapsed, a decision does not apply | {space.collapsed} |")
    L.append(f"| Removed by constraints | {space.invalid} |")
    L.append(f"| **Valid product variants** | **{len(space.valid)}** |")
    L.append(f"| Test scenarios ({spec.mode if spec.mode != 'twise' else f'{spec.strength}-wise'}) | {len(sc.variants)} |")
    L.append(f"| Implementation nodes (MRs) | {len(plan.nodes)} |")
    L.append("")

    status_text = {
        "draft": "Draft. Waiting for sign-off.",
        "approved": "Approved. Ready to implement.",
        "implementing": "Approved and in progress.",
        "done": "Done.",
    }.get(doc_status, doc_status)
    L.append(f"**Plan status:** {status_text}")
    L.append("")
    if result.confirmations:
        L.append("**Needs confirmation:**")
        for c in result.confirmations:
            L.append(f"- {c}")
        L.append("")
        L.append(f"Options: {', '.join(result.suggestions)}.")
        L.append("")

    diagram = decision_diagram(spec, space)
    L += ["### Decision tree", ""]
    if diagram:
        L += [_fence("mermaid", diagram), ""]
        L.append(
            f"Every path from left to right is one valid variant. Branches with identical "
            f"continuations are merged, so all {len(space.valid)} variants fit in one small diagram."
        )
    else:
        L.append("_Omitted: the reduced decision tree has more than 60 nodes. The tables below are complete._")
    L.append("")

    L += ["### Dimensions", "", "| Dimension | Options | Applies when |", "|---|---|---|"]
    for d, dim in spec.dimensions.items():
        cells = []
        for o in dim.options:
            text = f"`{o.id}`"
            if o.id in space.dead_options.get(d, []) or d in space.dead_dimensions:
                text = f"~~{text}~~ (dead)"
            elif o.noop:
                text += " (no-op)"
            elif o.id in plan.out_of_scope.get(d, []):
                text += " (not targeted)"
            cells.append(text)
        when = f"`{dim.applies_when}`" if dim.applies_when is not None else "always"
        L.append(f"| {dim.label} (`{d}`) | {', '.join(cells)} | {when} |")
    L.append("")

    if spec.constraints:
        L += ["### Constraints", "", "| ID | Rule | Removes | Only this rule | Note |", "|---|---|---:|---:|---|"]
        for r in space.reports:
            c = r.constraint
            note = r.finding or c.reason
            if r.finding and c.reason:
                note = f"{r.finding}. {c.reason}"
            L.append(f"| {c.id} | `{c.text}` | {r.removes_alone} | {r.removes_only} | {note} |")
        L.append("")
    cmap = constraint_map(spec, space, plan)
    if cmap:
        L += ["<details><summary>Constraint map</summary>", "", _fence("mermaid", cmap), "", "</details>", ""]

    L += ["### Findings", ""]
    if result.findings:
        for f in result.findings:
            L.append(f"- **{f.level}**: {f.text}")
    else:
        L.append("- No dead options, contradictions or redundant constraints found.")
    L.append("")

    kinds = [n.kind for n in plan.nodes]
    L += ["## Implementation plan", ""]
    L.append(
        f"{_n(len(plan.nodes), 'node')}: {kinds.count('base')} foundation, {_n(kinds.count('dimension'), 'abstraction')}, "
        f"{_n(kinds.count('option'), 'option')}, {_n(kinds.count('interaction'), 'interaction')}"
        + (f", {_n(kinds.count('followup'), 'follow-up')}" if kinds.count('followup') else "") + ". "
        f"Work is planned per option, so {plan.configurable} of {len(space.valid)} valid variants are "
        f"configurable from {kinds.count('option') + kinds.count('dimension')} option and abstraction MRs."
    )
    L.append("")
    L += ["### MR stack", "", _fence("mermaid", stack_diagram(plan, stack, state)), ""]
    L += ["| # | Node | Branch | Onto | Status |", "|---:|---|---|---|---|"]
    for n, nid in enumerate(stack.order, 1):
        p = stack.placements[nid]
        st = state.get(nid, {})
        status = st.get("status", "planned") + (f" {st['mr']}" if st.get("mr") else "")
        if st.get("restack_from"):
            status += f", restack from `{st['restack_from']}`"
        onto = f"`{effective_onto(stack, state, nid)}`" + (f" (wave {p.wave + 1})" if p.wave else "")
        L.append(f"| {n} | `{nid}` | `{p.branch}` | {onto} | {status} |")
    L.append("")
    L.append(
        f"Layout: {stack.layout}. Merge order is the table order. After a parent merges, "
        f"retarget its children to `{stack.base_branch}` (see `cad.py stack`)."
    )
    L.append("")

    L += ["### Nodes", ""]
    for n, nid in enumerate(stack.order, 1):
        L += _node_block(spec, result, plan.by_id[nid], n, state, doc_path)

    L += ["## Test matrix", ""]
    mode = spec.mode
    L.append(f"Mode: **{mode if mode != 'twise' else f'{spec.strength}-wise'}**, {MODE_TEXT[mode].format(t=spec.strength)}.")
    L.append("")
    untested = plan.configurable - len(sc.variants)
    L.append("> " + HONESTY[mode].format(
        t=spec.strength, untested=untested, valid=len(space.valid), configurable=plan.configurable,
    ))
    L.append("")
    if mode in ("pairwise", "twise"):
        L.append(
            f"Coverage: {sc.covered} of {sc.coverable} reachable {sc.strength}-tuples. "
            f"{sc.excluded} further tuples are impossible under the constraints."
        )
        L.append("")
    header = "| ID | " + " | ".join(f"`{d}`" for d in dims) + " |"
    table = [header, "|---|" + "---|" * len(dims)]
    for n, v in enumerate(sc.variants, 1):
        table.append(f"| T{n:02d} | " + " | ".join(_variant_cell(x) for x in v) + " |")
    if len(sc.variants) > 24:
        L += [f"<details><summary>{len(sc.variants)} scenarios</summary>", ""] + table + ["", "</details>"]
    else:
        L += table
    L.append("")
    return "\n".join(L)
