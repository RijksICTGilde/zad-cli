"""Tests for output formatting."""

import json

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
