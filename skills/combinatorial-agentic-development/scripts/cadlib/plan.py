"""Implementation plan: nodes are derived from options.

Node kinds and ids:

    base              shared foundation every variant builds on
    dim.<d>           variation point (interface, config key, no-op default)
    opt.<d>.<o>       one implementation per non-noop option in scope
    ix.<id>           declared interaction between options

Work therefore grows with the number of options while variants grow with
their product. Variants drive the test matrix.
"""

import re
from dataclasses import dataclass, field

from .spec import lower_label
from .space import variant_env

__all__ = ["Node", "Plan", "build", "contract", "dependents"]


@dataclass
class Node:
    id: str
    kind: str
    title: str
    purpose: str
    decisions: list
    scope: str
    depends_on: list
    options: list = field(default_factory=list)  # (dim, option) pairs implemented here
    components: list = field(default_factory=list)
    files: list = field(default_factory=list)
    guidance: str = ""
    tests: list = field(default_factory=list)
    scenarios: list = field(default_factory=list)
    acceptance: list = field(default_factory=list)
    risk: str = ""  # set only through plan enrichment
    complexity: str = ""
    notes: str = ""
    enriched: set = field(default_factory=set)
    notes_derived: list = field(default_factory=list)  # why dependencies exist
    contract_extra: list = field(default_factory=list)  # extra lines that define what the node must do
    followup_of: object = None
    changes: list = field(default_factory=list)  # for follow-ups: what changed in the original contract


@dataclass
class Plan:
    nodes: list
    order: list  # node ids in deterministic topological order
    out_of_scope: dict  # dim -> options valid but not targeted
    configurable: int  # valid variants buildable from implemented options
    skipped_edges: list = field(default_factory=list)
    unknown_enrichment: list = field(default_factory=list)

    @property
    def by_id(self):
        return {n.id: n for n in self.nodes}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [line.strip("- ").strip() for line in str(value).splitlines() if line.strip()]


def _lower_first(label):
    """`My company (Shopware)` becomes `my company (Shopware)`; acronyms such as `PDF` stay."""
    if label[:1].isupper() and label[1:2].islower():
        return label[:1].lower() + label[1:]
    return label


def _strip_verb(title):
    for verb in ("Add ", "Implement ", "Create "):
        if title.startswith(verb):
            return title[len(verb):]
    return title[:1].lower() + title[1:]


def contract(node):
    """What a node promises, independent of scenario counts. Used to spot changes after work started."""
    lines = [f"decision: {d}" for d in node.decisions]
    lines += [f"depends on: {d}" for d in sorted(node.depends_on) if d != node.followup_of]
    lines.append(f"scope: {node.scope}")
    lines += [f"accept: {re.sub(r'[0-9]+', '#', a)}" for a in node.acceptance]
    lines += node.contract_extra
    return lines


def dependents(plan, node_id):
    """Every node that depends on `node_id`, directly or transitively, in plan order."""
    hit = {node_id}
    changed = True
    while changed:
        changed = False
        for n in plan.nodes:
            if n.id not in hit and any(d in hit for d in n.depends_on):
                hit.add(n.id)
                changed = True
    return [n.id for n in plan.nodes if n.id in hit and n.id != node_id]


def build(spec, space, scenarios, followups=None, state=None):
    dims = space.dims
    targeted = scenarios.variants

    used = {d: set() for d in dims}
    for v in targeted:
        for d, value in zip(dims, v):
            if value is not None:
                used[d].add(value)
    valid_used = {d: set() for d in dims}
    for v in space.valid:
        for d, value in zip(dims, v):
            if value is not None:
                valid_used[d].add(value)

    def scen_ids(pred):
        return [f"T{n + 1:02d}" for n, v in enumerate(targeted) if pred(variant_env(dims, v))]

    nodes = []
    base = Node(
        id="base",
        kind="base",
        title=f"Add {lower_label(spec.title)} foundation",
        purpose="Shared domain model, configuration entry point and wiring that every variant builds on.",
        decisions=["shared by all variants"],
        scope=(
            "Domain types, one configuration object with a key per dimension, validation of that "
            "configuration against the constraints, and the composition root that picks implementations."
        ),
        depends_on=[],
        tests=[
            "Unit tests for the domain model.",
            "Configuration tests: every combination removed by a constraint is rejected with a readable message.",
        ],
        scenarios=scen_ids(lambda env: True),
        acceptance=[
            f"Configuration accepts the {len(space.valid)} valid variants and rejects the {space.invalid} invalid combinations.",
            "Existing behavior is unchanged while no variation point is wired in.",
            "The composition root discovers option modules at runtime, so option branches never edit shared files.",
            "Every active option leaves a marker in the output (for example `data-cad=\"style=serious\"`), "
            "and the `verify.probe` command prints the markers it observes as `dimension=option`.",
        ],
        contract_extra=[f"rule: {c.text}" for c in spec.constraints]
        + [f"options: {d}: {', '.join(sorted(used[d]))}" for d in dims],
    )
    nodes.append(base)

    dim_nodes = {}
    option_nodes = {}
    for d, dim in spec.dimensions.items():
        in_scope = [o for o in dim.options if o.id in used[d]]
        work = [o for o in in_scope if not o.noop]
        if not work:
            continue
        noops = [o for o in in_scope if o.noop]
        label = lower_label(dim.label)
        node = Node(
            id=f"dim.{d}",
            kind="dimension",
            title=f"Add {label} abstraction" if not dim.bundle else f"Add {label} ({', '.join(o.id for o in work)})",
            purpose=(
                f"Variation point for {label}: one interface and one configuration key "
                f"`{d}`, so every option plugs in without touching callers."
            ),
            decisions=[f"{d} in [{', '.join(o.id for o in in_scope)}]"],
            scope=(
                f"Interface for {label}, registration by option id"
                + (f", and the no-op implementation for {', '.join(f'`{o.id}`' for o in noops)}" if noops else "")
                + (f". Implements {', '.join(f'`{o.id}`' for o in work)} in this node (bundled)." if dim.bundle else ".")
            ),
            depends_on=["base"],
            options=[(d, o.id) for o in (in_scope if dim.bundle else noops)],
            tests=[
                "Contract test suite that every implementation of the interface must pass.",
            ] + ([
                f"The no-op option{'s' if len(noops) > 1 else ''} {', '.join(f'`{o.id}`' for o in noops)} "
                f"{'pass' if len(noops) > 1 else 'passes'} the contract suite."
            ] if noops else [])
              + ([f"Unit tests for {', '.join(o.id for o in work)}."] if dim.bundle else []),
            scenarios=scen_ids(lambda env, d=d: env[d] is not None),
            acceptance=[
                f"Selecting any of {', '.join(o.id for o in in_scope)} through configuration works without code changes in callers.",
                f"The selected `{d}` option is observable in the output, no-op options included (for example `{d}={in_scope[-1].id}`).",
            ] + ([f"All scenarios with {d} set pass."] if dim.bundle else []),
        )
        nodes.append(node)
        dim_nodes[d] = node
        if dim.bundle:
            for o in work:
                option_nodes[(d, o.id)] = node

    for d, dim in spec.dimensions.items():
        if d not in dim_nodes or dim.bundle:
            continue
        for o in dim.options:
            if o.noop or o.id not in used[d]:
                continue
            label = lower_label(dim.label)
            node = Node(
                id=f"opt.{d}.{o.id}",
                kind="option",
                title=f"{dim.label}: {_lower_first(o.label)}",
                purpose=o.summary or f"Implement `{d} = {o.id}` behind the {label} abstraction.",
                decisions=[f"{d} = {o.id}"],
                scope=f"One implementation of the {label} interface, registered as `{o.id}`. No changes to other options.",
                depends_on=[f"dim.{d}"],
                options=[(d, o.id)],
                tests=[
                    f"Unit tests for the `{o.id}` implementation.",
                    "Run the contract suite from the abstraction against it.",
                ],
                scenarios=scen_ids(lambda env, d=d, o=o.id: env[d] == o),
            )
            node.acceptance = [
                f"The {len(node.scenarios)} test scenarios with `{d} = {o.id}` pass, and the probe observes "
                f"`{d}={o.id}` in exactly those."
            ]
            nodes.append(node)
            option_nodes[(d, o.id)] = node

    for ix in spec.interactions:
        env_pred = ix.when.evaluate
        scen = scen_ids(env_pred)
        if not scen:
            continue
        node = Node(
            id=f"ix.{ix.id}",
            kind="interaction",
            title=ix.title,
            purpose=ix.summary or f"Glue code for variants where {ix.when}.",
            decisions=[str(ix.when)],
            scope="Only the code that is needed because these options meet. Each option stays usable on its own.",
            depends_on=[],
            tests=["Integration test that exercises the involved options together."],
            scenarios=scen,
            acceptance=[f"All {len(scen)} test scenarios where {ix.when} pass."],
        )
        nodes.append(node)

    by_id = {n.id: n for n in nodes}

    def target_for(dim_id, value):
        if (dim_id, value) in option_nodes:
            return option_nodes[(dim_id, value)].id
        if dim_id in dim_nodes:
            return dim_nodes[dim_id].id
        return None

    # Structural edges first: applies_when and interactions.
    for d, dim in spec.dimensions.items():
        if d in dim_nodes and dim.applies_when is not None:
            node = dim_nodes[d]
            for atom, negated in dim.applies_when.atoms():
                positive = not negated and atom.op in ("==", "in")
                targets = [target_for(atom.dim, v) for v in atom.values] if positive else [target_for(atom.dim, None)]
                for t in targets:
                    if t and t != node.id and t not in node.depends_on:
                        node.depends_on.append(t)
                        node.notes_derived.append(f"`{t}`: {d} only applies when {dim.applies_when}")
    for ix in spec.interactions:
        node = by_id.get(f"ix.{ix.id}")
        if node is None:
            continue
        for atom, negated in ix.when.atoms():
            positive = not negated and atom.op in ("==", "in")
            targets = [target_for(atom.dim, v) for v in atom.values] if positive else [target_for(atom.dim, None)]
            for t in targets:
                if t and t not in node.depends_on:
                    node.depends_on.append(t)
        if not node.depends_on:
            node.depends_on.append("base")

    def reaches(src, dst):
        stack, seen = [src], set()
        while stack:
            cur = stack.pop()
            if cur == dst:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(by_id[cur].depends_on)
        return False

    # Requirement edges: an option that requires another dimension builds on it.
    # Requiring one specific option (`x == v`) builds on that option's node,
    # anything looser (`!=`, `in`, negations) builds on the abstraction.
    skipped = []
    for c in spec.constraints:
        if c.kind != "requires" or c.when is None:
            continue
        triggers = [(a.dim, v) for a, neg in c.when.atoms() if not neg and a.op in ("==", "in") for v in a.values]
        needed = []
        for a, neg in c.then.atoms():
            if a.dim not in dim_nodes:
                continue
            exact = not neg and a.op == "==" and (a.dim, a.values[0]) in option_nodes
            tgt = option_nodes[(a.dim, a.values[0])].id if exact else dim_nodes[a.dim].id
            if tgt not in needed:
                needed.append(tgt)
        for dim_id, value in triggers:
            src = option_nodes.get((dim_id, value))
            if src is None:
                continue
            for tgt in needed:
                if tgt == src.id or tgt in src.depends_on:
                    continue
                if reaches(tgt, src.id):
                    skipped.append((src.id, tgt, c.id))
                    continue
                src.depends_on.append(tgt)
                src.notes_derived.append(f"`{tgt}`: constraint {c.id} ({c.text})")


    unknown = []
    for node_id, details in spec.plan.items():
        node = by_id.get(node_id)
        if node is None:
            unknown.append(node_id)
            continue
        for key, value in details.items():
            if key in ("components", "files", "tests", "acceptance"):
                setattr(node, key, _as_list(value))
            elif key in ("title", "purpose", "scope", "guidance", "risk", "complexity", "notes"):
                setattr(node, key, str(value).strip())
            else:
                continue
            node.enriched.add(key)

    # Follow-ups: merged nodes whose contract changed get a new node instead of a rewrite.
    state = state or {}
    for fu in followups or []:
        original = by_id.get(fu.get("of"))
        if original is None or fu["id"] in by_id:
            continue
        node = Node(
            id=fu["id"],
            kind="followup",
            title=f"Revise {_strip_verb(original.title)} for plan revision {fu.get('revision')}",
            purpose=f"`{original.id}` is already merged and its contract changed in plan revision {fu.get('revision')}. "
                    "This node brings it in line without rewriting merged history.",
            decisions=list(original.decisions),
            scope="Only the listed contract changes. No unrelated refactoring.",
            depends_on=[original.id],
            tests=list(original.tests),
            scenarios=list(original.scenarios),
            acceptance=[f"Contract change done: {c}" for c in fu.get("changes", [])]
            + [f"Everything `{original.id}` promised before still holds."],
            followup_of=original.id,
            changes=list(fu.get("changes", [])),
        )
        nodes.append(node)
        by_id[node.id] = node
        for other in nodes:
            status = (state.get(other.id) or {}).get("status", "planned")
            if other is node or other.followup_of or status != "planned" or original.id not in other.depends_on:
                continue
            other.depends_on.append(node.id)
            other.notes_derived.append(f"`{node.id}`: builds on the updated `{original.id}`")

    # Transitive reduction keeps the graph readable.
    for node in nodes:
        keep = []
        for dep in node.depends_on:
            others = [o for o in node.depends_on if o != dep]
            if not any(reaches(o, dep) for o in others):
                keep.append(dep)
        node.depends_on = keep

    order = _topo(nodes)

    out_scope = {d: [o for o in spec.dimensions[d].option_ids if o in valid_used[d] and o not in used[d]] for d in dims}
    out_scope = {d: v for d, v in out_scope.items() if v}
    configurable = sum(
        1 for v in space.valid if all(value is None or value in used[d] for d, value in zip(dims, v))
    )
    return Plan(
        nodes=[by_id[i] for i in order], order=order, out_of_scope=out_scope,
        configurable=configurable, skipped_edges=skipped, unknown_enrichment=unknown,
    )


def _topo(nodes):
    rank = {n.id: i for i, n in enumerate(nodes)}
    remaining = {n.id: set(n.depends_on) for n in nodes}
    order = []
    while remaining:
        ready = sorted((i for i, deps in remaining.items() if not deps), key=rank.get)
        if not ready:
            raise ValueError("dependency cycle between " + ", ".join(sorted(remaining)))
        pick = ready[0]
        order.append(pick)
        del remaining[pick]
        for deps in remaining.values():
            deps.discard(pick)
    return order
