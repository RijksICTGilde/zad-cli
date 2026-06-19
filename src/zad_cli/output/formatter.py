"""Output formatting: table, json, yaml."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from zad_cli.api.errors import Diagnosis

# Console for stderr (status messages), stdout is for data output
err_console = Console(stderr=True)


def _supports_unicode() -> bool:
    """True if stderr can render unicode glyphs. CI logs with ascii encoding get ascii fallbacks."""
    enc = (getattr(sys.stderr, "encoding", None) or "").lower()
    return "utf" in enc


def _glyphs() -> tuple[str, str, str]:
    """Return (error, warning, arrow) glyphs, ascii-safe when unicode isn't available."""
    if _supports_unicode():
        return "✗", "⚠", "→"  # ✗  ⚠  →
    return "x", "!", "->"


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

    def render_diagnosis(self, diagnosis: Diagnosis) -> None:
        """Render a failure diagnosis: source-labelled, with details and next steps.

        In json mode the structured diagnosis goes to stdout (the command failed, so
        there is no other stdout payload; automation branches on the ``fault`` key).
        In table mode it renders to stderr.
        """
        if self.fmt == "json":
            print(json.dumps(diagnosis.to_dict(), indent=2, default=str))
            return
        cross, _, _ = _glyphs()
        self._diagnosis_block(diagnosis, glyph=cross, header_color=diagnosis.color)

    def render_warnings(self, diagnoses: list[Diagnosis]) -> None:
        """Render degraded-but-successful warnings to stderr (never blocks stdout data).

        In json mode the result payload is already on stdout, so warnings go to stderr
        as a single JSON object to keep stdout a valid single document.
        """
        if not diagnoses:
            return
        if self.fmt == "json":
            payload = {"warnings": [d.to_dict() for d in diagnoses]}
            print(json.dumps(payload, indent=2, default=str), file=sys.stderr)
            return
        _, warn, _ = _glyphs()
        for diagnosis in diagnoses:
            self._diagnosis_block(diagnosis, glyph=warn, header_color="yellow")

    def _diagnosis_block(self, diagnosis: Diagnosis, *, glyph: str, header_color: str) -> None:
        """Shared stderr layout for diagnoses and warnings."""
        _, _, arrow = _glyphs()
        err_console.print(f"[{header_color}]{glyph} {escape(diagnosis.headline)}[/{header_color}]")
        err_console.print(f"  [dim]Source:[/dim] {escape(diagnosis.source)}")
        if diagnosis.summary:
            err_console.print(f"\n  {escape(diagnosis.summary)}")
        if diagnosis.details:
            err_console.print()
            for line in diagnosis.details:
                err_console.print(f"  {escape(line)}")
        if diagnosis.next_steps:
            err_console.print()
            for step in diagnosis.next_steps:
                err_console.print(f"  [cyan]{arrow}[/cyan] {escape(step)}")
        err_console.print()

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
