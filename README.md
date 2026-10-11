# Civil Code Plain Answers（民法典百炼白话问答）

An open-source Agent Skill for everyday questions about **residential rental deposits in mainland China**. The user describes the situation in their own words and gets: what to check first, which contract sentences matter, which official provisions say what, and a neutral message they can edit and send themselves.

**Current public release: D1 — material navigation only.** The skill does **not** give legal conclusions. The legal-explanation capabilities (`LEGAL01` / `LEGAL02`) are **not enabled**, because no real legal-professional review record exists yet. The scope is one scenario (`rent_deposit`); this is not coverage of Chinese rental law, and it is not twelve scenarios.

[中文说明](README.zh-CN.md)

## What it does today

| Capability | State | What it does |
| --- | --- | --- |
| NAV01–NAV03 | enabled | Locate the deposit clause; sort handover facts; map deduction items to evidence |
| DRAFT01 | enabled | Neutral message draft; the user decides whether to send it |
| SOURCE01 | enabled | Point to official provisions (text and locator only, no interpretation) |
| DIALOG01 | enabled | Multi-turn correction; stale premises are retracted and re-evaluated |
| LEGAL01 / LEGAL02 | **not enabled** | Needs real legal review; currently returns `PENDING_REVIEW` |

## Run it

Python 3 standard library only. Paths resolve relative to the module, so it runs from any working directory.

```sh
python3 skill/civil-code-plain-answers/scripts/answer.py --question "押金还没退，我该先看什么？"
python3 skill/civil-code-plain-answers/tests/run_tests.py
```

`stdout` is a single JSON envelope. The user-visible text is the `text` field and must be shown as-is (`render_contract.allow_host_append` is `false`). Exit codes: `0` normal (including a limited reply), `2` request or runtime failure, `3` output check failed. Exit code `0` is **not** evidence that an answer passed acceptance.

The model backend is optional. Copy `skill/civil-code-plain-answers/config/example.json` to `config/local.json` to point at a local Ollama. Without a usable local model the pipeline degrades to `heuristic-no-model` — a deterministic, template-only path that produces no free-form legal text — and reports `MODEL_UNAVAILABLE`. It never silently switches to a cloud model.

## What it does not do

No win rates, no predicted outcomes, no refund amounts or deduction ratios, no nationwide refund deadlines, no limitation-period conclusions, no court-fee or jurisdiction conclusions, no filing on the user's behalf, and no sending messages to third parties. When asked for these, it keeps giving the material help it can actually support.

## Layout

- `skill/civil-code-plain-answers/` — the skill: `SKILL.md`, `LICENSE.txt`, `config/`, `references/` (rules, templates, sources, reviews, release manifest), `scripts/`, plus `sources/` (official snapshots), `tests/` and `tools/` used during development.
- `scripts/`, `tests/`, `reports/`, `plan/`, `sources/SOURCE_MANIFEST.json` — the **earlier** wider-scope engineering effort (personal lending, residential leases, marital property; twelve planned scenarios). It is kept for history: nothing in it is enabled, its rules were never professionally reviewed, and it no longer drives the published skill.
- `docs/法律专业复核交接.md` — handover note for legal-professional review.

## Package

```sh
python3 scripts/package.py          # writes dist/ archives and dist/PACKAGE_MANIFEST.json
python3 tests/smoke_package.py      # extracts the SkillHub ZIP and checks the contract
```

The SkillHub archive contains only the runtime subset; `tests/`, `tools/`, `sources/` and `evidence/` are excluded.

## Status and gates

`skill/civil-code-plain-answers/references/release-manifest.json` is the source of truth for what is enabled. Current honest status:

- 33/33 program tests pass; 1 is not run (it needs a real local model).
- No legal-professional review record exists, so `LEGAL01`/`LEGAL02` stay disabled.
- The host's final displayed text has not been re-tested since the skill instructions were tightened.

## License

MIT for this project's own code and documentation (see `LICENSE` and `skill/civil-code-plain-answers/LICENSE.txt`). The official law texts referenced in `references/sources.json` come from public government pages and are used for citation and locating only; third-party commentary, publications and images are not distributed here and are not covered by the MIT grant.

Do not put real identities, account numbers or confidential case files into this repository or its issue tracker.
