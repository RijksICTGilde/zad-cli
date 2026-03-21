# Changelog

## [Unreleased]

### Added
- Initial CLI with full command tree: config, project, deployment, backup, restore, clone, logs, metrics, invite
- API client with retry logic (exponential backoff on 429/5xx) and async task polling
- Configuration with named contexts (~/.zad/config.yml) and environment variables (ZAD_API_KEY, ZAD_API_URL)
- Output formatting: table (Rich), json, yaml
- Input validation matching zad-actions patterns
- Claude Code skill for AI-assisted operations
