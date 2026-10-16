# Orbit NoSQL Mongo: development

This package declares support for `>=3.11,<3.15` in `pyproject.toml`. That declaration is distinct from evidence that hosted CI ran.

Use the checks for each language manifest present in this repository:

### Python package

```bash
python -m pip install -e '.[dev]' build
pytest
ruff check src tests
ruff format --check src tests
mypy
```

Optional SDKs and live-service tests are described by the package README. Do not run an opt-in live test against a shared or production service unless its own documentation explicitly supports that use.

## Contribution expectations

The last recorded local quality matrix passed on CPython 3.11, 3.12, 3.13, and 3.14. Since that
matrix, failed-close and cancelled-close retry regressions were added; the current suite passes on
CPython 3.13.15 with 10 tests passing and the opt-in MongoDB service test skipped because
`ORBIT_MONGO_URI` is unset. Ruff lint/format, strict mypy, and whitespace checks also pass for the
current changes. Rerun the full interpreter matrix and service test before release; hosted CI and
live MongoDB behavior are not established here.

Add focused regression coverage for behavior changes. Update the README and relevant guide when a contract, configuration option, security property, lifecycle rule, or operational assumption changes. Report the exact versions and services exercised; local checks do not imply hosted CI or release validation.
