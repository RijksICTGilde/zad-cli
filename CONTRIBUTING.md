# Contributing

## Setup

```bash
git clone https://github.com/RijksICTGilde/zad-cli.git
cd zad-cli
uv sync
uv run pre-commit install
```

## Development

```bash
uv run zadctl --help       # Run the CLI
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ruff format .       # Format
```

The command is `zadctl`. `zad` is registered as a second name for the same entry point, so
scripts and pipelines that already type it keep working; use `zadctl` in new code, help
texts and examples.

## Building the standalone binary

Releases ship a binary per platform so users need no Python. To build the same thing
locally, with the same flags the release uses:

```bash
scripts/build-binary.sh              # into dist/
scripts/build-binary.sh --install    # and copy it into ~/.local/bin
```

Nuitka compiles rather than bundles, so this takes a few minutes. The script ends with the
same smoke test the release runs, including a `-c` short option: a compiled binary can read
short flags that Python itself uses before the CLI ever sees them, and that shipped broken
once because the smoke test only used long options.

Keep the flags in `scripts/build-binary.sh` and
`.github/workflows/release-binaries.yml` in step. They drifted apart once, and a local build
then accepted input the published one died on.

## Testing

All tests run without a real API connection. Uses `respx` for httpx mocking and `tmp_path` for filesystem tests.

```bash
uv run pytest -v                                    # All tests
uv run pytest tests/test_client.py                   # Single file
uv run pytest tests/test_client.py::test_retry_on_500  # Single test
```

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature (bumps minor version)
- `fix:` bug fix (bumps patch version)
- `chore:` maintenance (no version bump)
- `docs:` documentation (no version bump)
- `test:` tests (no version bump)

CI enforces this format on all PR commits. Use `feat!:` or add a
`BREAKING CHANGE:` footer for breaking changes (bumps minor while pre-1.0).

## License

EUPL-1.2
