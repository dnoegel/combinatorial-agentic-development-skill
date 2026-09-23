"""The planning document: one Markdown file per feature.

Layout (top to bottom):

    front matter      machine-owned state: revision, status, sign-off, node progress
    # Title           human-owned
    ## Intent         human-owned
    ## Review notes   agent-owned judgment (semantic findings, open questions)
    ## Spec           canonical ```yaml cad-spec block
    generated region  between cad:generated markers, rewritten by `render`
    ## Changelog      newest first, appended by `render` and `approve`
"""

import datetime
import json
import os
import re
from dataclasses import dataclass

from . import engine, gitops, miniyaml, render as render_mod
from . import plan as plan_mod
from . import spec as spec_mod
from . import verify as verify_mod

__all__ = ["DocError", "read", "load_raw_spec", "create", "render", "approve", "check", "mark"]

GEN_START = "<!-- cad:generated:start (edit the spec above and run `cad.py render`; changes below this line are overwritten) -->"
GEN_START_RE = re.compile(r"<!-- cad:generated:start.*?-->")
GEN_END = "<!-- cad:generated:end -->"
SPEC_RE = re.compile(r"^```ya?ml cad-spec[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
STATUSES = ("planned", "branched", "mr-open", "merged")
CONTRACTS_RE = re.compile(r"\n*<!-- cad:contracts\n(.*?)\n-->\n?", re.S)
TAGLINE = "_Why choose a product path when you can implement the whole decision space?_"


class DocError(ValueError):
    pass


@dataclass
class Doc:
    path: str
    text: str
    front: dict
    body: str
    spec_text: str
    contracts: dict = None


def _read_contracts(body):
    match = CONTRACTS_RE.search(body)
    if not match:
        return {}
    out = {}
    for line in match.group(1).splitlines():
        if line.strip():
            node, _, payload = line.partition(" ")
            out[node] = json.loads(payload)
    return out


def _write_contracts(body, contracts):
    """Snapshots of what started nodes promised, kept out of sight at the end of the document."""
    body = CONTRACTS_RE.sub("\n", body).rstrip() + "\n"
    if not contracts:
        return body
    lines = [f"{node} {json.dumps(contracts[node], ensure_ascii=False)}" for node in sorted(contracts)]
    return body + "\n<!-- cad:contracts\n" + "\n".join(lines) + "\n-->\n"


def today(date=None):
    return date or os.environ.get("CAD_DATE") or datetime.date.today().isoformat()


def read(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    front, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1:
            raise DocError(f"{path}: front matter is not closed with ---")
        front = miniyaml.loads(text[4:end]) or {}
        body = text[end + 5:]
    match = SPEC_RE.search(body)
    if not match:
        raise DocError(f"{path}: no ```yaml cad-spec block found")
    return Doc(path=path, text=text, front=front, body=body, spec_text=match.group(1), contracts=_read_contracts(body))


def load_raw_spec(path):
    """Read a spec from a planning document, YAML file or JSON file."""
    if path.endswith(".md"):
        text = read(path).spec_text
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if path.endswith(".json"):
        return json.loads(text)
    try:
        return miniyaml.loads(text)
    except miniyaml.YamlError as exc:
        raise DocError(f"{path}: spec is not valid YAML ({exc})") from exc


STARTER_SPEC = """\
feature: {feature}
title: {title}

dimensions:
  # decision_name: [option_a, option_b, none]
  example_decision: [option_a, option_b]

constraints: []
  # - if: example_decision == option_a
  #   requires: other_decision != none

generation:
  mode: exhaustive   # exhaustive | pairwise | twise | selected
"""


def create(path, feature, title=None, spec_text=None, intent=""):
    if os.path.exists(path):
        raise DocError(f"{path} already exists")
    title = title or spec_mod.humanize(feature)
    spec_text = (spec_text or STARTER_SPEC.format(feature=feature, title=title)).rstrip("\n")
    front = {"cad": 1, "feature": feature, "revision": 0, "status": "draft"}
    body = "\n".join([
        f"# {title}",
        "",
        TAGLINE,
        "",
        "## Intent",
        "",
        intent.strip() or "_What this feature is for and why these decisions are still open._",
        "",
        "## Review notes",
        "",
        "_Semantic findings and open questions from review. Tool findings are listed in the generated section._",
        "",
        "## Spec",
        "",
        "The canonical decision space. Edit it directly or describe the change in conversation; "
        "either way the plan below is regenerated from it.",
        "",
        "```yaml cad-spec",
        spec_text,
        "```",
        "",
        GEN_START,
        GEN_END,
        "",
        "## Changelog",
        "",
    ])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _write(path, front, body)


def _write(path, front, body):
    text = "---\n" + miniyaml.dumps(front) + "---\n\n" + body.lstrip("\n")
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _replace_generated(body, content):
    block = f"{GEN_START}\n\n{content.rstrip()}\n\n{GEN_END}"
    start = GEN_START_RE.search(body)
    end = body.find(GEN_END)
    if start and end != -1 and end > start.start():
        return body[:start.start()] + block + body[end + len(GEN_END):]
    idx = body.find("\n## Changelog")
    if idx != -1:
        return body[:idx] + "\n" + block + "\n" + body[idx:]
    return body.rstrip() + "\n\n" + block + "\n"


def _add_changelog(body, lines):
    entry = "\n".join(lines) + "\n"
    match = re.search(r"^## Changelog[ \t]*\n\n?", body, re.M)
    if not match:
        return body.rstrip() + "\n\n## Changelog\n\n" + entry
    return body[:match.end()] + entry + body[match.end():]


def _load(doc):
    try:
        raw = miniyaml.loads(doc.spec_text)
    except miniyaml.YamlError as exc:
        raise DocError(f"{doc.path}: spec is not valid YAML ({exc})") from exc
    spec = spec_mod.load(raw)
    return raw, spec


def _codes(ids):
    return ", ".join(f"`{i}`" for i in ids)


def git_state(path, result, state):
    """Recorded progress, upgraded with what git shows: branches that exist or are merged."""
    folder = os.path.dirname(os.path.abspath(path))
    out = {k: dict(v or {}) for k, v in state.items()}
    if not gitops.is_repo(folder):
        return out
    report = verify_mod.Report()
    verify_mod.check_state(gitops.toplevel(folder), result.stack, report)
    for nid, status in report.nodes.items():
        recorded = out.setdefault(nid, {}).get("status", "planned")
        if recorded == "planned" or (status == "merged" and recorded != "merged"):
            out[nid]["status"] = status
    return out


def _contracts(result, prev_nodes, prev_contracts, state, followups, revision):
    """Compare each started node's contract with its snapshot.

    Returns (info per node, contract snapshots, new follow-ups, changelog lines).
    """
    info, snapshots, new_followups, log = {}, {}, [], []
    for node in result.plan.nodes:
        if node.kind == "followup":
            continue
        current = plan_mod.contract(node)
        old = prev_nodes.get(node.id) or {}
        status = (state.get(node.id) or {}).get("status", "planned")
        entry = {}
        snapshot = prev_contracts.get(node.id)
        if status != "planned":
            if snapshot is None or snapshot == current:
                snapshots[node.id] = current
            else:
                diff = [f"+ {l}" for l in current if l not in snapshot] + [f"- {l}" for l in snapshot if l not in current]
                if status == "merged":
                    fid = f"{node.id}.r{revision}"
                    if not any(f.get("id") == fid for f in followups):
                        new_followups.append({"id": fid, "of": node.id, "revision": revision, "changes": diff})
                        log.append(f"  - Follow-up planned: `{fid}`, because `{node.id}` is merged and its contract changed.")
                    snapshots[node.id] = current
                else:
                    snapshots[node.id] = snapshot
                    entry["needs_update"] = diff
                    if old.get("needs_update") != diff:
                        log.append(f"  - Needs update: `{node.id}` is {status} and its contract changed; amend the branch, then restack its children.")
        info[node.id] = entry
    return info, snapshots, new_followups, log


def render(path, note=None, date=None, _force_status=None, _changelog=None):
    """Regenerate the plan inside a document. Returns (result, changed)."""
    doc = read(path)
    raw, spec = _load(doc)
    h = spec_mod.spec_hash(raw)
    front = dict(doc.front)
    prev_nodes = {k: dict(v or {}) for k, v in (front.get("nodes") or {}).items()}
    followups = [dict(f) for f in front.get("followups") or []]
    first = not front.get("revision")
    known = None if first else set(prev_nodes)
    result = engine.run(spec, known_nodes=known, state=prev_nodes, followups=followups)
    if result.status == "error":
        return result, False
    live = git_state(path, result, prev_nodes)
    if live != prev_nodes:
        result = engine.run(spec, known_nodes=known, state=live, followups=followups)

    changed = front.get("spec_hash") != h
    revision = int(front.get("revision") or 0) + (1 if changed else 0)
    contract_info, snapshots, new_followups, contract_log = _contracts(
        result, prev_nodes, doc.contracts or {}, live, followups, revision
    )
    if new_followups:
        followups += new_followups
        result = engine.run(spec, known_nodes=known, state=live, followups=followups)
    status = _force_status or front.get("status") or "draft"
    approval = front.get("approved")
    log = []
    if changed or (approval and approval.get("hash") != h):
        if status in ("approved", "implementing", "done") or approval:
            if approval:
                log.append("  - Sign-off cleared: the spec changed after approval.")
            status = "draft"
            approval = None

    state = {}
    restacks = []
    for nid in result.stack.order:
        p = result.stack.placements[nid]
        old = prev_nodes.get(nid) or {}
        entry = {"branch": p.branch, "onto": p.parent_branch, "status": live.get(nid, {}).get("status", "planned")}
        entry.update(contract_info.get(nid, {}))
        if old.get("mr"):
            entry["mr"] = old["mr"]
        restack_from = old.get("restack_from")
        if entry["status"] not in ("planned", "merged") and old.get("onto") and old["onto"] != p.parent_branch:
            restack_from = restack_from or old["onto"]
        if restack_from and restack_from != p.parent_branch:
            entry["restack_from"] = restack_from
            if not old.get("restack_from"):
                restacks.append(f"`{nid}` from `{restack_from}` onto `{p.parent_branch}`")
        state[nid] = entry
    obsolete = []
    for nid, old in prev_nodes.items():
        if nid in state:
            continue
        if (old or {}).get("status", "planned") != "planned":
            kept = dict(old)
            kept["obsolete"] = True
            state[nid] = kept
            if not old.get("obsolete"):
                obsolete.append(nid)

    if changed:
        prev_counts = front.get("counts") or {}
        added = [n for n in result.stack.order if n not in prev_nodes]
        removed = [n for n in prev_nodes if n not in result.plan.by_id and not (prev_nodes[n] or {}).get("obsolete")]
        head = f"- **r{revision}** ({today(date)}): " + (note.strip() if note else ("Initial plan." if first else "Spec edited."))
        lines = [head]
        if not first:
            if added:
                lines.append(f"  - Added: {_codes(added)}.")
            if removed:
                lines.append(f"  - Removed: {_codes(removed)}.")
            deltas = []
            for key, label in (("valid", "valid variants"), ("scenarios", "test scenarios"), ("nodes", "nodes")):
                new_value = {
                    "valid": len(result.space.valid),
                    "scenarios": len(result.scenarios.variants),
                    "nodes": len(result.plan.nodes),
                }[key]
                if prev_counts.get(key) is not None and prev_counts.get(key) != new_value:
                    deltas.append(f"{label} {prev_counts[key]} to {new_value}")
            if deltas:
                lines.append(f"  - {'; '.join(deltas).capitalize()}.")
        if restacks:
            lines.append(f"  - Restack needed: {'; '.join(restacks)}.")
        if obsolete:
            lines.append(f"  - Started but no longer planned: {_codes(obsolete)}. Close or revert those MRs on purpose.")
        log = lines + contract_log + log
    elif contract_log:
        log = [f"- **r{revision}** ({today(date)}): Progress changed the plan."] + contract_log + log
    if _changelog:
        log = _changelog + log

    new_front = {
        "cad": 1,
        "feature": spec.feature,
        "revision": revision,
        "status": status,
        "spec_hash": h,
        "approved": approval,
        "counts": {
            "theoretical": result.space.theoretical,
            "valid": len(result.space.valid),
            "scenarios": len(result.scenarios.variants),
            "nodes": len(result.plan.nodes),
        },
        "nodes": state,
        "followups": followups,
    }
    if new_front["approved"] is None:
        del new_front["approved"]
    if not followups:
        del new_front["followups"]

    rel = os.path.relpath(path)
    content = render_mod.generated_markdown(result, state, doc_path=rel, doc_status=status)
    body = _replace_generated(doc.body, content)
    if log:
        body = _add_changelog(body, log)
    body = _write_contracts(body, snapshots)
    _write(path, new_front, body)
    return result, changed


def approve(path, by, date=None):
    doc = read(path)
    raw, spec = _load(doc)
    h = spec_mod.spec_hash(raw)
    if doc.front.get("spec_hash") != h:
        raise DocError("The spec changed since the last render. Run `cad.py render` and review the plan first.")
    if not by or not str(by).strip():
        raise DocError("Approval needs a name: --by <reviewer>.")
    result = engine.run(spec, known_nodes=None)
    if result.status == "error":
        raise DocError("The plan has errors and cannot be approved.")
    front = dict(doc.front)
    front["status"] = "approved"
    front["approved"] = {"by": str(by).strip(), "on": today(date), "hash": h}
    _write(path, front, doc.body)
    entry = [f"- **r{front.get('revision', 1)}** ({today(date)}): Approved by {str(by).strip()}."]
    if result.confirmations:
        entry.append("  - Confirmed despite: " + " ".join(result.confirmations))
    return render(path, date=date, _force_status="approved", _changelog=entry)[0]


def check(path):
    """Return (ok, message): is the document approved for its current spec?"""
    doc = read(path)
    raw, _ = _load(doc)
    h = spec_mod.spec_hash(raw)
    front = doc.front
    if front.get("spec_hash") != h:
        return False, "The spec changed since the last render. Run `cad.py render`, review, and approve again."
    approval = front.get("approved") or {}
    if front.get("status") not in ("approved", "implementing", "done") or not approval:
        return False, "The plan is not approved yet. Ask the engineer to review it, then run `cad.py approve --by <name>`."
    if approval.get("hash") != h:
        return False, "The approval belongs to an older spec. Review and approve again."
    return True, f"Approved by {approval.get('by')} on {approval.get('on')} for spec {h}."


def mark(path, node_id, status, mr=None, restacked=False, updated=False, date=None):
    if status not in STATUSES:
        raise DocError(f"status must be one of {', '.join(STATUSES)}")
    ok, message = check(path)
    if not ok:
        raise DocError(message)
    doc = read(path)
    front = dict(doc.front)
    nodes = front.get("nodes") or {}
    if node_id not in nodes:
        raise DocError(f"unknown node {node_id!r}; nodes are: {', '.join(nodes)}")
    entry = dict(nodes[node_id])
    entry["status"] = status
    if mr:
        entry["mr"] = str(mr)
    if restacked or status == "merged":
        entry.pop("restack_from", None)
    body = doc.body
    if updated:
        entry.pop("needs_update", None)
        contracts = dict(doc.contracts or {})
        contracts.pop(node_id, None)
        body = _write_contracts(body, contracts)
    nodes[node_id] = entry
    front["nodes"] = nodes
    active = [v for v in nodes.values() if not v.get("obsolete")]
    doc_status = "done" if active and all(v["status"] == "merged" for v in active) else "implementing"
    front["status"] = doc_status
    _write(path, front, body)
    return render(path, date=date, _force_status=doc_status)[0]
