"""The planning document: one Markdown file per feature.

Layout (top to bottom):

    front matter      machine-owned: revision, spec hash, branch layout, planned follow-ups
    # Title           human-owned
    ## Intent         human-owned
    ## Review notes   agent-owned judgment (semantic findings, open questions)
    ## Spec           canonical ```yaml cad-spec block
    generated region  between cad:generated markers, rewritten by `render`
    ## Changelog      newest first, appended by `render`

Progress (which branches exist, which are merged) is never stored here: it is
read from git whenever it is needed.
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

__all__ = ["DocError", "read", "load_raw_spec", "create", "render", "git_state"]

GEN_START = "<!-- cad:generated:start (edit the spec above and run `cad.py render`; changes below this line are overwritten) -->"
GEN_START_RE = re.compile(r"<!-- cad:generated:start.*?-->")
GEN_END = "<!-- cad:generated:end -->"
SPEC_RE = re.compile(r"^```ya?ml cad-spec[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
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
    front = {"cad": 1, "feature": feature, "revision": 0}
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


def git_state(path, result, recorded=None, repo=None):
    """Progress per node from git ({"status": planned|branched|merged}), plus the recorded `onto`."""
    recorded = recorded or {}
    out = {nid: {"onto": v.get("onto")} for nid, v in recorded.items() if v and v.get("onto")}
    repo = repo or _repo_of(path)
    if not repo:
        return out
    report = verify_mod.Report()
    verify_mod.check_state(repo, result.stack, report)
    for nid, status in report.nodes.items():
        out.setdefault(nid, {})["status"] = status
    return out


def _repo_of(path):
    folder = os.path.dirname(os.path.abspath(path))
    return gitops.toplevel(folder) if gitops.is_repo(folder) else None


def _contracts(result, prev_contracts, state, followups, revision):
    """Compare each started node's contract with its snapshot.

    Returns (contract snapshots, new follow-ups, changelog lines).
    """
    snapshots, new_followups, log = {}, [], []
    for node in result.plan.nodes:
        if node.kind == "followup":
            continue
        status = (state.get(node.id) or {}).get("status", "planned")
        if status == "planned":
            continue
        current = plan_mod.contract(node)
        snapshot = prev_contracts.get(node.id)
        snapshots[node.id] = current
        if snapshot is None or snapshot == current:
            continue
        diff = [f"+ {l}" for l in current if l not in snapshot] + [f"- {l}" for l in snapshot if l not in current]
        if status == "merged":
            fid = f"{node.id}.r{revision}"
            if not any(f.get("id") == fid for f in followups):
                new_followups.append({"id": fid, "of": node.id, "revision": revision, "changes": diff})
                log.append(f"  - Follow-up planned: `{fid}`, because `{node.id}` is merged and its contract changed.")
        else:
            log.append(
                f"  - Changed after work started: `{node.id}` ({'; '.join(diff)}). "
                "Amend its branch, then run `cad.py restack`."
            )
    return snapshots, new_followups, log


def render(path, note=None, date=None):
    """Regenerate the plan inside a document. Returns (result, changed)."""
    doc = read(path)
    raw, spec = _load(doc)
    h = spec_mod.spec_hash(raw)
    front = dict(doc.front)
    prev_nodes = {k: dict(v or {}) for k, v in (front.get("nodes") or {}).items()}
    followups = [dict(f) for f in front.get("followups") or []]
    first = not front.get("revision")
    result = engine.run(spec, followups=followups)
    if result.status == "error":
        return result, False
    live = git_state(path, result, prev_nodes)
    if live:
        result = engine.run(spec, state=live, followups=followups)

    changed = front.get("spec_hash") != h
    revision = int(front.get("revision") or 0) + (1 if changed else 0)
    snapshots, new_followups, contract_log = _contracts(result, doc.contracts or {}, live, followups, revision)
    if new_followups:
        followups += new_followups
        result = engine.run(spec, state=live, followups=followups)

    nodes, restacks = {}, []
    for nid in result.stack.order:
        p = result.stack.placements[nid]
        nodes[nid] = {"branch": p.branch, "onto": p.parent_branch}
        old_onto = prev_nodes.get(nid, {}).get("onto")
        if (live.get(nid) or {}).get("status") == "branched" and old_onto and old_onto != p.parent_branch:
            restacks.append(f"`{nid}` from `{old_onto}` onto `{p.parent_branch}`")
    repo = _repo_of(path)
    orphaned = [
        nid for nid, old in prev_nodes.items()
        if nid not in nodes and repo and old.get("branch") and gitops.branch_exists(repo, old["branch"])
    ]

    log = []
    if changed:
        prev_counts = front.get("counts") or {}
        log.append(f"- **r{revision}** ({today(date)}): " + (note.strip() if note else ("Initial plan." if first else "Spec edited.")))
        if not first:
            added = [n for n in result.stack.order if n not in prev_nodes]
            removed = [n for n in prev_nodes if n not in nodes]
            if added:
                log.append(f"  - Added: {_codes(added)}.")
            if removed:
                log.append(f"  - Removed: {_codes(removed)}.")
            now = {"valid": len(result.space.valid), "scenarios": len(result.scenarios.variants), "nodes": len(result.plan.nodes)}
            deltas = [
                f"{label} {prev_counts[key]} to {now[key]}"
                for key, label in (("valid", "valid variants"), ("scenarios", "test scenarios"), ("nodes", "nodes"))
                if prev_counts.get(key) is not None and prev_counts[key] != now[key]
            ]
            if deltas:
                log.append(f"  - {'; '.join(deltas).capitalize()}.")
        log += contract_log
    elif contract_log:
        log = [f"- **r{revision}** ({today(date)}): Work in progress changed the plan."] + contract_log
    if restacks:
        log.append(f"  - Restack needed: {'; '.join(restacks)}. Run `cad.py restack`.")
    if orphaned:
        log.append(f"  - Branches exist for nodes no longer planned: {_codes(orphaned)}. Close or revert them on purpose.")
    if log and not log[0].startswith("- "):
        log.insert(0, f"- **r{revision}** ({today(date)}): Branch layout changed.")

    new_front = {
        "cad": 1,
        "feature": spec.feature,
        "revision": revision,
        "spec_hash": h,
        "counts": {
            "theoretical": result.space.theoretical,
            "valid": len(result.space.valid),
            "scenarios": len(result.scenarios.variants),
            "nodes": len(result.plan.nodes),
        },
        "nodes": nodes,
    }
    if followups:
        new_front["followups"] = followups

    content = render_mod.generated_markdown(result, doc_path=os.path.relpath(path))
    body = _replace_generated(doc.body, content)
    if log:
        body = _add_changelog(body, log)
    body = _write_contracts(body, snapshots)
    _write(path, new_front, body)
    return result, changed
