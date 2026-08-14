"""Tests for output formatting."""

import json

import yaml

from zad_cli.api.errors import Diagnosis, Fault
from zad_cli.output.formatter import OutputFormatter


def test_json_output(capsys):
    fmt = OutputFormatter(fmt="json")
    fmt.render({"key": "value"})
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["key"] == "value"


def test_json_output_list(capsys):
    fmt = OutputFormatter(fmt="json")
    fmt.render([{"name": "a"}, {"name": "b"}])
    output = capsys.readouterr().out
    data = json.loads(output)
    assert len(data) == 2
    assert data[0]["name"] == "a"


def test_yaml_output(capsys):
    fmt = OutputFormatter(fmt="yaml")
    fmt.render({"key": "value"})
    output = capsys.readouterr().out
    assert "key: value" in output


def test_table_output_empty(capsys):
    fmt = OutputFormatter(fmt="table")
    fmt.render([])
    # Should print "No results." to stderr
    err = capsys.readouterr().err
    assert "No results" in err


def test_render_detail_json(capsys):
    fmt = OutputFormatter(fmt="json")
    fmt.render_detail({"status": "healthy", "version": "1.0"})
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["status"] == "healthy"


def test_render_text(capsys):
    fmt = OutputFormatter(fmt="table")
    fmt.render_text("line1\nline2")
    output = capsys.readouterr().out
    assert "line1" in output
    assert "line2" in output


def test_render_error_json(capsys):
    fmt = OutputFormatter(fmt="json")
    fmt.render_error("something broke", details={"code": 500})
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["error"] == "something broke"
    assert data["details"]["code"] == 500


def test_render_error_table(capsys):
    fmt = OutputFormatter(fmt="table")
    fmt.render_error("something broke")
    err = capsys.readouterr().err
    assert "something broke" in err


def _sample_diagnosis() -> Diagnosis:
    return Diagnosis(
        fault=Fault.USER_APP,
        headline="Your application failed to run on the cluster.",
        summary="deployment failed",
        details=["web (ImagePull): back-off pulling image"],
        next_steps=["Inspect `zadctl logs`."],
        status_code=None,
    )


def test_render_diagnosis_json_goes_to_stdout(capsys):
    fmt = OutputFormatter(fmt="json")
    fmt.render_diagnosis(_sample_diagnosis())
    out = capsys.readouterr().out  # failure has no other stdout payload -> diagnosis to stdout
    data = json.loads(out)
    assert data["fault"] == "UserApp"
    assert data["source"] == "your application (cluster runtime)"
    assert data["details"] == ["web (ImagePull): back-off pulling image"]


def test_render_diagnosis_table_goes_to_stderr(capsys):
    fmt = OutputFormatter(fmt="table")
    fmt.render_diagnosis(_sample_diagnosis())
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays clean for pipelines
    assert "Your application failed to run" in captured.err
    assert "Source: your application" in captured.err
    assert "Inspect" in captured.err


def test_render_warnings_json_goes_to_stderr(capsys):
    # The result payload is already on stdout, so warnings must not corrupt it.
    fmt = OutputFormatter(fmt="json")
    fmt.render_warnings([_sample_diagnosis()])
    captured = capsys.readouterr()
    assert captured.out == ""
    data = json.loads(captured.err)
    assert data["warnings"][0]["fault"] == "UserApp"


def test_render_warnings_empty_is_noop(capsys):
    OutputFormatter(fmt="table").render_warnings([])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_an_encrypted_blob_is_described_rather_than_printed():
    """`component update` used to scroll pages of AGE ciphertext past you.

    The answer to "what did it do?" disappeared behind a value nobody can read and nobody
    wants. Describing it stays honest -- something is stored, this much of it -- without
    pretending the bytes are information.
    """
    from zad_cli.output.formatter import describe_ciphertext

    blob = "-----BEGIN AGE ENCRYPTED FILE-----\n" + "YWJj\n" * 40 + "-----END AGE ENCRYPTED FILE-----"

    described = describe_ciphertext(f"aliases: {blob}")

    assert "BEGIN AGE" not in described
    assert described.startswith("aliases: (encrypted, ")
    assert "bytes)" in described


def test_text_without_ciphertext_is_left_exactly_as_it_is():
    from zad_cli.output.formatter import describe_ciphertext

    assert describe_ciphertext("plain value") == "plain value"


def _narrow(fmt: OutputFormatter, width: int = 60) -> None:
    """Pin the console width, so the test does not depend on the terminal running it."""
    from rich.console import Console

    fmt.console = Console(width=width, force_terminal=False)


def test_a_long_value_is_folded_rather_than_cut(capsys):
    """No ellipsis, ever. A URL is one unbreakable word, so wrapping cannot shorten it and
    Rich's default `overflow="ellipsis"` quietly ate the end: `config list` reported the
    sandbox API as `https://zad.sandbox.rijks…`, which you cannot copy, cannot compare, and
    cannot tell apart from a shorter URL that really ends there."""
    url = "https://zad.sandbox.rijksapp.dev/api/v2/operations-manager"
    fmt = OutputFormatter(fmt="table")
    _narrow(fmt)
    fmt.render({"api_url": url})

    out = capsys.readouterr().out
    assert "…" not in out and "..." not in out
    # Folded over several lines, so the table's own borders sit in between: compare on the
    # characters rather than on the layout.
    assert url in "".join(ch for ch in out if ch not in "|\n \r")


def test_a_long_value_in_a_multi_row_table_is_folded_too(capsys):
    """The record view and the list view answer the same way; one of the two folding is
    how a value looks whole in `describe` and cut in `list`."""
    url = "https://zad.sandbox.rijksapp.dev/api/v2/operations-manager"
    fmt = OutputFormatter(fmt="table")
    _narrow(fmt)
    fmt.render([{"name": "a", "url": url}, {"name": "b", "url": url}], columns=["name", "url"])

    out = capsys.readouterr().out
    assert "…" not in out
    assert url in "".join(ch for ch in out if ch not in "|\n \r")


def test_a_value_with_brackets_arrives_whole(capsys):
    """Rich reads `[a-z0-9]` as a style tag and drops it. A config `pattern` showed it
    worst -- `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$` arrived as `^([-a-z0-9]*)?$`, wrong in a way
    the reader cannot see -- but any API value may carry brackets."""
    pattern = "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    fmt = OutputFormatter(fmt="table")
    _narrow(fmt, width=120)
    fmt.render({"pattern": pattern})

    assert pattern in capsys.readouterr().out


def test_the_cells_this_cli_colours_itself_still_colour(capsys):
    """The exception to escaping is the handful of cells we build as markup on purpose."""
    from zad_cli.output.formatter import Markup

    fmt = OutputFormatter(fmt="table")
    _narrow(fmt, width=120)
    fmt.console.no_color = False
    fmt.render({"issues": Markup("[red]2 platform[/red]")})

    out = capsys.readouterr().out
    # The tags are consumed as style, not printed as text.
    assert "[red]" not in out
    assert "2 platform" in out


def test_a_markup_cell_is_a_plain_string_in_yaml(capsys):
    """pyyaml looks its representer up by exact type, so a str subclass would be written as
    `!!python/object/new:` -- a document no reader of ours expects."""
    from zad_cli.output.formatter import Markup

    fmt = OutputFormatter(fmt="yaml")
    fmt.render({"issues": Markup("[red]2 platform[/red]")})

    out = capsys.readouterr().out
    assert "python/object" not in out
    assert yaml.safe_load(out) == {"issues": "[red]2 platform[/red]"}
