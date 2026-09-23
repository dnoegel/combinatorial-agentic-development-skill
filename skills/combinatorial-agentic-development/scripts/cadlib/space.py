"""Decision space analysis: counting, constraint checks and findings.

The four headline numbers always add up:

    theoretical = collapsed + invalid + valid

theoretical  Cartesian product of every option list.
collapsed    duplicates that differ only in a dimension that does not apply
             (its applies_when is false), merged into one variant.
invalid      distinct combinations rejected by at least one constraint.
valid        everything else: the real product variants.
"""

import itertools
from dataclasses import dataclass, field
from math import prod

__all__ = ["TooLarge", "Space", "ConstraintReport", "theoretical_count", "analyze", "variant_env"]


class TooLarge(ValueError):
    def __init__(self, theoretical, limit):
        self.theoretical = theoretical
        self.limit = limit
        super().__init__(
            f"{theoretical:,} theoretical combinations exceed max_enumeration ({limit:,}). "
            "Nothing was generated. Split the feature, mark conditional decisions with "
            "applies_when, or raise limits.max_enumeration on purpose."
        )


@dataclass
class ConstraintReport:
    constraint: object
    removes_alone: int = 0  # combinations this constraint rejects
    removes_only: int = 0  # combinations rejected by this constraint and no other

    @property
    def finding(self):
        if self.removes_alone == 0:
            return "never fires"
        if self.removes_only == 0:
            return "redundant"
        return ""


@dataclass
class Space:
    dims: list
    theoretical: int
    collapsed: int
    invalid: int
    valid: list
    reports: list
    dead_options: dict = field(default_factory=dict)
    dead_dimensions: list = field(default_factory=list)
    forced: dict = field(default_factory=dict)
    unreachable_interactions: list = field(default_factory=list)
    rescuers: list = field(default_factory=list)

    @property
    def contradictory(self):
        return not self.valid


def theoretical_count(spec):
    return prod(len(d.options) for d in spec.dimensions.values())


def variant_env(dims, variant):
    return {d: v for d, v in zip(dims, variant)}


def normalize(spec, choice):
    """Apply applies_when in declaration order; inactive dimensions become None."""
    env = {}
    for dim in spec.dimensions.values():
        value = choice.get(dim.id)
        if dim.applies_when is not None and not dim.applies_when.evaluate(env):
            value = None
        env[dim.id] = value
    return env


def analyze(spec):
    """Enumerate the decision space and collect findings. Raises TooLarge."""
    dims = list(spec.dimensions)
    theoretical = theoretical_count(spec)
    if theoretical > spec.limits["max_enumeration"]:
        raise TooLarge(theoretical, spec.limits["max_enumeration"])

    reports = [ConstraintReport(c) for c in spec.constraints]
    seen = set()
    valid = []
    invalid = 0
    lists = [d.option_ids for d in spec.dimensions.values()]
    for combo in itertools.product(*lists):
        env = normalize(spec, dict(zip(dims, combo)))
        key = tuple(env[d] for d in dims)
        if key in seen:
            continue
        seen.add(key)
        broken = [i for i, c in enumerate(spec.constraints) if not c.holds(env)]
        for i in broken:
            reports[i].removes_alone += 1
        if len(broken) == 1:
            reports[broken[0]].removes_only += 1
        if broken:
            invalid += 1
        else:
            valid.append(key)

    space = Space(
        dims=dims,
        theoretical=theoretical,
        collapsed=theoretical - len(seen),
        invalid=invalid,
        valid=valid,
        reports=reports,
    )

    for idx, dim in enumerate(spec.dimensions.values()):
        used = {v[idx] for v in valid if v[idx] is not None}
        if valid and not used:
            space.dead_dimensions.append(dim.id)
            continue
        dead = [o for o in dim.option_ids if o not in used]
        if valid and dead:
            space.dead_options[dim.id] = dead
        if len(used) == 1 and len(dim.options) > 1:
            space.forced[dim.id] = next(iter(used))

    for ix in spec.interactions:
        if not any(ix.when.evaluate(variant_env(dims, v)) for v in valid):
            space.unreachable_interactions.append(ix.id)

    if not valid:
        space.rescuers = [r.constraint.id for r in reports if r.removes_only > 0]
    return space
