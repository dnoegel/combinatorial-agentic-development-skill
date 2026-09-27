# Delivery: toggles or open branches

Every decision is delivered in one of two ways.

| Strategy | What happens | Fits when |
|---|---|---|
| `toggle` | An abstraction lands in the base branch, every option merges behind it, and configuration picks one | several options must run side by side in production (per customer, A/B test, gradual rollout), or the options are small |
| `branch` | Each option is a complete implementation on its own branch, kept current but not merged; there is no switch in the base branch | exactly one option will win, the decision is still open, and each option is a large change (hundreds of lines, several layers such as API, backend and frontend) |

Toggles are cheap while options are small and become a burden when two large implementations have to live side by side in the base branch until someone decides. Open branches keep the base branch clean and cost rebases while they wait.

## How the strategy is chosen

The agent estimates two facts per decision, from the conversation and the repository, and writes them into the spec. The tool applies a fixed rule.

```yaml
dimensions:
  checkout:
    options: [one_page, multi_step]
    coexist: false   # must several options run side by side in production?
    size: large      # small | large: one option's change, judged from files and layers
    # delivery: branch   # optional override of the rule
```

| `coexist` | `size` | Strategy |
|---|---|---|
| true | any | `toggle` |
| false or unset | large | `branch` |
| false or unset | small or unset | `toggle` |

The planning document shows the strategy and the reason per decision. Read it back with the other spec changes; the engineer can override it with `delivery`.

## What changes for open branches

- **Plan:** no abstraction node. Each option node (`opt.checkout.one_page`) builds on `base` and contains the whole option. Nodes that build on an open branch, such as an interaction with it, stay open too. Work that merges is never stacked on an open branch.
- **Stack:** open branches are marked "stays open" in the table, dashed in the diagram, and `stack` and `brief` say not to merge them. `restack` keeps them current while the base branch moves.
- **Verify:** alternatives of one decision are allowed to conflict with each other. `verify --integration` therefore merges the shared branches once and then composes every test scenario on its own, adding only the open branches that scenario selects, and runs `verify.test` and the probe per scenario. Scenarios whose open branches do not exist yet are listed and skipped.
- **Looking at a variant:** `cad.py compose <doc> checkout=one_page payment_ui=embedded upsell=enabled` (or `T03`, or `--all`) creates `<feature>/variant/<options>`: the base branch plus every shared branch plus the open branches of that variant. Toggles still need their configuration, which `compose` prints. The variant branch is derived: recomposing replaces it, so never commit on it.

## When product decides

Write the decision into the spec and render:

```yaml
  checkout:
    options: [one_page, multi_step]
    size: large
    decided: one_page
```

- **Open branches:** the winner stops being open and merges like any other node, together with the nodes that waited for it. `render` lists the branches of the losing options; close them.
- **Toggles:** if code for the losing options already exists, the plan gets a cleanup node (`cleanup.theme`) that removes it, and the switch if it only served this decision.
- The decided dimension no longer multiplies the decision space, so counts, the test matrix and the tree shrink with every decision.
