"""Compare the plan with reality: git state, integration, and observable behavior.

Three checks, cheapest first:

state        every branch that exists sits on its planned parent and contains
             the parent's current tip (a stale branch needs a restack).
integration  all existing branches merged in stack order into a temporary
             worktree; merge conflicts fail, then the spec's test command runs.
probe        for every targeted variant, the spec's probe command reports the
             options it can observe in the product; each active option must be
             observed. This catches options that exist on a branch but are
             never wired into the product.

Nothing here touches branches or the working tree. The only writes are metadata
refs under refs/cad/base/, which remember each branch's fork point so restacks
replay exactly the branch's own commits.
"""

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from . import gitops
from .space import variant_env

__all__ = ["Issue", "Report", "run", "observed_tokens"]


@dataclass
class Issue:
    check: str  # state | integration | probe
    node: object
    text: str
    fix: str = ""


@dataclass
class Report:
    nodes: dict = field(default_factory=dict)  # node -> inferred status
    issues: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)  # worth fixing, but not a failure
    probe: dict = field(default_factory=dict)  # summary numbers

    @property
    def ok(self):
        return not self.issues


def _effective_parent(stack, statuses, nid):
    p = stack.placements[nid]
    if p.parent is None or statuses.get(p.parent) == "merged":
        return stack.base_branch
    return p.parent_branch


FORK_REF = "refs/cad/base/"


def fork_ref(branch):
    return FORK_REF + branch


def record_fork(repo, branch, parent, known=None):
    """Remember which parent commit a branch is based on (metadata ref, never a branch)."""
    tip = gitops.git(repo, "rev-parse", parent).stdout.strip() if known is None else known
    gitops.git(repo, "update-ref", fork_ref(branch), tip, check=False)


def old_base(repo, branch, parent):
    """The commit a branch was built on: the recorded fork point, else the merge base."""
    ref = fork_ref(branch)
    if gitops.ref_exists(repo, ref) and gitops.is_ancestor(repo, ref, branch):
        return gitops.git(repo, "rev-parse", ref).stdout.strip()
    return gitops.git(repo, "merge-base", parent, branch).stdout.strip()


def subtree(stack, node_id):
    out = [node_id]
    for nid in stack.order:
        if stack.placements[nid].parent in out and nid not in out:
            out.append(nid)
    return out


def check_state(repo, stack, report):
    base = stack.base_branch
    heads = gitops.refs(repo)
    if base not in heads:
        report.issues.append(Issue("state", None, f"base branch `{base}` does not exist"))
        return
    merged = gitops.merged_into(repo, base)
    forks = gitops.refs(repo, FORK_REF)
    for nid in stack.order:
        branch = stack.placements[nid].branch
        if branch not in heads:
            report.nodes[nid] = "planned"
        else:
            report.nodes[nid] = "merged" if branch in merged else "branched"
    stale = []
    for nid in stack.order:
        if report.nodes[nid] != "branched":
            continue
        p = stack.placements[nid]
        parent = _effective_parent(stack, report.nodes, nid)
        if parent not in heads:
            report.issues.append(Issue(
                "state", nid, f"`{p.branch}` exists but its parent `{parent}` does not",
                "create the parent first, or recreate this branch from the right parent",
            ))
            continue
        if not gitops.is_ancestor(repo, heads[parent], heads[p.branch]):
            stale.append(nid)
        elif forks.get(p.branch) != heads[parent]:
            record_fork(repo, p.branch, parent, heads[parent])
    reported = set()
    for nid in stale:
        if nid in reported:
            continue
        tree = [n for n in subtree(stack, nid) if report.nodes.get(n) == "branched"]
        reported.update(tree)
        p = stack.placements[nid]
        parent = _effective_parent(stack, report.nodes, nid)
        followers = [n for n in tree if n != nid]
        report.issues.append(Issue(
            "state", nid,
            f"`{p.branch}` is stale: `{parent}` has commits it does not contain"
            + (f"; {len(followers)} branch(es) built on it must follow: {', '.join(followers)}" if followers else ""),
            f"cad.py restack <doc> {nid}",
        ))
    missing = [n for n in stack.order if report.nodes[n] == "planned"]
    if missing:
        report.notes.append(f"{len(missing)} node(s) have no branch yet: {', '.join(missing)}")


def _run(cmd, cwd, env=None, stdin=None, timeout=600):
    return subprocess.run(
        cmd, shell=True, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )


def _tail(text, lines=12):
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return "\n".join(rows[-lines:])


@contextlib.contextmanager
def temp_worktree(repo, start):
    """A throwaway detached worktree; the caller's checkout is never touched."""
    tmp = tempfile.mkdtemp(prefix="cad-verify-")
    path = os.path.join(tmp, "worktree")
    gitops.git(repo, "worktree", "add", "--detach", path, start)
    try:
        yield path
    finally:
        gitops.git(repo, "worktree", "remove", "--force", path, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def merge_branch(path, branch):
    """Merge a branch into the worktree. Returns None on success, else the conflicting files."""
    proc = gitops.git(path, "merge", "--no-ff", "--no-edit", "-m", f"verify: merge {branch}", branch, check=False)
    if proc.returncode == 0:
        return None
    files = gitops.git(path, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
    gitops.git(path, "merge", "--abort", check=False)
    return files


def merge_shared(path, result, statuses, report):
    """Merge every existing branch that is meant for the base branch (everything except open branches)."""
    merged = []
    for nid in result.stack.order:
        if statuses.get(nid) != "branched" or result.plan.by_id[nid].hold:
            continue
        branch = result.stack.placements[nid].branch
        files = merge_branch(path, branch)
        if files is not None:
            report.issues.append(Issue(
                "integration", nid,
                f"`{branch}` conflicts with the branches merged before it"
                + (f" in {', '.join(f'`{f}`' for f in files)}" if files else ""),
                "move shared code into a common ancestor node, or discover modules at runtime "
                "so parallel branches never edit the same file",
            ))
            continue
        merged.append(branch)
    return merged


def open_nodes_for(result, variant):
    """Open branches whose code belongs in `variant`, in stack order."""
    env = variant_env(result.space.dims, variant)
    return [nid for nid in result.stack.order
            if result.plan.by_id[nid].hold and result.plan.by_id[nid].applies and result.plan.by_id[nid].applies(env)]


def _describe(dims, variant):
    return " ".join(f"{d}={v}" for d, v in zip(dims, variant) if v is not None)


def check_integration(repo, result, report, test_cmd, probe_cmd, scenarios):
    """Merge the stack into a temporary worktree, then test and probe.

    Without open branches everything is merged once. With open branches every
    scenario is composed on its own: the shared branches plus the open
    branches of the options it selects, because alternatives of one decision
    are allowed to conflict with each other.
    """
    dims = result.space.dims
    with temp_worktree(repo, result.stack.base_branch) as path:
        merged = merge_shared(path, result, report.nodes, report)
        report.notes.append(f"integration: merged {len(merged)} branch(es) into a temporary worktree")
        if not any(n.hold for n in result.plan.nodes):
            if test_cmd:
                proc = _run(test_cmd, path)
                if proc.returncode != 0:
                    report.issues.append(Issue(
                        "integration", None,
                        f"`{test_cmd}` fails with all branches merged:\n{_tail(proc.stdout + proc.stderr)}",
                    ))
                else:
                    report.notes.append(f"integration: `{test_cmd}` passes with all branches merged")
            if probe_cmd:
                _report_probe(report, [_probe_one(path, sid, dims, v, probe_cmd) for sid, v in scenarios])
            return
        head = gitops.git(path, "rev-parse", "HEAD").stdout.strip()
        probed, composed, skipped, failed_tests = [], 0, [], []
        for sid, variant in scenarios:
            needed = open_nodes_for(result, variant)
            missing = [n for n in needed if report.nodes.get(n) != "branched"]
            if missing:
                skipped.append(sid)
                continue
            gitops.git(path, "reset", "-q", "--hard", head)
            gitops.git(path, "clean", "-qfdx", check=False)
            conflict = False
            for nid in needed:
                branch = result.stack.placements[nid].branch
                files = merge_branch(path, branch)
                if files is not None:
                    report.issues.append(Issue(
                        "integration", nid,
                        f"{sid} ({_describe(dims, variant)}): `{branch}` conflicts"
                        + (f" in {', '.join(f'`{f}`' for f in files)}" if files else ""),
                        "open branches of different decisions must merge cleanly together",
                    ))
                    conflict = True
                    break
            if conflict:
                continue
            composed += 1
            if test_cmd:
                proc = _run(test_cmd, path)
                if proc.returncode != 0:
                    failed_tests.append(sid)
                    if len(failed_tests) <= 3:
                        report.issues.append(Issue(
                            "integration", None,
                            f"`{test_cmd}` fails for {sid} ({_describe(dims, variant)}):\n{_tail(proc.stdout + proc.stderr, 8)}",
                        ))
            if probe_cmd:
                probed.append(_probe_one(path, sid, dims, variant, probe_cmd))
        report.notes.append(f"integration: composed and checked {composed} scenario(s) with their open branches")
        if test_cmd and composed and not failed_tests:
            report.notes.append(f"integration: `{test_cmd}` passes in every composed scenario")
        if skipped:
            report.notes.append(
                f"{len(skipped)} scenario(s) not checked yet because an open branch they need does not exist: "
                + ", ".join(skipped)
            )
        if probe_cmd:
            _report_probe(report, probed)


def observed_tokens(text):
    """Parse `dim=option` tokens from probe output (whitespace or comma separated)."""
    out = set()
    for raw in text.replace(",", " ").split():
        if "=" in raw:
            dim, _, value = raw.partition("=")
            out.add((dim.strip(), value.strip()))
    return out


def _probe_one(cwd, sid, dims, variant, probe_cmd):
    payload = {d: v for d, v in zip(dims, variant)}
    expected = {(d, v) for d, v in payload.items() if v is not None}
    data = json.dumps(payload, sort_keys=True)
    proc = _run(probe_cmd, cwd, env=dict(os.environ, CAD_VARIANT=data), stdin=data, timeout=120)
    if proc.returncode != 0:
        return {"sid": sid, "payload": payload, "error": _tail(proc.stderr or proc.stdout, 6)}
    seen = {t for t in observed_tokens(proc.stdout) if t[0] in payload}
    return {"sid": sid, "payload": payload, "missing": expected - seen, "unexpected": seen - expected}


def _report_probe(report, results):
    failures = {}
    failing = errors = 0
    for r in results:
        if "error" in r:
            errors += 1
            failing += 1
            if errors <= 3:
                report.issues.append(Issue("probe", None, f"probe failed for {r['sid']} {r['payload']}:\n{r['error']}"))
            continue
        if r["missing"] or r["unexpected"]:
            failing += 1
        for d, v in r["missing"]:
            failures.setdefault(("missing", d, v), []).append(r["sid"])
        for d, v in r["unexpected"]:
            failures.setdefault(("unexpected", d, v), []).append(r["sid"])
    for (kind, d, v), ids in sorted(failures.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        listed = ", ".join(ids[:5]) + (" ..." if len(ids) > 5 else "")
        if kind == "missing":
            text = f"`{d}={v}` is selected in {len(ids)} scenario(s) but the probe never observes it ({listed})"
            fix = "wire the option into the product (registration, discovery, composition root) and emit its marker"
        else:
            text = f"the probe observes `{d}={v}` in {len(ids)} scenario(s) that did not select it ({listed})"
            fix = "the option leaks into variants that did not choose it; check defaults and fallbacks"
        report.issues.append(Issue("probe", f"opt.{d}.{v}", text, fix))
    report.probe = {"scenarios": len(results), "failing": failing, "errors": errors}
    if results and not failing:
        report.notes.append(f"probe: all {len(results)} scenarios show exactly their selected options")


def check_hygiene(repo, result, report):
    """Warnings that do not fail verify: stray worktrees and file ownership."""
    stack, plan = result.stack, result.plan
    main_tree = os.path.realpath(gitops.toplevel(repo))
    listing = gitops.git(repo, "worktree", "list", "--porcelain", check=False).stdout
    for block in listing.strip().split("\n\n"):
        lines = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
        path = lines.get("worktree", "")
        if not path or os.path.realpath(path) == main_tree or "cad-verify-" in path:
            continue
        what = f"detached at {lines.get('HEAD', '')[:7]}" if "detached" in lines else lines.get("branch", "")
        report.warnings.append(
            f"extra worktree `{path}` ({what}); remove it when you are done: git worktree remove --force {shlex.quote(path)}"
        )
    owner = {f: n.id for n in plan.nodes for f in n.files}
    for nid in stack.order:
        node = plan.by_id[nid]
        if report.nodes.get(nid) != "branched" or not node.files:
            continue
        p = stack.placements[nid]
        parent = _effective_parent(stack, report.nodes, nid)
        if not gitops.branch_exists(repo, parent):
            continue
        changed = gitops.git(repo, "diff", "--name-only", f"{parent}...{p.branch}", check=False).stdout.split()
        foreign = sorted(f for f in changed if owner.get(f) not in (None, nid))
        unlisted = sorted(f for f in changed if f not in owner)
        if foreign:
            report.warnings.append(
                f"`{p.branch}` edits files owned by other nodes: "
                + ", ".join(f"`{f}` ({owner[f]})" for f in foreign)
                + "; move the change to the owning node or restack"
            )
        if unlisted:
            report.warnings.append(
                f"`{p.branch}` adds or edits files the plan does not list: {', '.join(f'`{f}`' for f in unlisted)}; "
                f"add them to `plan.{nid}.files` so ownership and conflict checks can see them"
            )


def run(repo, result, integration=False, probe=False, only=None):
    spec, stack = result.spec, result.stack
    report = Report()
    check_state(repo, stack, report)
    check_hygiene(repo, result, report)
    scenarios = [(f"T{i:02d}", v) for i, v in enumerate(result.scenarios.variants, 1)]
    if only:
        from .plan import dependents
        ids = {only, *dependents(result.plan, only)}
        wanted = {sid for n in result.plan.nodes if n.id in ids for sid in n.scenarios}
        scenarios = [(sid, v) for sid, v in scenarios if sid in wanted]
        report.notes.append(f"probe limited to {len(scenarios)} scenario(s) affected by `{only}`")
    test_cmd = spec.verify.get("test")
    probe_cmd = spec.verify.get("probe")
    if probe and not probe_cmd:
        report.issues.append(Issue("probe", None, "no `verify.probe` command in the spec", "add one; see references/verification.md"))
        probe = False
    if integration:
        check_integration(repo, result, report, test_cmd, probe_cmd if probe else None, scenarios)
    elif probe:
        _report_probe(report, [_probe_one(repo, sid, result.space.dims, v, probe_cmd) for sid, v in scenarios])
    return report
