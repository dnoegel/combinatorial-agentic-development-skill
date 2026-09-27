"""Runs the whole pipeline and decides the status of a plan."""

from dataclasses import dataclass, field

from . import coverage, plan as plan_mod, space as space_mod, stack as stack_mod

__all__ = ["Finding", "Result", "run"]


@dataclass
class Finding:
    level: str  # error | warning | info
    text: str


@dataclass
class Result:
    spec: object
    space: object = None
    scenarios: object = None
    plan: object = None
    stack: object = None
    findings: list = field(default_factory=list)
    confirmations: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]

    @property
    def status(self):
        if self.errors:
            return "error"
        if self.confirmations:
            return "needs-confirmation"
        return "ok"


def run(spec, state=None, followups=None):
    """Analyze a spec.

    `state` holds progress per node (from git) so placement never moves
    started work; `followups` are revisions planned for merged nodes.
    """
    result = Result(spec=spec)
    for w in spec.warnings:
        result.findings.append(Finding("warning", w))

    try:
        space = space_mod.analyze(spec)
    except space_mod.TooLarge as exc:
        result.findings.append(Finding("error", str(exc)))
        return result
    result.space = space

    if space.contradictory:
        hint = (
            f" Dropping {' or '.join(space.rescuers)} would make variants valid again."
            if space.rescuers else " No single constraint is to blame; several conflict together."
        )
        result.findings.append(Finding("error", "The constraints contradict each other: no valid variant is left." + hint))
        return result

    for dim_id in space.dead_dimensions:
        result.findings.append(Finding("warning", f"Dimension `{dim_id}` never applies to a valid variant."))
    for dim_id, options in space.dead_options.items():
        names = ", ".join(f"`{o}`" for o in options)
        result.findings.append(Finding(
            "warning",
            f"Dead option{'s' if len(options) > 1 else ''} in `{dim_id}`: {names} "
            f"{'appear' if len(options) > 1 else 'appears'} in no valid variant.",
        ))
    for dim_id, option in space.forced.items():
        result.findings.append(Finding("info", f"`{dim_id}` is always `{option}` in valid variants, so constraints already decided it."))
    for report in space.reports:
        c = report.constraint
        if report.finding == "never fires":
            result.findings.append(Finding("warning", f"{c.id} never fires: `{c.text}` removes nothing."))
        elif report.finding == "redundant":
            result.findings.append(Finding("info", f"{c.id} is redundant: everything it removes is already removed by other constraints."))
    for ix_id in space.unreachable_interactions:
        result.findings.append(Finding("warning", f"Interaction `{ix_id}` matches no valid variant."))

    scenarios = coverage.build(spec, space)
    result.scenarios = scenarios
    for e in scenarios.errors:
        result.findings.append(Finding("error", e))
    if scenarios.errors:
        return result

    plan = plan_mod.build(spec, space, scenarios, followups=followups, state=state)
    result.plan = plan
    for src, tgt, cid in plan.skipped_edges:
        result.findings.append(Finding("warning", f"Skipped dependency `{src}` on `{tgt}` from {cid}: it would create a cycle."))
    for node_id in plan.unknown_enrichment:
        result.findings.append(Finding("warning", f"`plan.{node_id}` does not match any node and is ignored."))
    if plan.out_of_scope:
        names = "; ".join(f"{d}: {', '.join(v)}" for d, v in plan.out_of_scope.items())
        result.findings.append(Finding("info", f"Valid but not targeted by the selected variants, so not implemented: {names}."))

    stack = stack_mod.place(
        plan, spec.stack["layout"], spec.stack["base_branch"], spec.stack["branch_prefix"], state=state,
        max_coupling=spec.stack["max_coupling"],
    )
    result.stack = stack
    for p in stack.placements.values():
        if p.waits_for:
            result.findings.append(Finding(
                "info",
                f"`{p.node}` starts from {stack.base_branch} in wave {p.wave + 1} after "
                f"{', '.join(f'`{w}`' for w in p.waits_for)} merged (dependencies sit on separate lanes).",
            ))

    for d, dim in spec.dimensions.items():
        if dim.strategy[0] == "branch" and not dim.decided:
            result.findings.append(Finding(
                "info",
                f"`{d}` is delivered as open branches ({dim.strategy[1]}). When product decides, set "
                f"`decided: <option>` on the dimension: the winner merges and the other branches close.",
            ))
    if not spec.verify.get("probe"):
        result.findings.append(Finding(
            "warning",
            "No `verify.probe` configured: nothing proves that each option actually changes the product. "
            "Green tests per branch are not enough (see references/verification.md).",
        ))
    for a, b, shared in _parallel_file_overlaps(plan, stack):
        result.findings.append(Finding(
            "warning",
            f"`{a}` and `{b}` sit on parallel lanes and both list {', '.join(f'`{f}`' for f in shared)}. "
            "Their merges will conflict: move the file to a common ancestor node or discover modules at runtime.",
        ))

    limit = spec.limits["max_variants"]
    targeted = len(scenarios.variants)
    if targeted > limit:
        result.confirmations.append(f"{targeted} targeted variants exceed max_variants ({limit}).")
        result.suggestions = ["proceed as planned"]
        if spec.mode == "exhaustive":
            result.suggestions.append("switch the test matrix to pairwise")
        result.suggestions += [
            "add a constraint that rules out combinations nobody wants",
            "raise limits.max_variants on purpose",
        ]
    return result


def _parallel_file_overlaps(plan, stack):
    """Pairs of nodes on different lanes that plan to edit the same files."""
    def chain(nid):
        out = set()
        cur = nid
        while cur is not None:
            out.add(cur)
            cur = stack.placements[cur].parent
        return out

    chains = {nid: chain(nid) for nid in stack.order}
    files = {n.id: set(n.files) for n in plan.nodes if n.files}
    ids = [nid for nid in stack.order if nid in files]
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if a in chains[b] or b in chains[a]:
                continue
            shared = sorted(files[a] & files[b])
            if shared:
                out.append((a, b, shared))
    return out
