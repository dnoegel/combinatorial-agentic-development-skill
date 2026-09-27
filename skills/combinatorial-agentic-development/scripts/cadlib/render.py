"""Rendering: terminal receipt, Markdown sections, Mermaid diagrams, MR text."""

import re


__all__ = ["receipt", "generated_markdown", "decision_diagram", "stack_diagram", "mr_description"]

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
        "Pairwise coverage tests every pair of decisions. "
        "{untested} of {valid} valid variants are configurable but have no dedicated scenario."
    ),
    "twise": (
        "{t}-wise coverage tests every combination of {t} decisions. "
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
    "cleanup": (
        "Remove the losing options completely: code, registration, configuration values and tests. "
        "Keep the change reviewable by leaving the winner untouched."
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
    "cleanup": "Deletes code that some configurations used; check that nothing still selects it.",
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


def stack_diagram(plan, stack):
    by_id = plan.by_id
    base = _mid(stack.base_branch)
    lines = ["flowchart TD", f'  {base}(["{_label(stack.base_branch)}"])']
    for nid in stack.order:
        lines.append(f'  s_{_mid(nid)}["{_label(by_id[nid].title)}<br/><small>{_label(nid)}</small>"]')
    for nid in stack.order:
        p = stack.placements[nid]
        sid = "s_" + _mid(nid)
        if p.parent is None and p.wave > 0:
            lines.append(f'  {base} -.->|"wave {p.wave + 1}, after {_label(", ".join(p.waits_for))}"| {sid}')
        elif p.parent is None:
            lines.append(f"  {base} --> {sid}")
        else:
            lines.append(f"  s_{_mid(p.parent)} --> {sid}")
    held = [f"s_{_mid(n)}" for n in stack.order if by_id[n].hold]
    if held:
        lines.append("  classDef open stroke-dasharray:5 4")
        lines.append(f"  class {','.join(held)} open")
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
    if node.hold:
        lines.append(f"- Stays open: {node.hold_reason}. Merge only if this option wins.")
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
    lines += ["", "## Risks", f"- {node.risk.capitalize() + ': ' if node.risk else ''}{RISK_TEXT[node.kind]}"]
    return "\n".join(lines)


def _delivery_cell(dim):
    strategy, reason = dim.strategy
    if dim.decided:
        return f"decided: `{dim.decided}` ({strategy})"
    return f"{strategy}: {reason}"


def delivery_summary(spec):
    groups = {}
    for d, dim in spec.dimensions.items():
        label = f"{d} = {dim.decided}" if dim.decided else d
        key = "decided" if dim.decided else dim.strategy[0]
        groups.setdefault(key, []).append(label)
    names = {"toggle": "toggle", "branch": "branch (stays open until decided)", "decided": "decided"}
    return "; ".join(f"{names[k]}: {', '.join(v)}" for k, v in groups.items())


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
        out.append(f"Delivery           {delivery_summary(spec)}")
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
            if plan.by_id[nid].hold:
                extra += "  (stays open)"
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


def _node_block(result, node, number):
    stack, plan = result.stack, result.plan
    p = stack.placements[node.id]
    onto = f"`{p.parent_branch}`" + (f" (wave {p.wave + 1})" if p.wave else "")
    why = list(node.notes_derived)
    if p.grafted_for:
        why.append(f"stacked on `{p.parent}` so that `{p.grafted_for}` can build on both")
    if p.waits_for:
        why.append(f"starts after {', '.join(f'`{w}`' for w in p.waits_for)} merged, because they sit on separate lanes")
    rows = [
        ("Decisions", ", ".join(f"`{d}`" for d in node.decisions)),
        ("Scope", node.scope),
        ("Depends on", ", ".join(f"`{d}`" for d in node.depends_on) or "nothing (starts the stack)"),
    ]
    if why:
        rows.append(("Why", "; ".join(why)))
    rows += [
        ("Components and files", ", ".join(node.components + [f"`{f}`" for f in node.files]) or PLACEHOLDER),
        ("Branch", f"`{p.branch}` onto {onto}"),
    ]
    if node.hold:
        rows.append(("Merge", f"stays open: {node.hold_reason}"))
    if node.risk or node.complexity:
        rows.insert(-1, ("Risk / complexity", " / ".join(x for x in (node.risk, node.complexity) if x)))
    lines = [
        f"<details><summary><b>{number}. {node.title}</b> <code>{node.id}</code></summary>",
        "",
        node.purpose,
        "",
        "| | |",
        "|---|---|",
    ]
    lines += [f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows]
    lines.append("")
    if node.guidance:
        lines += [f"**Guidance.** {node.guidance}", ""]
    if node.notes:
        lines += [f"**Notes.** {node.notes}", ""]
    if node.changes:
        lines += ["**Contract changes**"] + [f"- `{c}`" for c in node.changes] + [""]
    lines += ["**Tests**"] + [f"- {t}" for t in node.tests]
    if node.scenarios:
        lines.append(f"- Scenarios: {_scenario_list(node.scenarios)}")
    lines += ["", "**Acceptance criteria**"] + [f"- [ ] {a}" for a in node.acceptance]
    lines += ["", "</details>", ""]
    return lines


def generated_markdown(result):
    spec, space, sc, plan, stack = result.spec, result.space, result.scenarios, result.plan, result.stack
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

    L += ["### Dimensions", "", "| Dimension | Options | Applies when | Delivery |", "|---|---|---|---|"]
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
        L.append(f"| {dim.label} (`{d}`) | {', '.join(cells)} | {when} | {_delivery_cell(dim)} |")
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
    L += ["### MR stack", "", _fence("mermaid", stack_diagram(plan, stack)), ""]
    L += ["| # | Node | Branch | Onto |", "|---:|---|---|---|"]
    for n, nid in enumerate(stack.order, 1):
        p = stack.placements[nid]
        onto = f"`{p.parent_branch}`" + (f" (wave {p.wave + 1})" if p.wave else "")
        if plan.by_id[nid].hold:
            onto += ", stays open"
        L.append(f"| {n} | `{nid}` | `{p.branch}` | {onto} |")
    L.append("")
    L.append(
        f"Layout: {stack.layout}. Merge order is the table order. Progress lives in git; "
        f"`cad.py stack` shows what exists and what comes next."
    )
    L.append("")

    L += ["### Nodes", "", "Default guidance, unless a node says otherwise:", ""]
    for kind, label in (("base", "Foundation"), ("dimension", "Abstractions"), ("option", "Options"),
                        ("interaction", "Interactions"), ("followup", "Follow-ups"), ("cleanup", "Cleanups")):
        if kind in kinds:
            L.append(f"- **{label}:** {GUIDANCE[kind]}")
    L.append("")
    for n, nid in enumerate(stack.order, 1):
        L += _node_block(result, plan.by_id[nid], n)

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
