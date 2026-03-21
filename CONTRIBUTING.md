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
uv run zad --help          # Run the CLI
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ruff format .       # Format
```

## Testing

All tests run without a real API connection. Uses `respx` for httpx mocking and `tmp_path` for filesystem tests.

```bash
uv run pytest -v                                    # All tests
uv run pytest tests/test_client.py                   # Single file
uv run pytest tests/test_client.py::test_retry_on_500  # Single test
```

## Commit messages

Use conventional commits:

- `feat:` new feature
- `fix:` bug fix
- `chore:` maintenance
- `docs:` documentation
- `test:` tests

## License

EUPL-1.2
