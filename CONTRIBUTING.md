# Contributing to AN-KLA Memory

Thanks for considering a contribution. AN-KLA is in local beta with a
deliberately conservative release policy: every change that touches storage,
retrieval, concurrency, or the managed contract must go through the governed
write flow and a tagged release.

## Before you start

- Open an issue describing the change you want to make. Wait for a maintainer
  response before investing significant work.
- AN-KLA Memory intentionally avoids third-party runtime dependencies. Keep it
  pure-Python and stdlib-only.
- Discuss API or schema changes in the issue first. The project does not bump
  major versionson beta; additive-only changes are preferred.

## Development setup

```bash
git clone https://github.com/kristhianmanue1/an-kla-memory.git
cd an-kla-memory
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

## Code style

- Target Python 3.9 for runtime code. Type hints (`from __future__ import
  annotations`) are mandatory in `an_kla/`.
- Use 4-space indentation, no tabs.
- Module, function, and class docstrings explain *intent*, not implementation.
- No emoji in code, error messages, or documentation.
- Comments explain *why*, not *what*. Prefer clear names over comments.

## Tests

- Add or update tests under `tests/` for every behavior change.
- Tests must be deterministic: no real network, no real clock, no `sleep`.
- Run the full suite before committing:

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

- Any change to `an_kla/store.py`, `an_kla/retrieval.py`, `an_kla/index.py`,
  or `an_kla/write_policy.py` requires the suite green.

## Architecture decisions

Changes that affect storage, retrieval, concurrency, or public contracts
require an Architecture Decision Record (ADR) under `docs/architecture/`. Use
the next free number and follow the structure of existing ADRs (Context,
Decision, Consequences).

## Pull request flow

1. Create a branch named `feat/…`, `fix/…`, or `docs/…`.
2. Open a PR against `main`.
3. Fill the PR template (tests, ADR, contract impact).
4. Ensure CI (`test.yml`, matrix `{ubuntu, macos, windows}` × `{3.9, 3.12}`)
   is green.
5. Do not squash-merge: keep individual commits; they are valuable history.

## Managed contract changes

`AGENTS.md` and `AN-KLA.md` are governed by the managed-context contract. Do
not edit them by hand in a PR. Instead:

1. Modify `DETAILED_CONTRACT` / `COMPACT_PAYLOAD` in `an_kla/context_package.py`.
2. Bump `TEMPLATE_VERSION` (and `VERSION` if also releasing).
3. Register the previous version in `_KNOWN_CONTEXT_TEMPLATES`.
4. Apply the change locally via `python -m an_kla context plan --operation
   update` → `context apply`.
5. Include the resulting `AGENTS.md` / `AN-KLA.md` diff in the PR.

## Releasing

Releases are tagged manually by the maintainer. Do not push tags from a PR.
The release checklist lives in `docs/releases/`.

## Code of conduct

Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
