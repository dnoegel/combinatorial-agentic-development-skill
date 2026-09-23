"""Spec loading and validation.

A spec is the canonical description of a decision space. It is usually stored
in a fenced ```yaml cad-spec block inside a planning document, but plain YAML
or JSON files work too.
"""

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field

from . import expr as ex

__all__ = ["SpecError", "Spec", "Dimension", "Option", "Constraint", "Interaction", "load", "humanize", "spec_hash"]

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
NOOP_IDS = {"none", "disabled", "off"}
MODES = ("exhaustive", "pairwise", "twise", "selected")
LAYOUTS = ("tree", "linear")
PLATFORMS = ("auto", "gitlab", "github", "none")
DEFAULT_LIMITS = {
    "max_valid_variants": 32,
    "max_implementation_nodes": 20,
    "require_confirmation_above": 12,
    "max_enumeration": 100000,
}
PLAN_FIELDS = (
    "title", "purpose", "scope", "components", "files", "guidance",
    "tests", "acceptance", "risk", "complexity", "notes",
)
TOP_LEVEL = (
    "cad", "feature", "project", "title", "summary", "description", "dimensions",
    "constraints", "interactions", "generation", "limits", "stack", "plan", "verify",
)
ACRONYMS = {
    "api", "crm", "csv", "html", "http", "id", "json", "pdf", "sms", "sso",
    "ui", "url", "ux", "sdk", "cli", "ci", "mr", "pr", "ab", "otp", "2fa",
}


class SpecError(ValueError):
    def __init__(self, errors, warnings=()):
        self.errors = list(errors)
        self.warnings = list(warnings)
        super().__init__("invalid spec:\n" + "\n".join(f"  - {e}" for e in self.errors))


def humanize(identifier):
    """Turn `pdf_delivery` into `PDF delivery`."""
    words = re.split(r"[_\-\s]+", str(identifier).strip())
    out = []
    for i, word in enumerate(w for w in words if w):
        if word.lower() in ACRONYMS:
            out.append(word.upper())
        elif i == 0:
            out.append(word[:1].upper() + word[1:])
        else:
            out.append(word.lower() if word.islower() or word.istitle() else word)
    return " ".join(out)


def lower_label(label):
    """Lowercase a label for use mid-sentence while keeping acronyms."""
    words = label.split(" ")
    if words and words[0] and words[0].upper() != words[0]:
        words[0] = words[0][:1].lower() + words[0][1:]
    return " ".join(words)


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


@dataclass
class Option:
    id: str
    label: str
    noop: bool = False
    summary: str = ""


@dataclass
class Dimension:
    id: str
    label: str
    options: list
    applies_when: object = None
    applies_when_text: str = ""
    bundle: bool = False
    summary: str = ""

    @property
    def option_ids(self):
        return [o.id for o in self.options]

    def option(self, option_id):
        for opt in self.options:
            if opt.id == option_id:
                return opt
        raise KeyError(option_id)


@dataclass
class Constraint:
    id: str
    kind: str  # requires | excludes | never
    when: object
    then: object
    reason: str = ""

    def holds(self, env):
        if self.kind == "never":
            return not self.then.evaluate(env)
        if self.when is not None and not self.when.evaluate(env):
            return True
        if self.kind == "requires":
            return self.then.evaluate(env)
        return not self.then.evaluate(env)

    @property
    def text(self):
        if self.kind == "never":
            return f"never {self.then}"
        if self.when is None:
            return f"always {self.then}" if self.kind == "requires" else f"never {self.then}"
        return f"if {self.when} {self.kind} {self.then}"


@dataclass
class Interaction:
    id: str
    title: str
    when: object
    summary: str = ""


@dataclass
class Spec:
    feature: str
    title: str
    summary: str
    dimensions: dict
    constraints: list
    interactions: list
    mode: str
    strength: int
    selected: list
    limits: dict
    stack: dict
    plan: dict
    verify: dict = field(default_factory=dict)
    raw: dict = field(repr=False, default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def option_map(self):
        return {d.id: d.option_ids for d in self.dimensions.values()}


def spec_hash(raw):
    """Stable short hash of a spec, insensitive to formatting and comments."""
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _suggest(word, candidates):
    close = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value).strip()


def _parse_options(dim_id, raw, errors):
    options = []
    items = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            entry = dict(value) if isinstance(value, dict) else {}
            entry["id"] = key
            items.append(entry)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "id" not in item and len(item) == 1:
                key, value = next(iter(item.items()))
                entry = dict(value) if isinstance(value, dict) else {}
                entry["id"] = key
                items.append(entry)
            elif isinstance(item, dict):
                items.append(dict(item))
            else:
                items.append({"id": item})
    else:
        errors.append(f"dimensions.{dim_id}: expected a list of options")
        return options
    seen = set()
    for entry in items:
        oid = entry.get("id")
        if oid is None or isinstance(oid, bool):
            errors.append(f"dimensions.{dim_id}: option {oid!r} is not a valid option id (quote it if you mean the word)")
            continue
        oid = str(oid)
        if not ID_RE.match(oid):
            errors.append(f"dimensions.{dim_id}: option id {oid!r} may only contain letters, digits, '_' and '-'")
            continue
        if oid in seen:
            errors.append(f"dimensions.{dim_id}: duplicate option {oid!r}")
            continue
        seen.add(oid)
        noop = entry.get("noop")
        options.append(Option(
            id=oid,
            label=str(entry.get("label") or humanize(oid)),
            noop=bool(noop) if noop is not None else oid.lower() in NOOP_IDS,
            summary=_text(entry.get("summary") or entry.get("description")),
        ))
    return options


def _parse_expr(text, path, known, errors):
    try:
        node = ex.parse(text if isinstance(text, str) else str(text))
    except ex.ExprError as exc:
        errors.append(f"{path}: {exc}")
        return None
    for problem in ex.validate(node, known):
        errors.append(f"{path}: {problem}")
    return node


def load(raw):
    """Validate a raw spec mapping and return a Spec, or raise SpecError."""
    errors, warnings = [], []
    if not isinstance(raw, dict):
        raise SpecError(["the spec must be a mapping with at least `feature` and `dimensions`"])

    for key in raw:
        if key not in TOP_LEVEL:
            warnings.append(f"unknown top-level key {key!r}{_suggest(key, TOP_LEVEL)} is ignored")

    feature = raw.get("feature", raw.get("project"))
    if not feature:
        errors.append("missing `feature` (a short slug such as lead-capture-flow)")
        feature = "feature"
    feature = str(feature)
    if not SLUG_RE.match(feature):
        errors.append(f"feature {feature!r} must be a lowercase slug such as {slugify(feature) or 'my-feature'!r}")

    title = str(raw.get("title") or humanize(feature))
    summary = _text(raw.get("summary") or raw.get("description"))

    dimensions = {}
    raw_dims = raw.get("dimensions")
    if not isinstance(raw_dims, dict) or not raw_dims:
        errors.append("`dimensions` must map each decision to its options")
        raw_dims = {}
    for dim_id, body in raw_dims.items():
        dim_id = str(dim_id)
        if not ID_RE.match(dim_id):
            errors.append(f"dimension id {dim_id!r} may only contain letters, digits, '_' and '-'")
            continue
        spec_body = body if isinstance(body, dict) and "options" in body else {"options": body}
        if isinstance(body, dict) and "options" in body:
            for key in body:
                if key not in ("options", "label", "applies_when", "bundle", "summary", "description"):
                    warnings.append(f"dimensions.{dim_id}: unknown key {key!r} is ignored")
        options = _parse_options(dim_id, spec_body.get("options"), errors)
        if not options:
            errors.append(f"dimensions.{dim_id}: needs at least one option")
        elif len(options) == 1:
            warnings.append(f"dimensions.{dim_id}: only one option, so this is not really a decision")
        dimensions[dim_id] = Dimension(
            id=dim_id,
            label=str(spec_body.get("label") or humanize(dim_id)),
            options=options,
            applies_when_text=_text(spec_body.get("applies_when")),
            bundle=bool(spec_body.get("bundle", False)),
            summary=_text(spec_body.get("summary") or spec_body.get("description")),
        )

    known = {d.id: d.option_ids for d in dimensions.values()}
    earlier = []
    for dim in dimensions.values():
        if dim.applies_when_text:
            path = f"dimensions.{dim.id}.applies_when"
            node = _parse_expr(dim.applies_when_text, path, known, errors)
            if node is not None:
                late = sorted({a.dim for a, _ in node.atoms() if a.dim in known and a.dim not in earlier})
                if late:
                    errors.append(
                        f"{path}: may only refer to dimensions listed above {dim.id!r}; "
                        f"move {', '.join(late)} before it"
                    )
                dim.applies_when = node
        earlier.append(dim.id)

    constraints = []
    raw_constraints = raw.get("constraints") or []
    if not isinstance(raw_constraints, list):
        errors.append("`constraints` must be a list")
        raw_constraints = []
    for i, item in enumerate(raw_constraints):
        path = f"constraints[{i}]"
        cid = f"C{i + 1}"
        if isinstance(item, str):
            item = {"never": item}
        if not isinstance(item, dict):
            errors.append(f"{path}: expected a mapping such as {{if: ..., requires: ...}}")
            continue
        cid = str(item.get("id") or cid)
        for key in item:
            if key not in ("id", "if", "requires", "excludes", "never", "reason"):
                errors.append(f"{path}: unknown key {key!r}{_suggest(str(key), ('if', 'requires', 'excludes', 'never', 'reason'))}")
        kinds = [k for k in ("requires", "excludes", "never") if k in item]
        if len(kinds) != 1:
            errors.append(f"{path}: use exactly one of `requires`, `excludes` or `never`")
            continue
        kind = kinds[0]
        if kind == "never" and "if" in item:
            errors.append(f"{path}: `never` does not take an `if`; use `if` + `excludes` instead")
            continue
        when = _parse_expr(item["if"], f"{path}.if", known, errors) if "if" in item else None
        then = _parse_expr(item[kind], f"{path}.{kind}", known, errors)
        if then is None or ("if" in item and when is None):
            continue
        constraints.append(Constraint(id=cid, kind=kind, when=when, then=then, reason=_text(item.get("reason"))))

    ids = [c.id for c in constraints]
    for cid in sorted({c for c in ids if ids.count(c) > 1}):
        errors.append(f"duplicate constraint id {cid!r}")

    interactions = []
    raw_ix = raw.get("interactions") or []
    if not isinstance(raw_ix, list):
        errors.append("`interactions` must be a list")
        raw_ix = []
    seen_ix = set()
    for i, item in enumerate(raw_ix):
        path = f"interactions[{i}]"
        if not isinstance(item, dict) or "when" not in item:
            errors.append(f"{path}: expected a mapping with `when` and `title`")
            continue
        ix_title = str(item.get("title") or f"Integrate {item['when']}")
        iid = str(item.get("id") or slugify(ix_title))
        if not ID_RE.match(iid):
            errors.append(f"{path}: id {iid!r} may only contain letters, digits, '_' and '-'")
            continue
        if iid in seen_ix:
            errors.append(f"{path}: duplicate interaction id {iid!r}")
            continue
        seen_ix.add(iid)
        node = _parse_expr(item["when"], f"{path}.when", known, errors)
        if node is None:
            continue
        interactions.append(Interaction(id=iid, title=ix_title, when=node, summary=_text(item.get("summary"))))

    generation = raw.get("generation") or {}
    if not isinstance(generation, dict):
        errors.append("`generation` must be a mapping such as {mode: pairwise}")
        generation = {}
    mode = str(generation.get("mode", "exhaustive")).replace("-", "").lower()
    if mode == "allpairs":
        mode = "pairwise"
    if mode not in MODES:
        errors.append(f"generation.mode {generation.get('mode')!r} must be one of {', '.join(MODES)}{_suggest(mode, MODES)}")
        mode = "exhaustive"
    strength = generation.get("strength")
    if mode == "pairwise":
        if strength not in (None, 2):
            warnings.append("generation.strength is always 2 for pairwise; use mode twise for other strengths")
        strength = 2
    elif mode == "twise":
        strength = 3 if strength is None else strength
        if not isinstance(strength, int) or isinstance(strength, bool) or strength < 1:
            errors.append("generation.strength must be a positive integer")
            strength = 2
        elif dimensions and strength > len(dimensions):
            errors.append(f"generation.strength {strength} is larger than the number of dimensions ({len(dimensions)})")
    else:
        strength = None
    selected = generation.get("variants") or []
    if mode == "selected" and not selected:
        errors.append("generation.mode selected needs `generation.variants`, a list of variants")
    if selected and not isinstance(selected, list):
        errors.append("generation.variants must be a list")
        selected = []

    limits = dict(DEFAULT_LIMITS)
    raw_limits = raw.get("limits") or {}
    if not isinstance(raw_limits, dict):
        errors.append("`limits` must be a mapping")
        raw_limits = {}
    for key, value in raw_limits.items():
        if key not in DEFAULT_LIMITS:
            warnings.append(f"limits.{key} is unknown{_suggest(key, DEFAULT_LIMITS)} and ignored")
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"limits.{key} must be a positive integer")
            continue
        limits[key] = value

    raw_stack = raw.get("stack") or {}
    if not isinstance(raw_stack, dict):
        errors.append("`stack` must be a mapping")
        raw_stack = {}
    stack = {
        "base_branch": str(raw_stack.get("base_branch", "main")),
        "branch_prefix": str(raw_stack.get("branch_prefix", feature)).strip("/"),
        "layout": str(raw_stack.get("layout", "tree")),
        "platform": str(raw_stack.get("platform", "auto")),
        "max_coupling": raw_stack.get("max_coupling", 2),
    }
    if not isinstance(stack["max_coupling"], int) or isinstance(stack["max_coupling"], bool) or stack["max_coupling"] < 0:
        errors.append("stack.max_coupling must be a non-negative integer")
        stack["max_coupling"] = 2
    for key in raw_stack:
        if key not in stack:
            warnings.append(f"stack.{key} is unknown{_suggest(key, stack)} and ignored")
    if stack["layout"] not in LAYOUTS:
        errors.append(f"stack.layout must be one of {', '.join(LAYOUTS)}")
    if stack["platform"] not in PLATFORMS:
        errors.append(f"stack.platform must be one of {', '.join(PLATFORMS)}")

    plan = raw.get("plan") or {}
    if not isinstance(plan, dict):
        errors.append("`plan` must map node ids to details")
        plan = {}
    for node_id, details in plan.items():
        if not isinstance(details, dict):
            errors.append(f"plan.{node_id}: expected a mapping of details")
            continue
        for key in details:
            if key not in PLAN_FIELDS:
                warnings.append(f"plan.{node_id}.{key} is unknown{_suggest(key, PLAN_FIELDS)} and ignored")

    verify = raw.get("verify") or {}
    if not isinstance(verify, dict):
        errors.append("`verify` must be a mapping such as {test: npm test, probe: node scripts/probe.js}")
        verify = {}
    for key, value in verify.items():
        if key not in ("test", "probe"):
            warnings.append(f"verify.{key} is unknown{_suggest(key, ('test', 'probe'))} and ignored")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"verify.{key} must be a shell command")
    verify = {k: str(v).strip() for k, v in verify.items() if k in ("test", "probe") and isinstance(v, str)}

    if errors:
        raise SpecError(errors, warnings)
    return Spec(
        feature=feature, title=title, summary=summary, dimensions=dimensions,
        constraints=constraints, interactions=interactions, mode=mode, strength=strength,
        selected=selected, limits=limits, stack=stack, plan=plan, verify=verify, raw=raw, warnings=warnings,
    )
