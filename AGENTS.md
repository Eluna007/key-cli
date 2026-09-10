# key-cli development rules

## Responsibilities

key-cli is an independent repository. It owns the `key shell`, `key ipc`, `key record`,
`key audio`, `key keyboard`, `key clipboard` and `key doctor` commands, their backend/process identity
behavior, packaging, and the machine-facing JSON protocol. Clavis consumes these public
interfaces; key-cli tests must not depend on `../clavis` or `../keytop`.

## Test policy

**Do not add tests automatically just because code was changed.** Fixing a bug does not
automatically require a regression test. Add a test only for stable CLI behavior, a public
JSON contract, backend input/output behavior, process identity/state semantics, or a
packaging artifact. Before adding one, explain why lint/build cannot cover it, why the
chosen test layer is appropriate, and why it does not freeze implementation details.

Allowed tests include public CLI parsing and entrypoint behavior, JSON response contracts,
clipboard MIME/backend behavior, recording/audio state transitions, process identity,
packaging and service artifacts. Tests must exercise input → backend → output behavior.

Forbidden tests use `grep`, `sed`, `awk`, regular expressions or source-text matching to
assert function names, file layout, class/module layout or implementation shape. Do not
create `test_*_architecture.sh`, `test_*_feature.sh` or `test_*_implementation.sh` tests.

## Protocol changes

When machine-facing JSON changes, update `docs/protocol.md` and the relevant contract
tests together. Preserve `schemaVersion`, `command`, `ok`, `error`, exit-code semantics,
and the documented record/audio/clipboard fields unless a deliberate protocol change is
being reviewed.

## Developer workflow

Use `.venv` with `python3 -m venv .venv` and
`.venv/bin/python -m pip install -e '.[dev]'`. Ordinary source edits need no reinstall;
metadata changes do, and existing watchers require an explicit restart.
`scripts/check.sh` runs daily quality/tests; `scripts/check.sh --build` adds wheel/install
verification. Do not run the same checks separately before that entry point.
Source deployment uses `scripts/install.sh` / `scripts/uninstall.sh`, a dedicated venv
and /usr/local. Development service overrides and optional keyboard authorization have
independent opt-in lifecycles. Arch scripts are future packaging references, never a
prerequisite for development or source installation. Do not silently modify fish,
permissions or user services. Installer tests use temporary roots and mock system tools.

`ruff format` is the formatter; do not add Black, isort or flake8. Do not add mypy,
pyright, coverage thresholds or a large pre-commit framework in routine cleanup.
