"""Progress display for task polling."""

from __future__ import annotations

from rich.console import Console

from zad_cli.api.models import TaskStatus

err_console = Console(stderr=True)


class TaskProgress:
    """Display task polling progress with a Rich spinner."""

    def __init__(self, *, silent: bool = False):
        self.silent = silent
        self._status = err_console.status("Waiting...") if not silent else None

    def __enter__(self) -> TaskProgress:
        if self._status:
            self._status.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        if self._status:
            self._status.__exit__(*args)

    def update(self, task_status: TaskStatus) -> None:
        """Update the spinner with current task status."""
        if self.silent or not self._status:
            return

        parts = [task_status.status]
        if task_status.current_step:
            parts.append(task_status.current_step)
        if task_status.progress_percent is not None:
            parts.append(f"{task_status.progress_percent}%")

        self._status.update(" - ".join(parts))
