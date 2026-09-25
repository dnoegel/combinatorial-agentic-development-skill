# Working on this repository

- The tool must stay dependency-free: Python 3.9+ standard library only, in `skills/combinatorial-agentic-development/scripts/`.
- Run `python3 -m unittest discover tests` before and after changes.
- Changes to the planning document output need `python3 tests/examples_builder.py`; the tests fail on a stale example.
- Everything the tool generates must be deterministic. Dates come from `CAD_DATE` in tests.
- Generated text and docs use no em dashes and no tool or agent attribution.
- Keep `SKILL.md` short. Details belong in `references/`.
