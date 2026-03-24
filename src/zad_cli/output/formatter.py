"""Output formatting: table, json, yaml."""

from __future__ import annotations

import json
import sys

import yaml
from rich.console import Console
from rich.table import Table

# Console for stderr (status messages), stdout is for data output
err_console = Console(stderr=True)


class OutputFormatter:
    """Render data in table, json, or yaml format."""

    def __init__(self, fmt: str = "table"):
        self.fmt = fmt
        self.console = Console()

    def render(
        self,
        data: list[dict] | dict,
        columns: list[str] | None = None,
        title: str | None = None,
    ) -> None:
        """Render a list of records or a single record."""
        if self.fmt == "json":
            print(json.dumps(data, indent=2, default=str))
        elif self.fmt == "yaml":
            print(yaml.dump(data, default_flow_style=False, sort_keys=False))
        else:
            self._table(data, columns, title)

    def render_detail(self, data: dict, title: str | None = None) -> None:
        """Render a single item as key-value pairs."""
        if self.fmt == "json":
            print(json.dumps(data, indent=2, default=str))
        elif self.fmt == "yaml":
            print(yaml.dump(data, default_flow_style=False, sort_keys=False))
        else:
            table = Table(title=title, show_header=True)
            table.add_column("Key", style="bold cyan")
            table.add_column("Value")
            for k, v in data.items():
                table.add_row(str(k), str(v))
            self.console.print(table)

    def render_text(self, text: str) -> None:
        """Render raw text (for logs)."""
        print(text)

    def render_success(self, message: str) -> None:
        """Print success message to stderr."""
        err_console.print(f"[green]{message}[/green]")

    def render_error(self, message: str, details: dict | None = None, status_code: int | None = None) -> None:
        """Print error to stderr, or JSON to stdout in json mode."""
        if self.fmt == "json":
            error_data: dict = {"error": message}
            if status_code is not None:
                error_data["status_code"] = status_code
            if details:
                error_data["details"] = details
            print(json.dumps(error_data, indent=2, default=str))
        else:
            print(f"Error: {message}", file=sys.stderr)
            if details:
                for k, v in details.items():
                    print(f"  {k}: {v}", file=sys.stderr)

    def _table(
        self,
        data: list[dict] | dict,
        columns: list[str] | None = None,
        title: str | None = None,
    ) -> None:
        """Render data as a Rich table."""
        if isinstance(data, dict):
            data = [data]
        if not data:
            err_console.print("[dim]No results.[/dim]")
            return

        if columns is None:
            columns = list(data[0].keys())

        table = Table(title=title, show_header=True)
        for col in columns:
            table.add_column(col.replace("_", " ").title())

        for row in data:
            table.add_row(*(str(row.get(col, "")) for col in columns))

        self.console.print(table)
