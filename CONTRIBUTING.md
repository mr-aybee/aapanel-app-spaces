# Contributing

Thanks for helping improve App Spaces.

## Setup

Python 3.9+ is all the backend needs; no third-party packages.

```bash
python tools/assemble_ui.py
python -m unittest discover -s tests -v
```

## Guidelines

- Edit UI sources (`app_spaces/ui.html`, `ui.css`, `ui.js`, `creation_ui.js`), then run `tools/assemble_ui.py` and commit the regenerated `index.html`, `workspace.html` and `preview/index.html`. CI fails if they are out of date.
- Keep the backend on the Python standard library.
- Never add a generic command-execution path. New operations must be explicit, validated, and gated by primary-admin auth, CSRF and request IDs.
- Never display fabricated metrics or state. Use "unavailable".
- Add or update tests in `tests/` for behavior changes. Run the Playwright checks (`node tests/ui.spec.cjs`) for UI changes.
- Do not commit `app_spaces/data/`, real hostnames, usernames or credentials. Use `example.com` / `example.net` in fixtures.

## Reporting security issues

Do not open a public issue. Use GitHub's **Security → Report a vulnerability** (private advisory) on this repository.

## Releasing

1. Bump `versions` in `app_spaces/info.json` and add a `CHANGELOG.md` entry.
2. Commit, then tag and push: `git tag v<version> && git push origin v<version>`.
3. The Release workflow tests, builds `app_spaces-<version>.zip` (+ `.sha256`) and publishes a GitHub Release.
