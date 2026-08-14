"""Which env file a run uses, and why.

`.env` is the name every other tool in a directory also claims: docker compose reads it,
dotenv loaders read it, a colleague's script sources it. This CLI writes an API key and an
SSO token, and sets the file to 0600 while doing so, so writing there means changing the
permissions of a file that is not ours.

Hence `.env.zadctl` -- ours, and covered by the usual `.env*` ignore rule, so the token
stays out of git without anyone having to think of it.

The one thing that must not happen is a working setup breaking over a rename, so a `.env`
that already carries ZAD_ variables keeps being read *and written*. It gets a
recommendation, not a migration.
"""

from __future__ import annotations

import pytest

from zad_cli import envfile


@pytest.fixture(autouse=True)
def _here(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(envfile, "_wrote_legacy", False)
    return tmp_path


def test_an_empty_directory_gets_the_new_name(_here):
    assert envfile.env_path() == _here / ".env.zadctl"
    assert not envfile.active_is_legacy()


def test_a_env_with_zad_variables_stays_the_file_in_use(_here):
    (_here / ".env").write_text("ZAD_PROJECT_ID=p1\n")

    assert envfile.env_path() == _here / ".env"
    assert envfile.active_is_legacy()
    assert envfile.read()["ZAD_PROJECT_ID"] == "p1"


def test_writes_keep_going_to_that_same_env(_here):
    (_here / ".env").write_text("ZAD_PROJECT_ID=p1\n")

    envfile.write({"ZAD_API_KEY": "k"})

    assert "ZAD_API_KEY=k" in (_here / ".env").read_text()
    assert not (_here / ".env.zadctl").exists(), "a setup that worked must not be moved out from under it"


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
    (_here / ".env").write_text("ZAD_PROJECT_ID=p1\n")
    assert envfile.legacy_advice() is None, "nothing has been written yet"

    envfile.write({"ZAD_API_KEY": "k"})

    advice = envfile.legacy_advice()
    assert advice is not None
    assert ".env.zadctl" in advice
    assert "0600" in advice, "say what we changed about their file, not only what we suggest"


def test_no_recommendation_when_we_write_our_own_file(_here):
    envfile.write({"ZAD_API_KEY": "k"})

    assert envfile.legacy_advice() is None
