# Spec format

The spec is the canonical description of a decision space. It lives in the ```` ```yaml cad-spec ```` block of a planning document. Standalone `.yaml` and `.json` files work too, which is handy for `analyze` and for tests. JSON Schema: [spec.schema.json](spec.schema.json).

## Minimal spec

```yaml
feature: lead-capture-flow        # slug, used for branch names (alias: project)

dimensions:
  channel: [website, landing_page, checkout]
  pdf_delivery: [email, download, none]
  email_capture: [before_test, after_test, disabled]
  crm_sync: [hubspot, none]

constraints:
  - if: pdf_delivery == email
    requires: email_capture != disabled
  - if: channel == checkout
    excludes: email_capture == before_test
```

Everything else is optional.

## Full reference

```yaml
feature: lead-capture-flow
title: Lead capture flow            # default: humanized feature slug
summary: One paragraph for humans.

dimensions:
  channel:                          # long form
    label: Channel                  # default: humanized id
    summary: Where the test runs.
    options:
      - website
      - id: landing_page
        label: Landing page
        summary: Campaign pages built in the CMS.
      - checkout
  crm_sync:
    options: [hubspot, none]
    bundle: true                    # abstraction and options in one MR
  email_format:
    options: [html, text]
    applies_when: pdf_delivery == email   # conditional dimension
  pdf_delivery:
    options:
      - email
      - download
      - id: none                    # none / disabled / off are no-ops by default
      - id: manual
        noop: true                  # any other option can be a no-op too

constraints:
  - if: <expr>
    requires: <expr>                # when if holds, requires must hold
  - if: <expr>
    excludes: <expr>                # when if holds, excludes must not hold
  - never: <expr>                   # this combination is invalid
    id: no-kiosk                    # default: C1, C2, ...
    reason: Kiosks are out of scope this year.
  - "channel == kiosk"              # shorthand for never

interactions:                       # glue code where options meet
  - id: pdf-after-capture           # default: slug of title
    when: pdf_delivery == email and email_capture == after_test
    title: Send the PDF once the address is captured
    summary: The PDF job waits for the capture event.

generation:
  mode: exhaustive                  # exhaustive | pairwise | twise | selected
  strength: 3                       # twise only (pairwise is always 2)
  variants:                         # selected only: every applicable dimension
    - {channel: website, pdf_delivery: email, email_capture: before_test, crm_sync: hubspot}

limits:                             # defaults shown
  max_valid_variants: 32            # targeted variants above this need confirmation
  max_implementation_nodes: 20      # plan nodes above this need confirmation
  require_confirmation_above: 12    # new MRs in one revision above this need confirmation
  max_enumeration: 100000           # theoretical combinations above this are refused

stack:
  base_branch: main
  branch_prefix: lead-capture-flow  # default: feature
  layout: tree                      # tree | linear
  platform: auto                    # auto | gitlab | github | none

verify:                             # see verification.md
  test: node --test                 # runs on all branches merged together
  probe: node scripts/probe.ts      # prints the options it observes, e.g. "style=serious rendering=static"

plan:                               # repository-specific enrichment, keyed by node id
  base:
    title: Add lead-capture domain model
    components: [leads, config]
    files: [src/leads/model.ts, src/leads/config.ts]
    guidance: Reuse the existing FormConfig loader.
  opt.crm_sync.hubspot:
    risk: high
    complexity: M
    notes: HubSpot rate limits apply; batch writes.
```

Node ids: `base`, `dim.<dimension>`, `opt.<dimension>.<option>`, `ix.<interaction id>`. Enrichment fields: `title`, `purpose`, `scope`, `components`, `files`, `guidance`, `tests`, `acceptance`, `risk` (low, medium, high), `complexity` (S, M, L), `notes`.

## Expressions

```text
expr  := or
or    := and ("or" and)*
and   := not ("and" not)*
not   := "not" not | "(" expr ")" | atom
atom  := dim == option | dim != option
       | dim in [option, ...] | dim not in [option, ...]
```

Expressions are parsed by a small grammar, never evaluated as code. Unknown dimensions and options are errors with suggestions ("did you mean 'email'?").

A dimension that does not apply to a variant has no value. `==` and `in` are false for it, `!=` and `not in` are true.

## Conditional dimensions

`applies_when` makes a dimension exist only in some variants. It may only refer to dimensions listed above it. Variants where it does not apply are counted once, not once per option: adding `email_format: [html, text]` with `applies_when: pdf_delivery == email` grows the lead-capture example from 42 to 52 valid variants, where a plain dimension would double it to 84.

## Counting

```text
theoretical = collapsed + invalid + valid
```

- **theoretical**: product of all option counts.
- **collapsed**: combinations that differ only in a dimension that does not apply.
- **invalid**: distinct combinations that break at least one constraint.
- **valid**: the product variants.

Per constraint the tool also reports how many combinations it removes and how many only it removes. "Never fires" (removes nothing) and "redundant" (everything it removes is removed by others anyway) are findings.

## YAML subset

The parser has no dependencies and supports block mappings and sequences, single-line flow lists and maps, plain and quoted scalars, `|` and `>` block scalars, and comments. Plain scalars follow YAML 1.2: `true`, `false`, `null` and numbers are typed, while `none`, `off`, `yes` and `no` stay strings. Anchors, aliases, tags and multi-line flow collections are rejected with a line number.
