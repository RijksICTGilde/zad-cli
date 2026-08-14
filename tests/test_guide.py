"""`zadctl guide`, and the checks that keep it from becoming a lie.

Two of these tests exist to fail the build: one when a new command does not reach the
guide, one when a setting in ``settings.py`` has no row in ``SETTING_DOCS``. A guide
nobody is forced to update is a guide that describes last quarter's CLI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from zad_cli import guide as guide_module
from zad_cli.cli import app
from zad_cli.guide import SECTION_NAMES, build_guide, command_tree, render_markdown, strip_markup
from zad_cli.settings import SETTING_DOCS

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


# --- Freshness: the two tests that fail the build ---


def test_every_command_appears_in_the_guide():
    """A command that is registered but not in the guide fails CI.

    The guide walks the same tree, so this can only break when someone replaces the walk
    with a list they maintain by hand — which is the thing this test forbids.
    """
    markdown = render_markdown(build_guide("https://api.example.com"))
    tree = command_tree()

    assert len(tree["commands"]) > 50, "the walk found suspiciously few commands"
    for command in tree["commands"]:
        assert f"zad {command['path']}" in markdown, f"missing from the guide: zad {command['path']}"


def test_every_command_in_zad_help_appears_in_the_guide():
    """The same claim, measured against `--help` instead of against the guide's own walk.

    The test above shares its source with the guide, so it can only catch a hand-written
    list. This one reads the help output of every group the way a user would, which is
    what "everything in `zad --help` is in the guide" actually means.
    """
    from tests.test_backwards_compat import extract_commands, run_help, strip_ansi

    markdown = render_markdown(build_guide("https://api.example.com"))
    groups = {group["path"] for group in command_tree()["groups"]}

    def check(path: str) -> None:
        result = run_help(*path.split())
        assert result.returncode == 0, result.stderr
        for name in extract_commands(strip_ansi(result.stdout)):
            child = f"{path} {name}".strip()
            assert f"zad {child}" in markdown, f"`zad {child}` is in --help but not in the guide"
            # A group's help lists its own subcommands; recurse until there are none left.
            if child in groups:
                check(child)

    check("")


def test_every_command_appears_in_the_json_structure():
    tree = command_tree()
    paths = {c["path"] for c in tree["commands"]}
    for expected in ("guide", "login", "project use", "deployment create", "service config set", "env add"):
        assert expected in paths


def test_every_setting_in_settings_py_is_documented():
    """Every ZAD_* variable settings.py reads has a row in the settings section."""
    source = Path(guide_module.__file__).with_name("settings.py").read_text()
    read_by_settings = set(re.findall(r"ZAD_[A-Z_]+", source)) - {"ZAD_"}
    # Names that only appear in the SETTING_DOCS table itself are what we are checking,
    # so compare against the docstring/precedence part too: any ZAD_* in the module.
    documented = {name for doc in SETTING_DOCS for name in doc.env}

    missing = read_by_settings - documented
    assert not missing, f"settings.py reads {sorted(missing)} but the guide never mentions it"


def test_settings_section_lists_every_resolved_setting():
    """Every key `Settings.resolve` reports a source for is in the guide."""
    from zad_cli.settings import Settings

    settings = Settings.resolve()
    section = build_guide("https://api.example.com", section="settings")["sections"][0]
    names = {record["setting"] for record in section["settings"]}

    for key in settings.sources:
        assert key in names, f"{key} is resolved but not documented"


def test_settings_flags_exist_on_the_cli():
    """A documented flag that no longer exists is worse than no documentation."""
    tree = command_tree()
    flags = {flag for option in tree["global_options"] for flag in option["flags"]}
    for doc in SETTING_DOCS:
        for flag in re.findall(r"--[a-z-]+", doc.flag):
            assert flag in flags, f"{doc.name} documents {flag}, which the CLI does not have"


# --- The command itself ---


def test_guide_prints_markdown_on_stdout():
    result = run("guide")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# zadctl guide")
    for heading in (
        "## Two kinds of credentials",
        "## The commands, in one map",
        "## Settings and where they come from",
    ):
        assert heading in result.stdout


def test_guide_markdown_carries_no_rich_markup():
    """This text is pasted into a prompt or a file; Rich tags would travel with it."""
    result = run("guide")
    assert result.exit_code == 0
    for tag in ("[bold]", "[/bold]", "[dim]", "[/dim]", "[green]"):
        assert tag not in result.stdout


def test_guide_json_is_structure_not_one_markdown_string():
    result = run("--output", "json", "guide", "--all")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    names = [section["name"] for section in payload["sections"]]
    assert names == list(SECTION_NAMES)

    commands = next(s for s in payload["sections"] if s["name"] == "commands")
    create = next(c for c in commands["commands"] if c["path"] == "deployment create")
    assert create["parameters"][0]["name"] == "deployment_name"
    assert create["parameters"][0]["kind"] == "argument"
    assert any("--dry-run" in p.get("flags", []) for p in create["parameters"])


def test_the_default_names_every_command_without_its_parameters():
    """What can this do is a different question from how do I call this one thing.

    Naming every command answers the first; repeating every parameter buries it, and is
    what `<command> --help` answers one command at a time.
    """
    result = run("--output", "json", "guide")
    payload = json.loads(result.stdout)
    commands = next(s for s in payload["sections"] if s["name"] == "commands")

    assert commands["compact"] is True
    create = next(c for c in commands["commands"] if c["path"] == "deployment create")
    assert create["summary"]
    assert "parameters" not in create


def test_all_is_much_longer_than_the_default():
    """If the two were close, the split would not be earning anything."""
    default = run("guide")
    everything = run("guide", "--all")
    assert len(everything.stdout) > 2 * len(default.stdout)


def test_guide_yaml_renders_the_same_structure():
    result = run("--output", "yaml", "guide", "--section", "settings")
    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["sections"][0]["name"] == "settings"


def test_section_limits_the_output():
    result = run("guide", "--section", "auth")
    assert result.exit_code == 0, result.output
    assert "## Two kinds of credentials" in result.stdout
    assert "zadctl deployment create" not in result.stdout


def test_unknown_section_names_the_valid_ones():
    result = run("guide", "--section", "bogus")
    assert result.exit_code != 0
    assert "auth" in result.output
    assert "commands" in result.output


def test_guide_works_without_credentials(monkeypatch: pytest.MonkeyPatch):
    """An agent has to be able to find out what ZAD is before it can log in."""
    for name in ("ZAD_API_KEY", "ZAD_PROJECT_ID", "ZAD_SSO_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    result = run("guide")
    assert result.exit_code == 0, result.output
    assert "## What ZAD is" in result.stdout


def test_guide_never_prints_a_key(monkeypatch: pytest.MonkeyPatch):
    """The guide says that an API key exists, never which one."""
    monkeypatch.setenv("ZAD_API_KEY", "sk-super-secret-value")
    result = run("guide")
    assert result.exit_code == 0
    assert "sk-super-secret-value" not in result.stdout


# --- Generated content ---


def test_examples_come_from_the_docstrings():
    tree = command_tree()
    create = next(c for c in tree["commands"] if c["path"] == "deployment create")
    assert any(example.startswith("zadctl deployment create staging") for example in create["examples"])


def test_services_come_from_the_registry_and_say_where_they_came_from():
    """With ZAD_CATALOG_OFFLINE set by conftest, the guide falls back to the snapshot."""
    section = build_guide("https://api.example.com", section="services")["sections"][0]
    assert section["source"] == "snapshot"
    names = {service["name"] for service in section["services"]}
    assert "postgresql-database" in names

    markdown = render_markdown({"sections": [section]})
    assert "snapshot bundled with the CLI" in markdown
    assert "postgresql-database" in markdown


def test_service_layers_come_from_the_catalog_entry():
    section = build_guide("https://api.example.com", section="services")["sections"][0]
    entry = next(s for s in section["services"] if s["name"] == "postgresql-database")
    assert entry["config_targets"] == ["project"]


def test_the_guide_points_at_the_walkthrough_document():
    """docs/proefrit.md stays; the guide refers to it instead of duplicating it."""
    markdown = render_markdown(build_guide("https://api.example.com", section="overview"))
    assert "docs/proefrit.md" in markdown
    assert Path(__file__).resolve().parents[1].joinpath("docs/proefrit.md").exists()


def test_markdown_lines_stay_readable_as_plain_text():
    """Only fenced example commands may run long; prose and tables are wrapped."""
    markdown = render_markdown(build_guide("https://api.example.com"))
    in_fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            assert len(line) <= 100, f"line too wide for a terminal: {line}"


def test_strip_markup_leaves_bracketed_prose_alone():
    assert strip_markup("[bold]Example:[/bold] a [env: ZAD_API_KEY] hint") == "Example: a [env: ZAD_API_KEY] hint"


def test_the_walkthrough_binds_a_service_to_a_component():
    """Configuring a service and binding it to a component are two things, and the guide
    used to show only the first.

    An agent followed it, ended with three components carrying `services: []`, and would
    have shipped an application that received no DATABASE_*, REDIS_* or S3_* variable at
    all -- while every command it ran had succeeded. Nothing warns about that, so the
    walkthrough has to.
    """
    workflow = build_guide("https://api.example.com", section="workflow")["sections"][0]
    text = " ".join(str(line) for line in workflow["paragraphs"])

    assert "--service" in text, "the walkthrough never binds a service to a component"
    assert "component add web --port 8080 --service" in text


def test_the_agent_notes_lead_with_the_confirmations():
    """A script that does not expect a prompt hangs on the first mutating command."""
    agents = build_guide("https://api.example.com", section="agents")["sections"][0]
    first_bullet = next(line for line in agents["paragraphs"] if str(line).startswith("- "))

    assert "yes" in first_bullet.lower()


def test_the_walkthrough_configures_services_before_components_use_them():
    """Two agents lost a run to this order.

    `component add --service keycloak` is refused until keycloak is configured at project
    level: "Services that must be enabled at project level first". The walkthrough used to
    show components first, which is the order that fails.
    """
    workflow = build_guide("https://api.example.com", section="workflow")["sections"][0]
    text = "\n".join(str(line) for line in workflow["paragraphs"])

    keycloak = text.index("service config set keycloak")
    component = text.index("component add web")
    assert keycloak < component, "the guide still tells you to add components before enabling keycloak"
