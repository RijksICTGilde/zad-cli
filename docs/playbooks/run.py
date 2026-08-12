#!/usr/bin/env python3
"""Play a playbook: run its shell blocks in order and report one line per step.

The playbook markdown is the only source. There is no second copy of the steps in a
script, because a script and a document drift apart and then nobody knows which one is
the playbook. Every ```sh block is executed, in one shell, so a variable set in step 2 is
still there in step 9.

A block that is an example rather than a step is marked in the fence:

    ```sh skip
    zad restore database productie backup --target-host "$DB_HOST" ...
    ```

Skipped blocks are reported as skipped, with the reason if the fence carries one
(```sh skip: needs credentials the platform does not hand out). A step that is silently
dropped is worse than a step that fails.

Usage:
    uv run python docs/playbooks/run.py 01-inrichten.md --zad ./zad
    uv run python docs/playbooks/run.py 01 --zad ./zad --from 5      # resume at step 5
    uv run python docs/playbooks/run.py 01 --list                    # show the steps only
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
FENCE = re.compile(r"^```sh(?P<flags>[^\n]*)$")
HEADING = re.compile(r"^(#{2,3})\s+(?P<title>.+?)\s*$")
# Which section tears things down again. Matched on the heading, because that is what a
# playbook names it; a step that deletes something mid-run lives under its own heading.
CLEANUP = re.compile(r"opruimen|cleanup", re.IGNORECASE)

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stderr.isatty() or os.environ.get("NO_COLOR"):
    GREEN = RED = YELLOW = DIM = RESET = ""


@dataclass
class Block:
    """One ```sh block, with the heading it sits under."""

    heading: str
    line: int
    code: str
    skip_reason: str | None = None


@dataclass
class Result:
    block: Block
    status: str  # ok | failed | skipped
    seconds: float = 0.0
    output: str = ""
    failing_line: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    @property
    def failed(self) -> list[Result]:
        return [r for r in self.results if r.status == "failed"]

    @property
    def skipped(self) -> list[Result]:
        return [r for r in self.results if r.status == "skipped"]


def parse(path: Path) -> list[Block]:
    """Every ```sh block in the file, in order, tagged with its nearest heading."""
    blocks: list[Block] = []
    heading = "(no heading)"
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match_heading = HEADING.match(line)
        if match_heading:
            heading = match_heading.group("title")
            i += 1
            continue
        match_fence = FENCE.match(line)
        if not match_fence:
            i += 1
            continue

        flags = match_fence.group("flags").strip()
        start = i + 1
        end = start
        while end < len(lines) and lines[end].rstrip() != "```":
            end += 1
        code = "\n".join(lines[start:end])

        reason = None
        if flags.startswith("skip"):
            reason = flags[len("skip") :].lstrip(": ").strip() or "marked skip"
        blocks.append(Block(heading=heading, line=start, code=code, skip_reason=reason))
        i = end + 1
    return blocks


def resolve(name: str) -> Path:
    """Accept `01`, `01-inrichten`, `01-inrichten.md`, or a path."""
    candidate = Path(name)
    if candidate.is_file():
        return candidate
    for pattern in (f"{name}", f"{name}.md", f"{name}*.md"):
        matches = sorted(HERE.glob(pattern))
        matches = [m for m in matches if not m.name.endswith("-bevindingen.md")]
        if matches:
            return matches[0]
    raise SystemExit(f"No playbook matching {name!r} in {HERE}")


def run_block(block: Block, workdir: Path, env: dict[str, str], state: Path) -> Result:
    """Run one block, carrying shell variables over from the previous one.

    Variables are carried by sourcing a state file before and dumping it after, which is
    what makes `URL=$(...)` in one step usable in the next without turning the whole
    playbook into a single unreadable script.
    """
    # `set -a` exports every assignment, which is what makes `IMG=...` in step 0 survive
    # into step 6: the state file is a dump of exported variables, and a playbook writes
    # plain assignments the way a person would, without `export` in front of them.
    script = f"""
set -o pipefail
[ -f {state} ] && . {state}
set -a
# Also on the way out: a block that fails halfway has still set the variables above the
# line that gave up, and without them every later step reports a follow-on error about an
# empty variable instead of its own result.
trap 'declare -px > {state} 2>/dev/null || true' EXIT
set -e
{block.code}
"""
    started = time.monotonic()
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    output = (proc.stdout + proc.stderr).strip()

    if proc.returncode == 0:
        return Result(block, "ok", elapsed, output)

    # Which line gave up: bash reports it on stderr for `set -e`, but not always, so fall
    # back to the whole block rather than claiming a line we did not identify.
    failing = ""
    for candidate in block.code.splitlines():
        stripped = candidate.strip()
        if stripped and not stripped.startswith("#"):
            failing = stripped
            break
    return Result(block, "failed", elapsed, output, failing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("playbook", help="01, 01-inrichten, or a path to the markdown")
    parser.add_argument("--zad", default="zad", help="The zad command to put on PATH (default: zad)")
    parser.add_argument("--workdir", help="Where to run (default: a fresh temp dir)")
    parser.add_argument("--from", dest="start", type=int, default=1, help="Resume at this step number")
    parser.add_argument("--list", action="store_true", help="Show the steps without running anything")
    parser.add_argument("--keep-going", action="store_true", help="Do not stop at the first failure")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Skip the cleanup steps, so the project stays up for you to look at",
    )
    args = parser.parse_args()

    path = resolve(args.playbook)
    blocks = parse(path)

    if args.list:
        for number, block in enumerate(blocks, 1):
            mark = f" {DIM}(skip: {block.skip_reason}){RESET}" if block.skip_reason else ""
            first = next((line for line in block.code.splitlines() if line.strip()), "")
            print(f"{number:3d}. {block.heading}{mark}")
            print(f"     {DIM}{first[:96]}{RESET}")
        return 0

    workdir = (
        Path(args.workdir).resolve() if args.workdir else Path(os.environ.get("TMPDIR", "/tmp")) / f"pb-{os.getpid()}"
    )
    workdir.mkdir(parents=True, exist_ok=True)

    zad = Path(args.zad).resolve() if os.sep in args.zad else args.zad
    # PLAYBOOKS lets a step reach its own helper scripts: the working directory is not the
    # repo, so a path relative to the repo root finds nothing.
    env = {**os.environ, "ZAD": str(zad), "PLAYBOOKS": str(HERE), "NO_COLOR": "1"}
    if os.sep in str(zad):
        # A wrapper script lives somewhere else; put it on PATH under the name `zad` so
        # the playbook can say `zad` like a person would.
        bindir = workdir / ".bin"
        bindir.mkdir(exist_ok=True)
        link = bindir / "zad"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(zad)
        env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"

    state = workdir / ".playbook-state"
    if state.exists():
        state.unlink()

    print(f"{path.name}  in {workdir}", file=sys.stderr)
    report = Report()

    for number, block in enumerate(blocks, 1):
        if number < args.start:
            continue
        label = f"{number:3d}. {block.heading}"

        # A cleanup step is the one thing you do not want when you came to look at the
        # result: the playbooks tear down what they built, so within a minute of a green
        # run the cluster is empty again and there is nothing left to inspect.
        reason = block.skip_reason
        if args.keep and CLEANUP.search(block.heading):
            reason = "--keep: left standing for inspection"

        if reason:
            print(f"{YELLOW}skip{RESET} {label}  {DIM}{reason}{RESET}", file=sys.stderr)
            report.results.append(Result(block, "skipped"))
            continue

        print(f"{DIM} run{RESET} {label}", end="", file=sys.stderr, flush=True)
        print("\r" + " " * (len(label) + 6) + "\r", end="", file=sys.stderr, flush=True)
        result = run_block(block, workdir, env, state)
        report.results.append(result)

        if result.status == "ok":
            print(f"{GREEN}  ok{RESET} {label}  {DIM}{result.seconds:.0f}s{RESET}", file=sys.stderr)
            continue

        print(f"{RED}FAIL{RESET} {label}  {DIM}{path.name}:{block.line}{RESET}", file=sys.stderr)
        if result.failing_line:
            print(f"      {DIM}{result.failing_line}{RESET}", file=sys.stderr)
        for line in result.output.splitlines()[-12:]:
            print(f"      {line}", file=sys.stderr)
        if not args.keep_going:
            break

    # The playbooks say the cleanup runs even when something failed, and until now that was
    # only true of the person following them by hand: a run that stopped early left its
    # project on the cluster, where it costs money, blocks the next run's names, and has to
    # be found by whoever notices. So the teardown gets its turn regardless.
    done = {id(r.block) for r in report.results}
    leftover = [b for b in blocks if CLEANUP.search(b.heading) and id(b) not in done and not b.skip_reason]
    if leftover and not args.keep:
        print(f"{DIM}cleaning up what the run created{RESET}", file=sys.stderr)
        for block in leftover:
            result = run_block(block, workdir, env, state)
            report.results.append(Result(block, "cleanup-ok" if result.status == "ok" else "cleanup-failed"))
            if result.status != "ok":
                print(f"{RED}Cleanup failed{RESET} {DIM}{path.name}:{block.line}{RESET}", file=sys.stderr)
                for line in result.output.splitlines()[-6:]:
                    print(f"      {line}", file=sys.stderr)

    print("", file=sys.stderr)
    ran = [r for r in report.results if r.status in ("ok", "failed")]
    ok = len([r for r in ran if r.status == "ok"])
    summary = f"{ok}/{len(ran)} steps ok"
    if report.skipped:
        summary += f", {len(report.skipped)} skipped"
    if report.failed:
        summary += f", {len(report.failed)} failed"
    stuck = [r for r in report.results if r.status == "cleanup-failed"]
    if stuck:
        # Loud, and its own line: this is the one outcome that leaves something behind on a
        # shared cluster, and a run that says nothing about it is how the leftovers pile up.
        summary += f", {len(stuck)} CLEANUP FAILED (a project may still be on the cluster)"
    print(f"{RED if report.failed else GREEN}{summary}{RESET}  ({workdir})", file=sys.stderr)
    if args.keep:
        print(f"{DIM}Left standing. Look with: cd {workdir} && zad project status{RESET}", file=sys.stderr)
        print(f"{DIM}Remove it with: cd {workdir} && zad project delete{RESET}", file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
