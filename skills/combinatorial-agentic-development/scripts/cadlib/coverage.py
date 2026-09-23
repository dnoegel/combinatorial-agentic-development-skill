"""Test scenario generation for the four generation modes.

exhaustive  every valid variant becomes a scenario.
pairwise    a small set of valid variants that together contain every pair of
            option values that can occur together (t = 2).
twise       the same for every combination of t option values.
selected    exactly the variants listed in the spec.

Pairwise and t-wise use a deterministic lazy greedy set cover over the
enumerated valid variants. Because only valid variants are candidates,
constraints are respected exactly. The result is small but not guaranteed
to be minimal. Covering every t-tuple is a statement about interactions of
t decisions; it says nothing about the untested full variants.
"""

import heapq
import itertools
from dataclasses import dataclass, field

from .space import normalize

__all__ = ["Scenarios", "build", "tuples_of", "greedy_cover"]


@dataclass
class Scenarios:
    mode: str
    strength: object
    variants: list
    possible: int = 0  # t-tuples over the declared options
    coverable: int = 0  # t-tuples that occur in at least one valid variant
    covered: int = 0  # t-tuples covered by the scenarios
    errors: list = field(default_factory=list)

    @property
    def excluded(self):
        return self.possible - self.coverable


def tuples_of(variant, t):
    active = [(i, v) for i, v in enumerate(variant) if v is not None]
    return list(itertools.combinations(active, t))


def possible_tuples(spec, t):
    sizes = [len(d.options) for d in spec.dimensions.values()]
    total = 0
    for combo in itertools.combinations(range(len(sizes)), t):
        count = 1
        for i in combo:
            count *= sizes[i]
        total += count
    return total


def greedy_cover(variants, t):
    """Pick variant indices covering every t-tuple present in `variants`.

    Deterministic: at each step the variant covering the most uncovered tuples
    wins, ties go to the earliest variant.
    """
    tuple_sets = [set(tuples_of(v, t)) for v in variants]
    uncovered = set().union(*tuple_sets) if tuple_sets else set()
    heap = [(-len(s), i) for i, s in enumerate(tuple_sets)]
    heapq.heapify(heap)
    chosen = []
    while uncovered and heap:
        stale_gain, idx = heapq.heappop(heap)
        gain = len(tuple_sets[idx] & uncovered)
        if gain == 0:
            continue
        if gain == -stale_gain:
            chosen.append(idx)
            uncovered -= tuple_sets[idx]
        else:
            heapq.heappush(heap, (-gain, idx))
    return sorted(chosen)


def _selected(spec, space):
    errors = []
    dims = list(spec.dimensions)
    valid = set(space.valid)
    variants = []
    for n, entry in enumerate(spec.selected):
        path = f"generation.variants[{n}]"
        if not isinstance(entry, dict):
            errors.append(f"{path}: expected a mapping of dimension to option")
            continue
        entry = {str(k): (None if v is None else str(v)) for k, v in entry.items()}
        unknown = [k for k in entry if k not in spec.dimensions]
        if unknown:
            errors.append(f"{path}: unknown dimension(s) {', '.join(unknown)}")
            continue
        bad = [f"{k}={v}" for k, v in entry.items() if v is not None and v not in spec.dimensions[k].option_ids]
        if bad:
            errors.append(f"{path}: unknown option(s) {', '.join(bad)}")
            continue
        env = normalize(spec, entry)
        missing = [d for d in dims if env[d] is None and d in _active_dims(spec, entry)]
        if missing:
            errors.append(f"{path}: missing a choice for {', '.join(missing)}")
            continue
        key = tuple(env[d] for d in dims)
        if key not in valid:
            broken = [c.id for c in spec.constraints if not c.holds(env)]
            errors.append(f"{path}: not a valid variant (violates {', '.join(broken)})")
            continue
        if key not in variants:
            variants.append(key)
    order = {v: i for i, v in enumerate(space.valid)}
    return sorted(variants, key=order.get), errors


def _active_dims(spec, entry):
    env = {}
    active = set()
    for dim in spec.dimensions.values():
        if dim.applies_when is None or dim.applies_when.evaluate(env):
            active.add(dim.id)
            env[dim.id] = entry.get(dim.id)
        else:
            env[dim.id] = None
    return active


def _coverage(spec, space, variants, t):
    coverable = set()
    for v in space.valid:
        coverable.update(tuples_of(v, t))
    covered = set()
    for v in variants:
        covered.update(tuples_of(v, t))
    return possible_tuples(spec, t), len(coverable), len(covered & coverable)


def build(spec, space):
    mode = spec.mode
    if mode == "exhaustive":
        variants = list(space.valid)
        result = Scenarios(mode, None, variants)
        result.possible, result.coverable, result.covered = _coverage(spec, space, variants, min(2, len(space.dims)))
        return result
    if mode == "selected":
        variants, errors = _selected(spec, space)
        result = Scenarios(mode, None, variants, errors=errors)
        result.possible, result.coverable, result.covered = _coverage(spec, space, variants, min(2, len(space.dims)))
        return result
    t = spec.strength
    chosen = greedy_cover(space.valid, t)
    variants = [space.valid[i] for i in chosen]
    result = Scenarios(mode, t, variants)
    result.possible, result.coverable, result.covered = _coverage(spec, space, variants, t)
    return result
