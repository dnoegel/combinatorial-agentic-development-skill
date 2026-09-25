# Verification

Green tests on every branch do not prove that the product works. In a trial run, fourteen branches each passed their own tests while no option was ever wired into the product: the plugin loader looked in the wrong directory and the composition root was a placeholder. Every variant rendered the same page.

`cad.py verify` compares the plan with what git and the product actually show.

```bash
cad.py verify docs/variants/<feature>.md                          # git state only, instant
cad.py verify docs/variants/<feature>.md --integration            # plus merge all branches and run verify.test
cad.py verify docs/variants/<feature>.md --integration --probe    # plus check every variant's behavior
```

It never changes branches or the working tree. Integration runs in a temporary `git worktree` that is removed afterwards. The only thing it writes is a metadata ref per branch under `refs/cad/base/` (the fork point used by `restack`).

`verify.test` and `verify.probe` are shell commands from the spec, and `verify` runs them. Treat a spec change like a code change: review it before you run `verify` on someone else's branch.

## State

For every node: does the branch exist, is it merged into the base branch, and does it contain its parent's current tip? A parent that received commits after its children branched makes them **stale**. `verify` lists the stale branch together with everything built on it, and `cad.py restack` fixes the whole cascade.

## Integration

All existing branches are merged in stack order into a throwaway worktree based on the base branch. A merge conflict fails the check and names the files: two nodes on parallel lanes edited the same file, which the plan should have prevented (see "Shared files" below). Then `verify.test` runs on the merged result.

## Probe

The probe is a command you add to the spec:

```yaml
verify:
  test: node --test
  probe: node scripts/probe.ts
```

For each targeted variant, `verify --probe` runs it with the variant as JSON on stdin and in `CAD_VARIANT`, for example `{"style": "serious", "rendering": "static", "guestbook": "none", ...}`. The probe builds or renders the product for that configuration and prints what it **observes**, as `dimension=option` tokens:

```text
style=serious rendering=static guestbook=none imprint=enabled start_page=company
```

Every selected option must be observed, no-op options included, and nothing else. Missing tokens mean an option exists in the code but does not reach the product. Unexpected tokens mean an option leaks into variants that did not choose it.

How to make options observable, cheaply:

- **Web pages:** a `data-cad="style=serious"` attribute on the element each option produces; the probe renders the pages and collects the attributes.
- **APIs and services:** a debug endpoint or header that reports the active strategy ids, or the registered handler names.
- **Libraries and CLIs:** a `--describe` flag or a function that returns the ids of the composed implementations.

Observe the result, never the configuration: a probe that echoes its input proves nothing. The probe belongs to the `base` node, so it exists before any option is implemented.

## Shared files

Parallel lanes that edit the same file conflict at integration. The plan warns when two parallel nodes list the same file in `plan.<node>.files`. The usual fix is structural: the `base` node owns a composition root that discovers option modules at runtime (a directory scan, an entry-point registry, dependency injection), so option branches only add files.

## Delegating to other models

Cheaper models are fine for single nodes when the instructions are exact and the result is checked:

1. `cad.py brief <doc> --next` prints a self-contained brief for the next node: branch command, scope, owned files, files not to touch, acceptance criteria, commit format, and the rule to stop and report instead of improvising.
2. Hand one brief (or one lane of briefs) to the implementer.
3. Run `cad.py verify` after every lane, and `--integration --probe` before calling the stack done.
4. Report the stack as done when `verify` passes, whatever the implementer's summary says.
