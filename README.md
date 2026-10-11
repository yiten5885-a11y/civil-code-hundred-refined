![民法典百炼白话问答封面：借贷、租房、婚姻财产；理清事实、查找法源、关键追问；工程内测](assets/cover.jpg)

# Civil Code Plain Answers (engineering alpha)

An open-source Agent Skill prototype for everyday questions about personal loans, residential leases, and marital property in mainland China. Its current public release **organizes facts and points to official sources; it does not provide reviewed legal conclusions**. The planned twelve scenarios, local Qwen drafts, and three-turn examples have not passed professional legal review. No rule is enabled in `rules/approved/`.

[中文说明](README.zh-CN.md) · [Development status](plan/TASKS.md) · [Release readiness](reports/PUBLISH_READINESS.md)

## What is in the repository

- `skill/civil-code-plain-answers/`: the five-file public skill. Its Chinese instructions direct the host to use `scripts/answer.py` and show only the returned text when the status is not `ANSWER`.
- `scripts/`: official-source fetching, article extraction and hash checks, local-only Qwen draft generation, candidate auditing, and packaging.
- `sources/SOURCE_MANIFEST.json`: source locations and recorded hashes. Downloaded law pages and normalized full texts stay outside Git and outside both public skill ZIPs.
- `tests/`: program checks and an 80-case inventory. The legal expected answers have not been approved; twenty cases are reserved for final acceptance.
- `reports/`: inspectable engineering evidence and explicit remaining gates.

The private Qwen candidates, reviewer notes, normalized law texts, and unsigned 80-case review worksheet are excluded from Git and the public skill. A separate local reviewer bundle can be built for authorized professional review.

## Reproduce the engineering checks

Python 3 standard library is sufficient for the program tests and packages. Fetching official pages additionally uses `curl` and a network connection. Local Qwen candidate generation is optional and requires your own loopback Ollama service; installing the public skill does not provide a model or free inference.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/package.py
python3 tests/smoke_package.py
printf '%s\n' '{"question":"押金还没退，我该先看什么？","scenario":"rent_deposit"}' | python3 skill/civil-code-plain-answers/scripts/answer.py
```

The sample answer currently returns `PENDING_REVIEW`. To rebuild local official-source indexes, run `source_pipeline.py fetch` and `build`, followed by the relevant companion normalization scripts and `check_source_hashes.py`. The [Chinese guide](README.zh-CN.md) lists the full commands and the local Qwen workflow. Hash checks establish file integrity, not current legal effect or correct interpretation.

## Host and release limits

The five-file skill was installed locally in WorkBuddy 5.7.7 and invoked on two synthetic questions. In one run the host added unreviewed conditional claims after the script returned `PENDING_REVIEW`. The skill instructions were tightened, but that host behavior has not yet been retested. A prompt-only skill cannot guarantee that a host will enforce the script's output boundary.

The planned release gates remain open: source validity and applicability, professional review of every enabled rule and example, legal and factual acceptance of the 80 cases, a five-reader comprehension check, and a host-level end-to-end test. Only the scope that passes these gates may be described as providing legal explanations. The current alpha is limited to fact organization and source pointers.

## License and data

The project's original code and documentation are MIT licensed. Third-party official law pages, publisher materials, and user consultations are not included under that license. Do not submit real identities, account numbers, or confidential case files to the public repository or issue tracker.
