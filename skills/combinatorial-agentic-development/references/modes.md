# Generation modes

Two questions are easy to mix up:

1. **What do we build?** Every option that occurs in the targeted variants, each once, behind an abstraction. The number of MRs grows with the number of options.
2. **What do we test?** A set of full variants (scenarios). Their number grows with the product of the options unless you reduce it.

`generation.mode` chooses the targeted variants. Implementation follows from them, and so does the test matrix.

## Trade-offs

| Mode | Scenarios | Implementation | Guarantee | Cost | Good for |
|---|---|---|---|---|---|
| `exhaustive` | every valid variant | every option | each shippable product has a scenario | grows with the product of options | small spaces, regulated flows, everything ships |
| `pairwise` | small set covering every reachable pair | every option (pairs contain every single value) | every combination of two decisions is exercised | roughly grows with the two largest dimensions | large spaces where most bugs involve one or two decisions |
| `twise` | small set covering every reachable t-tuple | every option | every combination of t decisions is exercised | grows quickly with t | risky interactions between three or more decisions |
| `selected` | the listed variants | options used by them | each listed product has a scenario | as many as you list | only some variants will ship |

Numbers for the lead-capture example (42 valid variants): exhaustive 42 scenarios, pairwise 10, 3-wise 22 (run `cad.py analyze --json` for the current values).

## What pairwise and t-wise do not promise

Pairwise coverage exercises every pair of decisions. A defect that needs three specific decisions together can slip through; t-wise with t = 3 narrows that gap and costs more. The tool therefore always reports:

- how many valid variants are configurable from the implemented options,
- how many of those have no dedicated scenario,
- how many t-tuples are reachable, covered, and impossible under the constraints.

When you summarize a pairwise plan, repeat the untested count. "Implemented and pairwise tested" is accurate. "All 42 variants tested" is not.

## Algorithm

Pairwise and t-wise use a deterministic lazy greedy set cover over the enumerated valid variants (the AETG family of strategies). Candidates are valid variants only, so constraints are handled exactly and no scenario violates one. Ties go to the earlier variant in enumeration order, so the matrix is stable across runs. The result is small but not guaranteed minimal; for planning that is the right trade.

Established tools such as Microsoft PICT and NIST ACTS produce smaller arrays for very large spaces and have richer constraint languages. They are the natural backend once spaces are too large to enumerate; see the roadmap in the README.

## Choosing a mode

- Fewer than about 30 valid variants and each could ship: `exhaustive`.
- More than that, and all options must work: `pairwise`, then raise to `twise` for risky dimensions.
- Only a few variants ship this quarter: `selected`, which also shrinks the implementation to the options those variants use.
- Unsure: start with `exhaustive`. If the limit triggers, the tool offers pairwise as an option.
