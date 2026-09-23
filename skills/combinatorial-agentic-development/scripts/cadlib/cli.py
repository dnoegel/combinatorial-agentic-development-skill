"""Command line interface: `python3 cad.py <command> ...`."""

import argparse
import json
import os
import subprocess
import sys

from . import brief as brief_mod
from . import plan as plan_mod
from . import restack as restack_mod
from . import document, engine, gitops, miniyaml, render as render_mod, stack as stack_mod
from . import spec as spec_mod
from . import verify as verify_mod

__version__ = "0.1.0"


def _fail(message, code=1):
    print(message, file=sys.stderr)
    return code


def _spec_from(path):
    raw = document.load_raw_spec(path)
    return spec_mod.load(raw)


def result_json(result, doc_path=None):
    spec, space, sc, plan, stack = result.spec, result.space, result.scenarios, result.plan, result.stack
    out = {
        "tool": "combinatorial-agentic-development",
        "version": __version__,
        "feature": spec.feature,
        "title": spec.title,
        "status": result.status,
        "mode": spec.mode,
        "strength": spec.strength,
        "confirmations": result.confirmations,
        "suggestions": result.suggestions,
        "findings": [{"level": f.level, "text": f.text} for f in result.findings],
    }
    if space is None:
        return out
    out["counts"] = {
        "theoretical": space.theoretical,
        "collapsed": space.collapsed,
        "invalid": space.invalid,
        "valid": len(space.valid),
    }
    out["dimensions"] = [
        {
            "id": d.id,
            "label": d.label,
            "applies_when": str(d.applies_when) if d.applies_when is not None else None,
            "options": [
                {"id": o.id, "label": o.label, "noop": o.noop, "dead": o.id in space.dead_options.get(d.id, [])}
                for o in d.options
            ],
        }
        for d in spec.dimensions.values()
    ]
    out["constraints"] = [
        {
            "id": r.constraint.id,
            "rule": r.constraint.text,
            "removes": r.removes_alone,
            "removes_only": r.removes_only,
            "finding": r.finding or None,
        }
        for r in space.reports
    ]
    if sc is None:
        return out
    out["counts"]["scenarios"] = len(sc.variants)
    out["coverage"] = {
        "strength": sc.strength or 2,
        "possible": sc.possible,
        "reachable": sc.coverable,
        "covered": sc.covered,
    }
    out["scenarios"] = [
        {"id": f"T{n:02d}", "variant": dict(zip(space.dims, v))} for n, v in enumerate(sc.variants, 1)
    ]
    if plan is None:
        return out
    out["counts"]["configurable"] = plan.configurable
    out["counts"]["nodes"] = len(plan.nodes)
    out["stack"] = {"layout": stack.layout, "base_branch": stack.base_branch, "lanes": stack.lanes, "waves": stack.waves}
    nodes = []
    for nid in stack.order:
        n = plan.by_id[nid]
        p = stack.placements[nid]
        nodes.append({
            "id": n.id,
            "kind": n.kind,
            "title": n.title,
            "purpose": n.purpose,
            "decisions": n.decisions,
            "scope": n.scope,
            "depends_on": n.depends_on,
            "components": n.components,
            "files": n.files,
            "guidance": n.guidance or render_mod.GUIDANCE[n.kind],
            "tests": n.tests,
            "scenarios": n.scenarios,
            "acceptance": n.acceptance,
            "risk": n.risk,
            "complexity": n.complexity,
            "branch": p.branch,
            "onto": p.parent_branch,
            "wave": p.wave + 1,
            "mr_title": n.title,
            "mr_description": render_mod.mr_description(spec, n, stack, plan, doc_path),
            "needs_enrichment": [k for k in ("components", "files") if not getattr(n, k)],
        })
    out["nodes"] = nodes
    return out


def cmd_new(args):
    spec_text = None
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            spec_text = fh.read()
        raw = miniyaml.loads(spec_text)
        feature = args.feature or (raw or {}).get("feature") or (raw or {}).get("project")
    else:
        feature = args.feature
    if not feature:
        return _fail("Pass --feature <slug> or --spec <file>.")
    document.create(args.path, feature, args.title, spec_text, args.intent or "")
    print(f"Created {args.path}. Edit the cad-spec block, then run: cad.py render {args.path}")
    return 0


def cmd_analyze(args):
    spec = _spec_from(args.source)
    result = engine.run(spec)
    if args.json:
        print(json.dumps(result_json(result, args.source if args.source.endswith(".md") else None), indent=2))
    else:
        print(render_mod.receipt(result))
        if args.variants and result.scenarios is not None:
            print("\nScenarios")
            dims = result.space.dims
            for n, v in enumerate(result.scenarios.variants, 1):
                print(f"  T{n:02d}  " + "  ".join(f"{d}={x if x is not None else 'n/a'}" for d, x in zip(dims, v)))
    return 1 if result.status == "error" else 0


def cmd_render(args):
    result, changed = document.render(args.doc, note=args.note, date=args.date)
    print(render_mod.receipt(result))
    if result.status == "error":
        print(f"\n{args.doc} was not changed.")
        return 1
    print(f"\n{args.doc} {'updated' if changed else 'refreshed (spec unchanged)'}.")
    return 0


def cmd_approve(args):
    result = document.approve(args.doc, args.by, date=args.date)
    print(f"Approved. {len(result.plan.nodes)} nodes are ready to implement in stack order.")
    return 0


def cmd_check(args):
    ok, message = document.check(args.doc)
    print(message)
    return 0 if ok else 1


def _detect_platform():
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False
        ).stdout.lower()
    except OSError:
        return "none"
    if "github" in url:
        return "github"
    if "gitlab" in url:
        return "gitlab"
    return "none"


def _repo_for(args):
    """The git repository the plan's branches live in, or None."""
    if getattr(args, "repo", None):
        return args.repo
    folder = os.path.dirname(os.path.abspath(args.doc))
    return gitops.toplevel(folder) if gitops.is_repo(folder) else None


def _load_plan(args):
    doc = document.read(args.doc)
    spec = spec_mod.load(miniyaml.loads(doc.spec_text))
    state = {k: dict(v or {}) for k, v in (doc.front.get("nodes") or {}).items()}
    result = engine.run(spec, state=state, followups=doc.front.get("followups") or [])
    if result.status == "error":
        raise document.DocError("The plan has errors. Run `cad.py render` for details.")
    repo = _repo_for(args)
    if repo:
        report = verify_mod.Report()
        verify_mod.check_state(repo, result.stack, report)
        for nid, status in report.nodes.items():
            recorded = state.setdefault(nid, {}).get("status", "planned")
            if recorded == "planned" or (status == "merged" and recorded != "merged"):
                state[nid]["status"] = status
    if repo:
        # re-place with the live state, so started branches keep their actual parents
        result = engine.run(spec, state=state, followups=doc.front.get("followups") or [])
    return doc, spec, state, result, repo


def cmd_stack(args):
    ok, message = document.check(args.doc)
    if not ok and not args.preview:
        return _fail(message + "\nUse --preview to see the steps without approval.")
    doc, spec, state, result, repo = _load_plan(args)
    remote = gitops.has_remote(repo) if repo else True
    platform = args.platform or spec.stack["platform"]
    if platform == "auto":
        platform = _detect_platform()
    desc_dir = args.write_descriptions or ".cad/mr"
    steps = stack_mod.steps(result.plan, result.stack, state, platform, desc_dir, remote=remote)
    if args.write_descriptions:
        os.makedirs(desc_dir, exist_ok=True)
        rel = os.path.relpath(args.doc)
        for nid in result.stack.order:
            p = result.stack.placements[nid]
            text = render_mod.mr_description(spec, result.plan.by_id[nid], result.stack, result.plan, rel)
            with open(os.path.join(desc_dir, p.branch.replace("/", "__") + ".md"), "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
    if args.json:
        print(json.dumps({"approved": ok, "platform": platform, "steps": steps}, indent=2))
        return 0
    header = "PREVIEW (plan not approved)" if not ok else "Dry run"
    print(f"# {header}: {spec.title}, {len(steps)} nodes, platform {platform}")
    print("# Nothing below has been executed. Local steps are safe to run after approval;")
    print("# push and MR commands need an explicit go from the engineer.")
    if not remote:
        print("# No remote configured: branches start from the local base branch; push and MR steps omitted.")
    elif platform == "none":
        print("# No GitHub or GitLab remote detected: MR commands omitted (use --platform).")
    if remote:
        print("\ngit fetch origin")
    wave = 0
    for n, s in enumerate(steps, 1):
        if s["wave"] != wave:
            wave = s["wave"]
            print(f"\n# ---- wave {wave + 1}: start after every earlier wave is merged into {result.stack.base_branch}")
        label = {"create": "", "restack": "RESTACK ", "keep": "up to date ", "done": "merged "}[s["action"]]
        print(f"\n# [{n}/{len(steps)}] {label}{s['node']}: {s['title']}  (onto {s['target']})")
        for c in s["commands"]:
            print(c)
    return 0


def cmd_verify(args):
    doc, spec, state, result, repo = _load_plan(args)
    if not repo:
        return _fail("verify needs a git repository (use --repo).")
    if args.only and args.only not in result.plan.by_id:
        return _fail(f"unknown node {args.only!r}")
    recorded = {k: (v or {}).get("status", "planned") for k, v in (doc.front.get("nodes") or {}).items()}
    report = verify_mod.run(
        repo, result, integration=args.integration, probe=args.probe, only=args.only, recorded=recorded
    )
    if args.json:
        print(json.dumps({
            "ok": report.ok,
            "nodes": report.nodes,
            "issues": [{"check": i.check, "node": i.node, "text": i.text, "fix": i.fix} for i in report.issues],
            "notes": report.notes,
            "warnings": report.warnings,
            "probe": report.probe,
        }, indent=2))
        return 0 if report.ok else 1
    counts = {}
    for status in report.nodes.values():
        counts[status] = counts.get(status, 0) + 1
    print(f"Verify {spec.feature}: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    for note in report.notes:
        print(f"  ok     {note}")
    for warning in report.warnings:
        print(f"  warn   {warning}")
    for issue in report.issues:
        where = f" [{issue.node}]" if issue.node else ""
        print(f"  FAIL   {issue.check}{where}: {issue.text}")
        if issue.fix:
            print(f"         fix: {issue.fix}")
    if not args.integration or not args.probe:
        skipped = [n for n, on in (("--integration", args.integration), ("--probe", args.probe)) if not on]
        print(f"  note   not run: {', '.join(skipped)}")
    result_text = "ok" if report.ok else f"{len(report.issues)} issue(s)"
    if report.warnings:
        result_text += f", {len(report.warnings)} warning(s)"
    print("Result: " + result_text)
    return 0 if report.ok else 1


def cmd_brief(args):
    ok, message = document.check(args.doc)
    if not ok and not args.preview:
        return _fail(message + "\nUse --preview to see a brief without approval.")
    doc, spec, state, result, repo = _load_plan(args)
    statuses = {k: v.get("status", "planned") for k, v in state.items()}
    node_id = args.node
    if args.next or not node_id:
        node_id = brief_mod.next_node(result.stack, statuses)
        if node_id is None:
            print("Every node has a branch. Run `cad.py verify --integration --probe`.")
            return 0
    if node_id not in result.plan.by_id:
        return _fail(f"unknown node {node_id!r}; nodes are: {', '.join(result.stack.order)}")
    start = gitops.base_ref(repo, spec.stack["base_branch"]) if repo else f"origin/{spec.stack['base_branch']}"
    print(brief_mod.brief(result, node_id, statuses, os.path.relpath(args.doc), start), end="")
    return 0


def cmd_restack(args):
    doc, spec, state, result, repo = _load_plan(args)
    if not repo:
        return _fail("restack needs a git repository (use --repo).")
    if args.node and args.node not in result.plan.by_id:
        return _fail(f"unknown node {args.node!r}")
    steps = restack_mod.plan(repo, result.stack, args.node)
    if not steps:
        print("Nothing to restack: every branch contains its parent's tip.")
        return 0
    print(f"# Restack {len(steps)} branch(es), parents first. Local only; nothing is pushed.")
    for step in steps:
        print(f"\n# {step.node}: {step.branch} onto {step.onto}")
        for command in step.commands:
            print(command)
    if gitops.has_remote(repo):
        print("\n# Open MRs need a force-push afterwards (git push --force-with-lease). Only when the engineer asks.")
    if args.execute:
        ok, message = restack_mod.execute(repo, steps)
        print("\n" + message)
        return 0 if ok else 1
    return 0


def cmd_impact(args):
    doc, spec, state, result, repo = _load_plan(args)
    plan, stack = result.plan, result.stack
    if args.node not in plan.by_id:
        return _fail(f"unknown node {args.node!r}; nodes are: {', '.join(stack.order)}")
    node = plan.by_id[args.node]
    status = state.get(args.node, {}).get("status", "planned")
    code_deps = plan_mod.dependents(plan, args.node)
    branch_deps = [n for n in restack_mod.subtree(stack, args.node) if n != args.node]
    scenario_ids = sorted({sid for n in plan.nodes if n.id in {args.node, *code_deps} for sid in n.scenarios})
    if args.json:
        print(json.dumps({
            "node": args.node, "status": status,
            "code_dependents": code_deps, "stack_descendants": branch_deps,
            "scenarios": scenario_ids,
        }, indent=2))
        return 0

    def row(nid):
        st = state.get(nid, {})
        mr = f" {st['mr']}" if st.get("mr") else ""
        return f"  {nid:<40}{st.get('status', 'planned')}{mr}"

    print(f"Impact of changing `{args.node}` ({node.title}), currently {status}")
    print(f"\nCode that builds on it ({len(code_deps)}): must still work, adapt it if the interface changes")
    for nid in code_deps:
        print(row(nid))
    print(f"\nBranches stacked on it ({len(branch_deps)}): must be restacked when its branch changes")
    for nid in branch_deps:
        print(row(nid))
    print(f"\nScenarios to re-check: {len(scenario_ids)} of {len(result.scenarios.variants)}")
    print("\nHow to change it")
    if status == "merged":
        print("  It is merged: never rewrite it. Change the spec if the contract changes (render plans a")
        print("  follow-up node), or add the fix as a normal commit on a new branch from the base branch.")
    elif status == "planned":
        print("  No branch yet: edit the plan or the spec; nothing to restack.")
    else:
        print(f"  Amend `{stack.placements[args.node].branch}`, then:")
        print(f"    cad.py restack {args.doc} {args.node}")
    print(f"  Then: cad.py verify {args.doc} --integration --probe --only {args.node}")
    return 0


def cmd_mark(args):
    repo = _repo_for(args)
    if repo:
        doc = document.read(args.doc)
        base = spec_mod.load(miniyaml.loads(doc.spec_text)).stack["base_branch"]
        current = gitops.current_branch(repo)
        if current and current != base:
            return _fail(
                f"You are on `{current}`. Progress is recorded on `{base}` only, so feature branches "
                f"never carry plan edits. Switch to `{base}` first."
            )
    document.mark(
        args.doc, args.node, args.status, mr=args.mr, restacked=args.restacked, updated=args.updated, date=args.date
    )
    print(f"{args.node}: {args.status}" + (f" ({args.mr})" if args.mr else ""))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cad.py",
        description="Combinatorial Agentic Development: plan the whole decision space, then build it as stacked MRs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a planning document")
    p.add_argument("path")
    p.add_argument("--feature", help="feature slug, e.g. lead-capture-flow")
    p.add_argument("--title")
    p.add_argument("--spec", help="start from an existing YAML spec file")
    p.add_argument("--intent", help="one paragraph on what the feature is for")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("analyze", help="count, validate and plan without writing anything")
    p.add_argument("source", help="planning document (.md), YAML or JSON spec")
    p.add_argument("--json", action="store_true")
    p.add_argument("--variants", action="store_true", help="also list the targeted variants")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("render", help="regenerate the plan inside a planning document")
    p.add_argument("doc")
    p.add_argument("--note", help="changelog note, e.g. what the engineer asked for")
    p.add_argument("--date", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("approve", help="record sign-off, bound to the current spec")
    p.add_argument("doc")
    p.add_argument("--by", required=True)
    p.add_argument("--date", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("check", help="exit 0 only if the current spec is approved")
    p.add_argument("doc")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("stack", help="print the dry-run branch and MR steps")
    p.add_argument("doc")
    p.add_argument("--repo")
    p.add_argument("--platform", choices=spec_mod.PLATFORMS)
    p.add_argument("--preview", action="store_true", help="show steps even if the plan is not approved")
    p.add_argument("--write-descriptions", metavar="DIR", help="write MR descriptions as Markdown files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stack)

    p = sub.add_parser("verify", help="compare the plan with git: stale branches, integration, probe")
    p.add_argument("doc")
    p.add_argument("--repo", help="git repository with the branches (default: the one containing the doc)")
    p.add_argument("--integration", action="store_true", help="merge all branches in a temporary worktree and run verify.test")
    p.add_argument("--probe", action="store_true", help="run verify.probe for every targeted variant")
    p.add_argument("--only", metavar="NODE", help="limit the probe to scenarios affected by NODE and its dependents")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("restack", help="rebase stale branches and everything built on them, parents first")
    p.add_argument("doc")
    p.add_argument("node", nargs="?", help="restack this node's subtree (default: every stale subtree)")
    p.add_argument("--repo")
    p.add_argument("--execute", action="store_true", help="run the rebases locally (stops at the first conflict)")
    p.set_defaults(func=cmd_restack)

    p = sub.add_parser("impact", help="what a change to a node affects")
    p.add_argument("doc")
    p.add_argument("node")
    p.add_argument("--repo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("brief", help="self-contained instructions for one node")
    p.add_argument("doc")
    p.add_argument("node", nargs="?")
    p.add_argument("--next", action="store_true", help="the next node without a branch")
    p.add_argument("--repo")
    p.add_argument("--preview", action="store_true", help="allow a brief before approval")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("mark", help="record progress for a node")
    p.add_argument("--repo")
    p.add_argument("doc")
    p.add_argument("node")
    p.add_argument("--status", required=True, choices=document.STATUSES)
    p.add_argument("--mr", help="MR or PR reference, e.g. !42 or #42")
    p.add_argument("--restacked", action="store_true", help="the branch was rebased onto its new parent")
    p.add_argument("--updated", action="store_true", help="the branch was amended to its changed contract")
    p.add_argument("--date", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_mark)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except spec_mod.SpecError as exc:
        lines = ["The spec has problems:"] + [f"  - {e}" for e in exc.errors]
        if exc.warnings:
            lines += ["Warnings:"] + [f"  - {w}" for w in exc.warnings]
        return _fail("\n".join(lines))
    except (document.DocError, miniyaml.YamlError, gitops.GitError, OSError) as exc:
        return _fail(str(exc))
