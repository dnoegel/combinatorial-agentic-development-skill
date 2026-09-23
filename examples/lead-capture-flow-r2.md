---
cad: 1
feature: lead-capture-flow
revision: 2
status: draft
spec_hash: f076cfb87ea3
counts:
  theoretical: 108
  valid: 52
  scenarios: 52
  nodes: 18
nodes:
  base:
    branch: lead-capture-flow/base
    onto: main
    status: merged
    mr: "!4"
  dim.email_capture:
    branch: lead-capture-flow/email-capture
    onto: lead-capture-flow/base
    status: merged
    mr: "!5"
  opt.email_capture.before_test:
    branch: lead-capture-flow/email-capture-before-test
    onto: lead-capture-flow/email-capture
    status: planned
  opt.email_capture.after_test:
    branch: lead-capture-flow/email-capture-after-test
    onto: lead-capture-flow/email-capture
    status: mr-open
    mr: "!7"
  base.r2:
    branch: lead-capture-flow/base-r2
    onto: lead-capture-flow/base
    status: planned
  dim.channel:
    branch: lead-capture-flow/channel
    onto: lead-capture-flow/base-r2
    status: planned
  dim.pdf_delivery:
    branch: lead-capture-flow/pdf-delivery
    onto: lead-capture-flow/base-r2
    status: planned
  dim.crm_sync:
    branch: lead-capture-flow/crm-sync
    onto: lead-capture-flow/base-r2
    status: planned
  opt.channel.website:
    branch: lead-capture-flow/channel-website
    onto: lead-capture-flow/channel
    status: planned
  opt.channel.landing_page:
    branch: lead-capture-flow/channel-landing-page
    onto: lead-capture-flow/channel
    status: planned
  opt.channel.checkout:
    branch: lead-capture-flow/channel-checkout
    onto: lead-capture-flow/channel
    status: planned
  opt.pdf_delivery.email:
    branch: lead-capture-flow/pdf-delivery-email
    onto: lead-capture-flow/pdf-delivery
    status: planned
  dim.email_format:
    branch: lead-capture-flow/email-format
    onto: lead-capture-flow/pdf-delivery-email
    status: planned
  opt.pdf_delivery.download:
    branch: lead-capture-flow/pdf-delivery-download
    onto: lead-capture-flow/pdf-delivery
    status: planned
  opt.crm_sync.hubspot:
    branch: lead-capture-flow/crm-sync-hubspot
    onto: lead-capture-flow/crm-sync
    status: planned
  opt.email_format.html:
    branch: lead-capture-flow/email-format-html
    onto: lead-capture-flow/email-format
    status: planned
  opt.email_format.text:
    branch: lead-capture-flow/email-format-text
    onto: lead-capture-flow/email-format
    status: planned
  ix.pdf-after-capture:
    branch: lead-capture-flow/pdf-after-capture
    onto: main
    status: planned
followups:
  - id: base.r2
    of: base
    revision: 2
    changes:
      - "+ options: email_format: html, text"
---

# Lead capture flow

_Why choose a product path when you can implement the whole decision space?_

## Intent

Visitors take a short self-assessment test and we turn them into leads. Nobody has decided yet where the flow lives, how the PDF report is delivered, when we ask for the email address, or whether leads go to HubSpot. Instead of waiting for a decision, we plan all of it.

## Review notes

- `crm_sync = hubspot` with `email_capture = disabled` creates HubSpot contacts without an email
  address. Is that useful, or should it be a constraint? (open question)
- `website` and `landing_page` probably share one flow and differ in layout. If so,
  `bundle: true` on `channel` saves two MRs.

## Spec

The canonical decision space. Edit it directly or describe the change in conversation; either way the plan below is regenerated from it.

```yaml cad-spec
# Revision 2 of the lead-capture example: emails can be HTML or plain text,
# and sending the PDF after capture needs a little glue code.
project: lead-capture-flow

dimensions:
  channel:
    - website
    - landing_page
    - checkout

  pdf_delivery:
    - email
    - download
    - none

  email_capture:
    - before_test
    - after_test
    - disabled

  crm_sync:
    - hubspot
    - none

  email_format:
    options: [html, text]
    applies_when: pdf_delivery == email

constraints:
  - if: pdf_delivery == email
    requires: email_capture != disabled

  - if: channel == checkout
    excludes: email_capture == before_test

interactions:
  - id: pdf-after-capture
    when: pdf_delivery == email and email_capture == after_test
    title: Send the PDF once the address is captured

generation:
  mode: exhaustive

limits:
  max_valid_variants: 20
  max_implementation_nodes: 12
  require_confirmation_above: 8
```

<!-- cad:generated:start (edit the spec above and run `cad.py render`; changes below this line are overwritten) -->

## Decision space

| | Count |
|---|---:|
| Theoretical combinations (3 × 3 × 3 × 2 × 2) | 108 |
| Collapsed, a decision does not apply | 36 |
| Removed by constraints | 20 |
| **Valid product variants** | **52** |
| Test scenarios (exhaustive) | 52 |
| Implementation nodes (MRs) | 18 |

**Plan status:** Draft. Waiting for sign-off.

**Needs confirmation:**
- 52 targeted variants exceed max_valid_variants (20).
- 18 implementation nodes exceed max_implementation_nodes (12).

Options: proceed as planned, switch the test matrix to pairwise, add a constraint that rules out combinations nobody wants, bundle small dimensions (`bundle: true`) into one MR each, raise the limits in the spec on purpose.

### Decision tree

```mermaid
flowchart LR
  n0(["Channel"])
  n1(["PDF delivery"])
  n2(["Email capture"])
  n3(["CRM sync"])
  n4(["Email format"])
  n5(["Email capture"])
  n6(["CRM sync"])
  n7(["PDF delivery"])
  n8(["Email capture"])
  n9(["Email capture"])
  done(["52 valid variants"])
  n0 -->|"website / landing_page"| n1
  n0 -->|"checkout"| n7
  n1 -->|"email"| n2
  n1 -->|"download / none"| n5
  n2 -->|"before_test / after_test"| n3
  n3 -->|"hubspot / none"| n4
  n4 -->|"html / text"| done
  n5 -->|"before_test / after_test / disabled"| n6
  n6 -->|"hubspot / none"| done
  n7 -->|"email"| n8
  n7 -->|"download / none"| n9
  n8 -->|"after_test"| n3
  n9 -->|"after_test / disabled"| n6
  classDef valid fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
  class done valid
```

Every path from left to right is one valid variant. Branches with identical continuations are merged, so all 52 variants fit in one small diagram.

### Dimensions

| Dimension | Options | Applies when |
|---|---|---|
| Channel (`channel`) | `website`, `landing_page`, `checkout` | always |
| PDF delivery (`pdf_delivery`) | `email`, `download`, `none` (no-op) | always |
| Email capture (`email_capture`) | `before_test`, `after_test`, `disabled` (no-op) | always |
| CRM sync (`crm_sync`) | `hubspot`, `none` (no-op) | always |
| Email format (`email_format`) | `html`, `text` | `pdf_delivery == email` |

### Constraints

| ID | Rule | Removes | Only this rule | Note |
|---|---|---:|---:|---|
| C1 | `if pdf_delivery == email requires email_capture != disabled` | 12 | 12 |  |
| C2 | `if channel == checkout excludes email_capture == before_test` | 8 | 8 |  |

<details><summary>Constraint map</summary>

```mermaid
flowchart LR
  subgraph d_channel["Channel"]
    direction TB
    o_channel__website["website"]
    o_channel__landing_page["landing_page"]
    o_channel__checkout["checkout"]
  end
  subgraph d_pdf_delivery["PDF delivery"]
    direction TB
    o_pdf_delivery__email["email"]
    o_pdf_delivery__download["download"]
    o_pdf_delivery__none["none"]
  end
  subgraph d_email_capture["Email capture"]
    direction TB
    o_email_capture__before_test["before_test"]
    o_email_capture__after_test["after_test"]
    o_email_capture__disabled["disabled"]
  end
  subgraph d_crm_sync["CRM sync"]
    direction TB
    o_crm_sync__hubspot["hubspot"]
    o_crm_sync__none["none"]
  end
  subgraph d_email_format["Email format"]
    direction TB
    o_email_format__html["html"]
    o_email_format__text["text"]
  end
  o_pdf_delivery__email --x|"C1 excludes"| o_email_capture__disabled
  o_channel__checkout --x|"C2 excludes"| o_email_capture__before_test
  o_pdf_delivery__email -.->|"enables"| d_email_format
  classDef noop stroke-dasharray:4 3
  class o_pdf_delivery__none,o_email_capture__disabled,o_crm_sync__none noop
```

</details>

### Findings

- **info**: `ix.pdf-after-capture` starts from main in wave 2 after `opt.pdf_delivery.email`, `opt.email_capture.after_test` merged (dependencies sit on separate lanes).
- **warning**: No `verify.probe` configured: nothing proves that each option actually changes the product. Green tests per branch are not enough (see references/verification.md).

## Implementation plan

18 nodes: 1 foundation, 5 abstractions, 10 options, 1 interaction, 1 follow-up. Work is planned per option, so 52 of 52 valid variants are configurable from 15 option and abstraction MRs.

### MR stack

```mermaid
flowchart TD
  main(["main"])
  s_base["Add lead capture flow foundation<br/><small>base</small>"]
  s_dim_email_capture["Add email capture abstraction<br/><small>dim.email_capture</small>"]
  s_opt_email_capture_before_test["Email capture: before test<br/><small>opt.email_capture.before_test</small>"]
  s_opt_email_capture_after_test["Email capture: after test<br/><small>opt.email_capture.after_test</small>"]
  s_base_r2["Revise lead capture flow foundation for plan revision 2<br/><small>base.r2</small>"]
  s_dim_channel["Add channel abstraction<br/><small>dim.channel</small>"]
  s_dim_pdf_delivery["Add PDF delivery abstraction<br/><small>dim.pdf_delivery</small>"]
  s_dim_crm_sync["Add CRM sync abstraction<br/><small>dim.crm_sync</small>"]
  s_opt_channel_website["Channel: website<br/><small>opt.channel.website</small>"]
  s_opt_channel_landing_page["Channel: landing page<br/><small>opt.channel.landing_page</small>"]
  s_opt_channel_checkout["Channel: checkout<br/><small>opt.channel.checkout</small>"]
  s_opt_pdf_delivery_email["PDF delivery: email<br/><small>opt.pdf_delivery.email</small>"]
  s_dim_email_format["Add email format abstraction<br/><small>dim.email_format</small>"]
  s_opt_pdf_delivery_download["PDF delivery: download<br/><small>opt.pdf_delivery.download</small>"]
  s_opt_crm_sync_hubspot["CRM sync: hubspot<br/><small>opt.crm_sync.hubspot</small>"]
  s_opt_email_format_html["Email format: HTML<br/><small>opt.email_format.html</small>"]
  s_opt_email_format_text["Email format: text<br/><small>opt.email_format.text</small>"]
  s_ix_pdf_after_capture["Send the PDF once the address is captured<br/><small>ix.pdf-after-capture</small>"]
  main --> s_base
  s_base --> s_dim_email_capture
  s_dim_email_capture --> s_opt_email_capture_before_test
  s_dim_email_capture --> s_opt_email_capture_after_test
  s_base --> s_base_r2
  s_base_r2 --> s_dim_channel
  s_base_r2 --> s_dim_pdf_delivery
  s_base_r2 --> s_dim_crm_sync
  s_dim_channel --> s_opt_channel_website
  s_dim_channel --> s_opt_channel_landing_page
  s_dim_channel --> s_opt_channel_checkout
  s_dim_pdf_delivery --> s_opt_pdf_delivery_email
  s_opt_pdf_delivery_email --> s_dim_email_format
  s_dim_pdf_delivery --> s_opt_pdf_delivery_download
  s_dim_crm_sync --> s_opt_crm_sync_hubspot
  s_dim_email_format --> s_opt_email_format_html
  s_dim_email_format --> s_opt_email_format_text
  main -.->|"wave 2, after opt.pdf_delivery.email, opt.email_capture.after_test"| s_ix_pdf_after_capture
  classDef merged fill:#e8f5e9,stroke:#2e7d32
  class s_base,s_dim_email_capture merged
  classDef mr_open fill:#e3f2fd,stroke:#1565c0
  class s_opt_email_capture_after_test mr_open
```

| # | Node | Branch | Onto | Status |
|---:|---|---|---|---|
| 1 | `base` | `lead-capture-flow/base` | `main` | merged !4 |
| 2 | `dim.email_capture` | `lead-capture-flow/email-capture` | `main` | merged !5 |
| 3 | `opt.email_capture.before_test` | `lead-capture-flow/email-capture-before-test` | `main` | planned |
| 4 | `opt.email_capture.after_test` | `lead-capture-flow/email-capture-after-test` | `main` | mr-open !7 |
| 5 | `base.r2` | `lead-capture-flow/base-r2` | `main` | planned |
| 6 | `dim.channel` | `lead-capture-flow/channel` | `lead-capture-flow/base-r2` | planned |
| 7 | `dim.pdf_delivery` | `lead-capture-flow/pdf-delivery` | `lead-capture-flow/base-r2` | planned |
| 8 | `dim.crm_sync` | `lead-capture-flow/crm-sync` | `lead-capture-flow/base-r2` | planned |
| 9 | `opt.channel.website` | `lead-capture-flow/channel-website` | `lead-capture-flow/channel` | planned |
| 10 | `opt.channel.landing_page` | `lead-capture-flow/channel-landing-page` | `lead-capture-flow/channel` | planned |
| 11 | `opt.channel.checkout` | `lead-capture-flow/channel-checkout` | `lead-capture-flow/channel` | planned |
| 12 | `opt.pdf_delivery.email` | `lead-capture-flow/pdf-delivery-email` | `lead-capture-flow/pdf-delivery` | planned |
| 13 | `dim.email_format` | `lead-capture-flow/email-format` | `lead-capture-flow/pdf-delivery-email` | planned |
| 14 | `opt.pdf_delivery.download` | `lead-capture-flow/pdf-delivery-download` | `lead-capture-flow/pdf-delivery` | planned |
| 15 | `opt.crm_sync.hubspot` | `lead-capture-flow/crm-sync-hubspot` | `lead-capture-flow/crm-sync` | planned |
| 16 | `opt.email_format.html` | `lead-capture-flow/email-format-html` | `lead-capture-flow/email-format` | planned |
| 17 | `opt.email_format.text` | `lead-capture-flow/email-format-text` | `lead-capture-flow/email-format` | planned |
| 18 | `ix.pdf-after-capture` | `lead-capture-flow/pdf-after-capture` | `main` (wave 2) | planned |

Layout: tree. Merge order is the table order. After a parent merges, retarget its children to `main` (see `cad.py stack`).

### Nodes

### 1. Add lead capture flow foundation

Shared domain model, configuration entry point and wiring that every variant builds on.

| | |
|---|---|
| Node | `base` (base) |
| Decisions | `shared by all variants` |
| Scope | Domain types, one configuration object with a key per dimension, validation of that configuration against the constraints, and the composition root that picks implementations. |
| Depends on | nothing (starts the stack) |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / M |
| Branch | `lead-capture-flow/base` onto `main` |
| Status | merged (!4) |

**Guidance.** Prefer one configuration object over scattered flags. Validate it at startup with the same rules as the constraint table, so an invalid combination fails fast and loudly. Own the composition root here and let it discover option modules at runtime, so parallel option branches never touch the same file. Add the probe now: it proves later that every option is wired in.

**Tests**
- Unit tests for the domain model.
- Configuration tests: every combination removed by a constraint is rejected with a readable message.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Configuration accepts the 52 valid variants and rejects the 20 invalid combinations.
- [ ] Existing behavior is unchanged while no variation point is wired in.
- [ ] The composition root discovers option modules at runtime, so option branches never edit shared files.
- [ ] Every active option leaves a marker in the output (for example `data-cad="style=serious"`), and the `verify.probe` command prints the markers it observes as `dimension=option`.

<details><summary>MR description</summary>

```markdown
## Summary
- Shared domain model, configuration entry point and wiring that every variant builds on.
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `base`.

## Stack
- Based on `main`.
- Unblocks `lead-capture-flow/email-capture`, `lead-capture-flow/base-r2`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Medium: Touches wiring shared by every variant.
```

</details>

### 2. Add email capture abstraction

Variation point for email capture: one interface and one configuration key `email_capture`, so every option plugs in without touching callers.

| | |
|---|---|
| Node | `dim.email_capture` (dimension) |
| Decisions | `email_capture in [before_test, after_test, disabled]` |
| Scope | Interface for email capture, registration by option id, and the no-op implementation for `disabled`. |
| Depends on | `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / M |
| Branch | `lead-capture-flow/email-capture` onto `main` (parent `lead-capture-flow/base` is merged) |
| Status | merged (!5) |

**Guidance.** Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. A no-op option is a real implementation of the interface; keep if-statements out of the call sites.

**Tests**
- Contract test suite that every implementation of the interface must pass.
- The no-op option `disabled` passes the contract suite.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Selecting any of before_test, after_test, disabled through configuration works without code changes in callers.
- [ ] The selected `email_capture` option is observable in the output, no-op options included (for example `email_capture=disabled`).

<details><summary>MR description</summary>

```markdown
## Summary
- Variation point for email capture: one interface and one configuration key `email_capture`, so every option plugs in without touching callers.
- Decisions: `email_capture in [before_test, after_test, disabled]`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `dim.email_capture`.

## Stack
- Based on `lead-capture-flow/base` (Add lead capture flow foundation). Merge that first.
- Unblocks `lead-capture-flow/email-capture-before-test`, `lead-capture-flow/email-capture-after-test`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Medium: Every option of this dimension builds on the interface introduced here.
```

</details>

### 3. Email capture: before test

Implement `email_capture = before_test` behind the email capture abstraction.

| | |
|---|---|
| Node | `opt.email_capture.before_test` (option) |
| Decisions | `email_capture = before_test` |
| Scope | One implementation of the email capture interface, registered as `before_test`. No changes to other options. |
| Depends on | `dim.email_capture` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / S |
| Branch | `lead-capture-flow/email-capture-before-test` onto `main` (parent `lead-capture-flow/email-capture` is merged) |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `before_test` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T01, T02, T03, T04, T09, T10, T15, T16 and 8 more

**Acceptance criteria**
- [ ] All 16 test scenarios with email_capture = before_test pass.
- [ ] The probe observes `email_capture=before_test` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `email_capture = before_test` behind the email capture abstraction.
- Decisions: `email_capture = before_test`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.email_capture.before_test`.

## Stack
- Based on `lead-capture-flow/email-capture` (Add email capture abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T09, T10, T15, T16 and 8 more.

## Risks
- Medium: Isolated to one option behind an interface.
```

</details>

### 4. Email capture: after test

Implement `email_capture = after_test` behind the email capture abstraction.

| | |
|---|---|
| Node | `opt.email_capture.after_test` (option) |
| Decisions | `email_capture = after_test` |
| Scope | One implementation of the email capture interface, registered as `after_test`. No changes to other options. |
| Depends on | `dim.email_capture` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / S |
| Branch | `lead-capture-flow/email-capture-after-test` onto `main` (parent `lead-capture-flow/email-capture` is merged) |
| Status | mr-open (!7) |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `after_test` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T05, T06, T07, T08, T11, T12, T17, T18 and 16 more

**Acceptance criteria**
- [ ] All 24 test scenarios with email_capture = after_test pass.
- [ ] The probe observes `email_capture=after_test` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `email_capture = after_test` behind the email capture abstraction.
- Decisions: `email_capture = after_test`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.email_capture.after_test`.

## Stack
- Based on `lead-capture-flow/email-capture` (Add email capture abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T05, T06, T07, T08, T11, T12, T17, T18 and 16 more.

## Risks
- Medium: Isolated to one option behind an interface.
```

</details>

### 5. Revise lead capture flow foundation for plan revision 2

`base` is already merged and its contract changed in plan revision 2. This node brings it in line without rewriting merged history.

| | |
|---|---|
| Node | `base.r2` (followup) |
| Decisions | `shared by all variants` |
| Scope | Only the listed contract changes. No unrelated refactoring. |
| Depends on | `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / S |
| Branch | `lead-capture-flow/base-r2` onto `main` (parent `lead-capture-flow/base` is merged) |
| Status | planned |

**Guidance.** Change only what the contract changes list. The original node is merged, so this is a normal new commit on top of the base branch; never rewrite merged history.

**Contract changes**
- `+ options: email_format: html, text`

**Tests**
- Unit tests for the domain model.
- Configuration tests: every combination removed by a constraint is rejected with a readable message.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Contract change done: + options: email_format: html, text
- [ ] Everything `base` promised before still holds.

<details><summary>MR description</summary>

```markdown
## Summary
- `base` is already merged and its contract changed in plan revision 2. This node brings it in line without rewriting merged history.
- Decisions: `shared by all variants`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `base.r2`.

## Stack
- Based on `lead-capture-flow/base` (Add lead capture flow foundation). Merge that first.
- Unblocks `lead-capture-flow/channel`, `lead-capture-flow/pdf-delivery`, `lead-capture-flow/crm-sync`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Medium: Changes code that is already merged and that other nodes build on.
```

</details>

### 6. Add channel abstraction

Variation point for channel: one interface and one configuration key `channel`, so every option plugs in without touching callers.

| | |
|---|---|
| Node | `dim.channel` (dimension) |
| Decisions | `channel in [website, landing_page, checkout]` |
| Scope | Interface for channel, registration by option id. |
| Depends on | `base.r2` |
| Why | `base.r2`: builds on the updated `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / M |
| Branch | `lead-capture-flow/channel` onto `lead-capture-flow/base-r2` |
| Status | planned |

**Guidance.** Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. A no-op option is a real implementation of the interface; keep if-statements out of the call sites.

**Tests**
- Contract test suite that every implementation of the interface must pass.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Selecting any of website, landing_page, checkout through configuration works without code changes in callers.
- [ ] The selected `channel` option is observable in the output, no-op options included (for example `channel=checkout`).

<details><summary>MR description</summary>

```markdown
## Summary
- Variation point for channel: one interface and one configuration key `channel`, so every option plugs in without touching callers.
- Decisions: `channel in [website, landing_page, checkout]`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `dim.channel`.

## Stack
- Based on `lead-capture-flow/base-r2` (Revise lead capture flow foundation for plan revision 2). Merge that first.
- Unblocks `lead-capture-flow/channel-website`, `lead-capture-flow/channel-landing-page`, `lead-capture-flow/channel-checkout`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Medium: Every option of this dimension builds on the interface introduced here.
```

</details>

### 7. Add PDF delivery abstraction

Variation point for PDF delivery: one interface and one configuration key `pdf_delivery`, so every option plugs in without touching callers.

| | |
|---|---|
| Node | `dim.pdf_delivery` (dimension) |
| Decisions | `pdf_delivery in [email, download, none]` |
| Scope | Interface for PDF delivery, registration by option id, and the no-op implementation for `none`. |
| Depends on | `base.r2` |
| Why | `base.r2`: builds on the updated `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / M |
| Branch | `lead-capture-flow/pdf-delivery` onto `lead-capture-flow/base-r2` |
| Status | planned |

**Guidance.** Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. A no-op option is a real implementation of the interface; keep if-statements out of the call sites.

**Tests**
- Contract test suite that every implementation of the interface must pass.
- The no-op option `none` passes the contract suite.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Selecting any of email, download, none through configuration works without code changes in callers.
- [ ] The selected `pdf_delivery` option is observable in the output, no-op options included (for example `pdf_delivery=none`).

<details><summary>MR description</summary>

```markdown
## Summary
- Variation point for PDF delivery: one interface and one configuration key `pdf_delivery`, so every option plugs in without touching callers.
- Decisions: `pdf_delivery in [email, download, none]`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `dim.pdf_delivery`.

## Stack
- Based on `lead-capture-flow/base-r2` (Revise lead capture flow foundation for plan revision 2). Merge that first.
- Unblocks `lead-capture-flow/pdf-delivery-email`, `lead-capture-flow/pdf-delivery-download`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Medium: Every option of this dimension builds on the interface introduced here.
```

</details>

### 8. Add CRM sync abstraction

Variation point for CRM sync: one interface and one configuration key `crm_sync`, so every option plugs in without touching callers.

| | |
|---|---|
| Node | `dim.crm_sync` (dimension) |
| Decisions | `crm_sync in [hubspot, none]` |
| Scope | Interface for CRM sync, registration by option id, and the no-op implementation for `none`. |
| Depends on | `base.r2` |
| Why | `base.r2`: builds on the updated `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/crm-sync` onto `lead-capture-flow/base-r2` |
| Status | planned |

**Guidance.** Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. A no-op option is a real implementation of the interface; keep if-statements out of the call sites.

**Tests**
- Contract test suite that every implementation of the interface must pass.
- The no-op option `none` passes the contract suite.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more

**Acceptance criteria**
- [ ] Selecting any of hubspot, none through configuration works without code changes in callers.
- [ ] The selected `crm_sync` option is observable in the output, no-op options included (for example `crm_sync=none`).

<details><summary>MR description</summary>

```markdown
## Summary
- Variation point for CRM sync: one interface and one configuration key `crm_sync`, so every option plugs in without touching callers.
- Decisions: `crm_sync in [hubspot, none]`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `dim.crm_sync`.

## Stack
- Based on `lead-capture-flow/base-r2` (Revise lead capture flow foundation for plan revision 2). Merge that first.
- Unblocks `lead-capture-flow/crm-sync-hubspot`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 44 more.

## Risks
- Low: Every option of this dimension builds on the interface introduced here.
```

</details>

### 9. Channel: website

Implement `channel = website` behind the channel abstraction.

| | |
|---|---|
| Node | `opt.channel.website` (option) |
| Decisions | `channel = website` |
| Scope | One implementation of the channel interface, registered as `website`. No changes to other options. |
| Depends on | `dim.channel` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/channel-website` onto `lead-capture-flow/channel` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `website` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more

**Acceptance criteria**
- [ ] All 20 test scenarios with channel = website pass.
- [ ] The probe observes `channel=website` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `channel = website` behind the channel abstraction.
- Decisions: `channel = website`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.channel.website`.

## Stack
- Based on `lead-capture-flow/channel` (Add channel abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 10. Channel: landing page

Implement `channel = landing_page` behind the channel abstraction.

| | |
|---|---|
| Node | `opt.channel.landing_page` (option) |
| Decisions | `channel = landing_page` |
| Scope | One implementation of the channel interface, registered as `landing_page`. No changes to other options. |
| Depends on | `dim.channel` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/channel-landing-page` onto `lead-capture-flow/channel` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `landing_page` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T21, T22, T23, T24, T25, T26, T27, T28 and 12 more

**Acceptance criteria**
- [ ] All 20 test scenarios with channel = landing_page pass.
- [ ] The probe observes `channel=landing_page` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `channel = landing_page` behind the channel abstraction.
- Decisions: `channel = landing_page`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.channel.landing_page`.

## Stack
- Based on `lead-capture-flow/channel` (Add channel abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T21, T22, T23, T24, T25, T26, T27, T28 and 12 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 11. Channel: checkout

Implement `channel = checkout` behind the channel abstraction.

| | |
|---|---|
| Node | `opt.channel.checkout` (option) |
| Decisions | `channel = checkout` |
| Scope | One implementation of the channel interface, registered as `checkout`. No changes to other options. |
| Depends on | `dim.channel` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / S |
| Branch | `lead-capture-flow/channel-checkout` onto `lead-capture-flow/channel` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `checkout` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T41, T42, T43, T44, T45, T46, T47, T48 and 4 more

**Acceptance criteria**
- [ ] All 12 test scenarios with channel = checkout pass.
- [ ] The probe observes `channel=checkout` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `channel = checkout` behind the channel abstraction.
- Decisions: `channel = checkout`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.channel.checkout`.

## Stack
- Based on `lead-capture-flow/channel` (Add channel abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T41, T42, T43, T44, T45, T46, T47, T48 and 4 more.

## Risks
- Medium: Isolated to one option behind an interface.
```

</details>

### 12. PDF delivery: email

Implement `pdf_delivery = email` behind the PDF delivery abstraction.

| | |
|---|---|
| Node | `opt.pdf_delivery.email` (option) |
| Decisions | `pdf_delivery = email` |
| Scope | One implementation of the PDF delivery interface, registered as `email`. No changes to other options. |
| Depends on | `dim.pdf_delivery`, `dim.email_capture` |
| Why | `dim.email_capture`: constraint C1 (if pdf_delivery == email requires email_capture != disabled) |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / M |
| Branch | `lead-capture-flow/pdf-delivery-email` onto `lead-capture-flow/pdf-delivery` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `email` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more

**Acceptance criteria**
- [ ] All 20 test scenarios with pdf_delivery = email pass.
- [ ] The probe observes `pdf_delivery=email` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `pdf_delivery = email` behind the PDF delivery abstraction.
- Decisions: `pdf_delivery = email`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.pdf_delivery.email`.

## Stack
- Based on `lead-capture-flow/pdf-delivery` (Add PDF delivery abstraction). Merge that first.
- Unblocks `lead-capture-flow/email-format`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more.

## Risks
- Medium: Isolated to one option behind an interface.
```

</details>

### 13. Add email format abstraction

Variation point for email format: one interface and one configuration key `email_format`, so every option plugs in without touching callers.

| | |
|---|---|
| Node | `dim.email_format` (dimension) |
| Decisions | `email_format in [html, text]` |
| Scope | Interface for email format, registration by option id. |
| Depends on | `opt.pdf_delivery.email` |
| Why | `opt.pdf_delivery.email`: email_format only applies when pdf_delivery == email; `base.r2`: builds on the updated `base` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | medium / S |
| Branch | `lead-capture-flow/email-format` onto `lead-capture-flow/pdf-delivery-email` |
| Status | planned |

**Guidance.** Use a strategy (or equivalent) keyed by option id. Keep today's behavior as the default. A no-op option is a real implementation of the interface; keep if-statements out of the call sites.

**Tests**
- Contract test suite that every implementation of the interface must pass.
- Scenarios: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more

**Acceptance criteria**
- [ ] Selecting any of html, text through configuration works without code changes in callers.
- [ ] The selected `email_format` option is observable in the output, no-op options included (for example `email_format=text`).

<details><summary>MR description</summary>

```markdown
## Summary
- Variation point for email format: one interface and one configuration key `email_format`, so every option plugs in without touching callers.
- Decisions: `email_format in [html, text]`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `dim.email_format`.

## Stack
- Based on `lead-capture-flow/pdf-delivery-email` (PDF delivery: email). Merge that first.
- Unblocks `lead-capture-flow/email-format-html`, `lead-capture-flow/email-format-text`.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T03, T04, T05, T06, T07, T08 and 12 more.

## Risks
- Medium: Every option of this dimension builds on the interface introduced here.
```

</details>

### 14. PDF delivery: download

Implement `pdf_delivery = download` behind the PDF delivery abstraction.

| | |
|---|---|
| Node | `opt.pdf_delivery.download` (option) |
| Decisions | `pdf_delivery = download` |
| Scope | One implementation of the PDF delivery interface, registered as `download`. No changes to other options. |
| Depends on | `dim.pdf_delivery` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/pdf-delivery-download` onto `lead-capture-flow/pdf-delivery` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `download` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T09, T10, T11, T12, T13, T14, T29, T30 and 8 more

**Acceptance criteria**
- [ ] All 16 test scenarios with pdf_delivery = download pass.
- [ ] The probe observes `pdf_delivery=download` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `pdf_delivery = download` behind the PDF delivery abstraction.
- Decisions: `pdf_delivery = download`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.pdf_delivery.download`.

## Stack
- Based on `lead-capture-flow/pdf-delivery` (Add PDF delivery abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T09, T10, T11, T12, T13, T14, T29, T30 and 8 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 15. CRM sync: hubspot

Implement `crm_sync = hubspot` behind the CRM sync abstraction.

| | |
|---|---|
| Node | `opt.crm_sync.hubspot` (option) |
| Decisions | `crm_sync = hubspot` |
| Scope | One implementation of the CRM sync interface, registered as `hubspot`. No changes to other options. |
| Depends on | `dim.crm_sync` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/crm-sync-hubspot` onto `lead-capture-flow/crm-sync` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `hubspot` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T01, T02, T05, T06, T09, T11, T13, T15 and 18 more

**Acceptance criteria**
- [ ] All 26 test scenarios with crm_sync = hubspot pass.
- [ ] The probe observes `crm_sync=hubspot` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `crm_sync = hubspot` behind the CRM sync abstraction.
- Decisions: `crm_sync = hubspot`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.crm_sync.hubspot`.

## Stack
- Based on `lead-capture-flow/crm-sync` (Add CRM sync abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T01, T02, T05, T06, T09, T11, T13, T15 and 18 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 16. Email format: HTML

Implement `email_format = html` behind the email format abstraction.

| | |
|---|---|
| Node | `opt.email_format.html` (option) |
| Decisions | `email_format = html` |
| Scope | One implementation of the email format interface, registered as `html`. No changes to other options. |
| Depends on | `dim.email_format` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/email-format-html` onto `lead-capture-flow/email-format` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `html` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T01, T03, T05, T07, T21, T23, T25, T27 and 2 more

**Acceptance criteria**
- [ ] All 10 test scenarios with email_format = html pass.
- [ ] The probe observes `email_format=html` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `email_format = html` behind the email format abstraction.
- Decisions: `email_format = html`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.email_format.html`.

## Stack
- Based on `lead-capture-flow/email-format` (Add email format abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T01, T03, T05, T07, T21, T23, T25, T27 and 2 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 17. Email format: text

Implement `email_format = text` behind the email format abstraction.

| | |
|---|---|
| Node | `opt.email_format.text` (option) |
| Decisions | `email_format = text` |
| Scope | One implementation of the email format interface, registered as `text`. No changes to other options. |
| Depends on | `dim.email_format` |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | low / S |
| Branch | `lead-capture-flow/email-format-text` onto `lead-capture-flow/email-format` |
| Status | planned |

**Guidance.** Touch only the new implementation and its registration. If the interface has to change, that change belongs in the abstraction node.

**Tests**
- Unit tests for the `text` implementation.
- Run the contract suite from the abstraction against it.
- Scenarios: T02, T04, T06, T08, T22, T24, T26, T28 and 2 more

**Acceptance criteria**
- [ ] All 10 test scenarios with email_format = text pass.
- [ ] The probe observes `email_format=text` in exactly the scenarios that select it (`cad.py verify --probe`).

<details><summary>MR description</summary>

```markdown
## Summary
- Implement `email_format = text` behind the email format abstraction.
- Decisions: `email_format = text`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `opt.email_format.text`.

## Stack
- Based on `lead-capture-flow/email-format` (Add email format abstraction). Merge that first.

## Verification
- Not run yet.
- Scenarios to cover: T02, T04, T06, T08, T22, T24, T26, T28 and 2 more.

## Risks
- Low: Isolated to one option behind an interface.
```

</details>

### 18. Send the PDF once the address is captured

Glue code for variants where pdf_delivery == email and email_capture == after_test.

| | |
|---|---|
| Node | `ix.pdf-after-capture` (interaction) |
| Decisions | `pdf_delivery == email and email_capture == after_test` |
| Scope | Only the code that is needed because these options meet. Each option stays usable on its own. |
| Depends on | `opt.pdf_delivery.email`, `opt.email_capture.after_test` |
| Why | starts after `opt.pdf_delivery.email`, `opt.email_capture.after_test` merged, because they sit on separate lanes |
| Components | _to fill in from the repository_ |
| Expected files | _to fill in from the repository_ |
| Risk / complexity | high / M |
| Branch | `lead-capture-flow/pdf-after-capture` onto `main` in wave 2 |
| Status | planned |

**Guidance.** Keep the glue at the composition root or in a small coordinator, so each option still works without the other.

**Tests**
- Integration test that exercises the involved options together.
- Scenarios: T05, T06, T07, T08, T25, T26, T27, T28 and 4 more

**Acceptance criteria**
- [ ] All 12 test scenarios where pdf_delivery == email and email_capture == after_test pass.

<details><summary>MR description</summary>

```markdown
## Summary
- Glue code for variants where pdf_delivery == email and email_capture == after_test.
- Decisions: `pdf_delivery == email and email_capture == after_test`
- Part of the Lead capture flow decision space (examples/lead-capture-flow-r2.md), node `ix.pdf-after-capture`.

## Stack
- Based on `main` after `opt.pdf_delivery.email`, `opt.email_capture.after_test` merged.

## Verification
- Not run yet.
- Scenarios to cover: T05, T06, T07, T08, T25, T26, T27, T28 and 4 more.

## Risks
- High: Couples options; regressions only show up in combined scenarios.
```

</details>

## Test matrix

Mode: **exhaustive**, every valid variant is a test scenario.

> The test matrix contains every valid variant.

<details><summary>52 scenarios</summary>

| ID | `channel` | `pdf_delivery` | `email_capture` | `crm_sync` | `email_format` |
|---|---|---|---|---|---|
| T01 | `website` | `email` | `before_test` | `hubspot` | `html` |
| T02 | `website` | `email` | `before_test` | `hubspot` | `text` |
| T03 | `website` | `email` | `before_test` | `none` | `html` |
| T04 | `website` | `email` | `before_test` | `none` | `text` |
| T05 | `website` | `email` | `after_test` | `hubspot` | `html` |
| T06 | `website` | `email` | `after_test` | `hubspot` | `text` |
| T07 | `website` | `email` | `after_test` | `none` | `html` |
| T08 | `website` | `email` | `after_test` | `none` | `text` |
| T09 | `website` | `download` | `before_test` | `hubspot` | n/a |
| T10 | `website` | `download` | `before_test` | `none` | n/a |
| T11 | `website` | `download` | `after_test` | `hubspot` | n/a |
| T12 | `website` | `download` | `after_test` | `none` | n/a |
| T13 | `website` | `download` | `disabled` | `hubspot` | n/a |
| T14 | `website` | `download` | `disabled` | `none` | n/a |
| T15 | `website` | `none` | `before_test` | `hubspot` | n/a |
| T16 | `website` | `none` | `before_test` | `none` | n/a |
| T17 | `website` | `none` | `after_test` | `hubspot` | n/a |
| T18 | `website` | `none` | `after_test` | `none` | n/a |
| T19 | `website` | `none` | `disabled` | `hubspot` | n/a |
| T20 | `website` | `none` | `disabled` | `none` | n/a |
| T21 | `landing_page` | `email` | `before_test` | `hubspot` | `html` |
| T22 | `landing_page` | `email` | `before_test` | `hubspot` | `text` |
| T23 | `landing_page` | `email` | `before_test` | `none` | `html` |
| T24 | `landing_page` | `email` | `before_test` | `none` | `text` |
| T25 | `landing_page` | `email` | `after_test` | `hubspot` | `html` |
| T26 | `landing_page` | `email` | `after_test` | `hubspot` | `text` |
| T27 | `landing_page` | `email` | `after_test` | `none` | `html` |
| T28 | `landing_page` | `email` | `after_test` | `none` | `text` |
| T29 | `landing_page` | `download` | `before_test` | `hubspot` | n/a |
| T30 | `landing_page` | `download` | `before_test` | `none` | n/a |
| T31 | `landing_page` | `download` | `after_test` | `hubspot` | n/a |
| T32 | `landing_page` | `download` | `after_test` | `none` | n/a |
| T33 | `landing_page` | `download` | `disabled` | `hubspot` | n/a |
| T34 | `landing_page` | `download` | `disabled` | `none` | n/a |
| T35 | `landing_page` | `none` | `before_test` | `hubspot` | n/a |
| T36 | `landing_page` | `none` | `before_test` | `none` | n/a |
| T37 | `landing_page` | `none` | `after_test` | `hubspot` | n/a |
| T38 | `landing_page` | `none` | `after_test` | `none` | n/a |
| T39 | `landing_page` | `none` | `disabled` | `hubspot` | n/a |
| T40 | `landing_page` | `none` | `disabled` | `none` | n/a |
| T41 | `checkout` | `email` | `after_test` | `hubspot` | `html` |
| T42 | `checkout` | `email` | `after_test` | `hubspot` | `text` |
| T43 | `checkout` | `email` | `after_test` | `none` | `html` |
| T44 | `checkout` | `email` | `after_test` | `none` | `text` |
| T45 | `checkout` | `download` | `after_test` | `hubspot` | n/a |
| T46 | `checkout` | `download` | `after_test` | `none` | n/a |
| T47 | `checkout` | `download` | `disabled` | `hubspot` | n/a |
| T48 | `checkout` | `download` | `disabled` | `none` | n/a |
| T49 | `checkout` | `none` | `after_test` | `hubspot` | n/a |
| T50 | `checkout` | `none` | `after_test` | `none` | n/a |
| T51 | `checkout` | `none` | `disabled` | `hubspot` | n/a |
| T52 | `checkout` | `none` | `disabled` | `none` | n/a |

</details>

<!-- cad:generated:end -->

## Changelog
- **r2** (2026-09-28): Emails can be HTML or plain text. Sending the PDF after capture needs glue code.
  - Added: `base.r2`, `dim.email_format`, `opt.email_format.html`, `opt.email_format.text`, `ix.pdf-after-capture`.
  - Valid variants 42 to 52; test scenarios 42 to 52; nodes 13 to 18.
  - Follow-up planned: `base.r2`, because `base` is merged and its contract changed.
  - Sign-off cleared: the spec changed after approval.
- **r1** (2026-09-24): Approved by Dana (product).
  - Confirmed despite: 42 targeted variants exceed max_valid_variants (20). 13 implementation nodes exceed max_implementation_nodes (12). 13 new MRs in this revision exceed require_confirmation_above (8).
- **r1** (2026-09-23): Initial plan for the lead capture flow.

<!-- cad:contracts
base ["decision: shared by all variants", "scope: Domain types, one configuration object with a key per dimension, validation of that configuration against the constraints, and the composition root that picks implementations.", "accept: Configuration accepts the # valid variants and rejects the # invalid combinations.", "accept: Existing behavior is unchanged while no variation point is wired in.", "accept: The composition root discovers option modules at runtime, so option branches never edit shared files.", "accept: Every active option leaves a marker in the output (for example `data-cad=\"style=serious\"`), and the `verify.probe` command prints the markers it observes as `dimension=option`.", "rule: if pdf_delivery == email requires email_capture != disabled", "rule: if channel == checkout excludes email_capture == before_test", "options: channel: checkout, landing_page, website", "options: pdf_delivery: download, email, none", "options: email_capture: after_test, before_test, disabled", "options: crm_sync: hubspot, none", "options: email_format: html, text"]
dim.email_capture ["decision: email_capture in [before_test, after_test, disabled]", "depends on: base", "scope: Interface for email capture, registration by option id, and the no-op implementation for `disabled`.", "accept: Selecting any of before_test, after_test, disabled through configuration works without code changes in callers.", "accept: The selected `email_capture` option is observable in the output, no-op options included (for example `email_capture=disabled`)."]
opt.email_capture.after_test ["decision: email_capture = after_test", "depends on: dim.email_capture", "scope: One implementation of the email capture interface, registered as `after_test`. No changes to other options.", "accept: All # test scenarios with email_capture = after_test pass.", "accept: The probe observes `email_capture=after_test` in exactly the scenarios that select it (`cad.py verify --probe`)."]
-->
