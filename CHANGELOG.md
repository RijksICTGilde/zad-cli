# Changelog

## [Unreleased]

### Added
- Initial CLI with full command tree: config, project, deployment, backup, restore, clone, logs, metrics, invite
- API client with retry logic (exponential backoff on 429/5xx) and async task polling
- `.env` file support via python-dotenv
- Global config file at `~/.config/zad/config.toml` for api_url
- Global `--project`/`-p` flag and `ZAD_PROJECT_ID` env var
- Output formatting: table (Rich), json, yaml
- Input validation matching zad-actions patterns
- Claude Code skill for AI-assisted operations
