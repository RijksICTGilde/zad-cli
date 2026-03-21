"""Logs command: zad logs [-d deployment] [-n 100] [--since 1h]."""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime, timedelta

import typer

from zad_cli.helpers import complete_deployment, get_helpers, handle_api_errors, require_project

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}

# Matches timestamps like "2026/03/21 11:16:12" or "2026-03-18T15:04:48.775Z"
_TS_PATTERNS = [
    re.compile(r"(\d{4}[/-]\d{2}[/-]\d{2}[T ]\d{2}:\d{2}:\d{2})"),
]


def _parse_since(since: str) -> datetime:
    """Parse a duration string like '1h', '30m', '2d' into a cutoff datetime."""
    match = _DURATION_RE.match(since)
    if not match:
        raise typer.BadParameter(f"Invalid duration '{since}'. Use e.g. 30m, 1h, 2d.")
    value, unit = int(match.group(1)), match.group(2)
    delta = timedelta(**{_DURATION_UNITS[unit]: value})
    return datetime.now(tz=UTC) - delta


def _parse_line_timestamp(line: str) -> datetime | None:
    """Try to extract a timestamp from a log line."""
    for pattern in _TS_PATTERNS:
        match = pattern.search(line)
        if match:
            ts_str = match.group(1).replace("/", "-").replace("T", " ")
            try:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _format_logs(data: dict, since_cutoff: datetime | None = None) -> str:
    """Format parsed log JSON into text output, optionally filtering by time."""
    lines = []
    for result in data.get("results", []):
        header = f"==> {result['deployment']}/{result['component']} <=="
        component_lines = []
        for line in result.get("lines", []):
            if since_cutoff:
                ts = _parse_line_timestamp(line)
                if ts and ts < since_cutoff:
                    continue
            component_lines.append(line)
        if component_lines:
            lines.append(header)
            lines.extend(component_lines)
            lines.append("")
    return "\n".join(lines)


@handle_api_errors
def logs_command(
    ctx: typer.Context,
    deployment: str = typer.Option(
        None, "--deployment", "-d", help="Deployment name", autocompletion=complete_deployment
    ),
    container: str = typer.Option(None, "--container", help="Container name"),
    tail: int = typer.Option(None, "--tail", "-n", help="Number of lines to show"),
    since: str = typer.Option(None, "--since", help="Show logs newer than duration (e.g. 1h, 30m, 2d)"),
) -> None:
    """View logs for a project deployment.

    Requires ZAD_API_KEY and ZAD_PROJECT_ID (or --api-key and -p).

    [bold]Examples:[/bold]

        $ zad logs -d regelrecht

        $ zad logs -d regelrecht --since 1h

        $ zad logs -d regelrecht -n 50
    """
    project = require_project(ctx)
    client, formatter = get_helpers(ctx)

    since_cutoff = _parse_since(since) if since else None
    data = client.get_logs(project, deployment=deployment, container=container, limit=tail, since=since)

    if formatter.fmt in ("json", "yaml"):
        formatter.render(data)
    else:
        text = _format_logs(data, since_cutoff=since_cutoff)
        if text.strip():
            formatter.render_text(text)
        else:
            print("No logs found.", file=sys.stderr)
