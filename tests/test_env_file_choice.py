"""Which env file a run uses, and why.

`.env` is the name every other tool in a directory also claims: docker compose reads it,
dotenv loaders read it, a colleague's script sources it. This CLI writes an API key and an
SSO token, and sets the file to 0600 while doing so, so writing there means changing the
permissions of a file that is not ours.

Hence `.env.zadctl` -- ours, and covered by the usual `.env*` ignore rule, so the token
stays out of git without anyone having to think of it.

The one thing that must not happen is a working setup breaking over a rename, so a `.env`
that already carries ZAD_ variables keeps being *read*. The first *write* splits the two
cases: a `.env` holding nothing but ours is renamed to `.env.zadctl`, with a line saying
so; one shared with other tools stays, and gets the recommendation instead of the move.
"""

from __future__ import annotations

import pytest

from zad_cli import envfile


@pytest.fixture(autouse=True)
def _here(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(envfile, "_wrote_legacy", False)
    monkeypatch.setattr(envfile, "_migrated_from", None)
    return tmp_path


def test_an_empty_directory_gets_the_new_name(_here):
    assert envfile.env_path() == _here / ".env.zadctl"
    assert not envfile.active_is_legacy()


def test_a_env_with_zad_variables_stays_the_file_in_use(_here):
    (_here / ".env").write_text("ZAD_PROJECT_ID=p1\n")

    assert envfile.env_path() == _here / ".env"
    assert envfile.active_is_legacy()
    assert envfile.read()["ZAD_PROJECT_ID"] == "p1"


def test_an_env_holding_only_ours_migrates_at_the_first_write(_here):
    """It was never anyone else's file; a move is what the recommendation always said."""
    (_here / ".env").write_text("# mijn notitie\nZAD_PROJECT_ID=p1\n")

    envfile.write({"ZAD_API_KEY": "k"})

    assert not (_here / ".env").exists()
    text = (_here / ".env.zadctl").read_text()
    assert "ZAD_PROJECT_ID=p1" in text and "ZAD_API_KEY=k" in text
    assert "# mijn notitie" in text, "a migration keeps the reader's own lines"


def test_the_migration_is_said_out_loud(_here):
    """Not silently: a file moving under you deserves one line naming both names."""
    (_here / ".env").write_text("ZAD_PROJECT_ID=p1\n")

    envfile.write({"ZAD_API_KEY": "k"})

    advice = envfile.legacy_advice()
    assert advice is not None
    assert ".env" in advice and ".env.zadctl" in advice
    assert "Moved" in advice


def test_someone_elses_env_is_not_ours(_here):
    (_here / ".env").write_text("DATABASE_URL=postgres://localhost/db\n")

    assert envfile.env_path() == _here / ".env.zadctl"

    envfile.write({"ZAD_API_KEY": "k"})

    assert (_here / ".env").read_text() == "DATABASE_URL=postgres://localhost/db\n"
    assert "ZAD_API_KEY=k" in (_here / ".env.zadctl").read_text()


def test_making_the_new_file_is_how_you_switch(_here):
    """Both present: the explicit one wins, without a flag or a migration step."""
    (_here / ".env").write_text("ZAD_PROJECT_ID=oud\n")
    (_here / ".env.zadctl").write_text("ZAD_PROJECT_ID=nieuw\n")

    assert envfile.env_path() == _here / ".env.zadctl"
    assert envfile.read()["ZAD_PROJECT_ID"] == "nieuw"


def test_the_recommendation_is_made_after_writing_to_a_shared_env(_here):
    """A `.env` other tools also read is not ours to move; it gets the advice instead."""
    (_here / ".env").write_text("DATABASE_URL=postgres://localhost/db\nZAD_PROJECT_ID=p1\n")
    assert envfile.legacy_advice() is None, "nothing has been written yet"

    envfile.write({"ZAD_API_KEY": "k"})

    assert (_here / ".env").exists(), "someone else's settings share it, so it stays"
    assert not (_here / ".env.zadctl").exists()
    advice = envfile.legacy_advice()
    assert advice is not None
    assert ".env.zadctl" in advice
    assert "0600" in advice, "say what we changed about their file, not only what we suggest"
    assert "not zadctl" in advice, "name why it stayed: the answer to 'why didn't it move?'"


def test_no_recommendation_when_we_write_our_own_file(_here):
    envfile.write({"ZAD_API_KEY": "k"})

    assert envfile.legacy_advice() is None
