"""The Studio session token survives restarts (open tabs keep working) and is private to the user."""
import os
import stat

from studio import server as S


def test_token_persists_rotates_and_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "TOKEN_FILE", tmp_path / "studio" / "session-token")
    a = S.persistent_token()
    assert a == S.persistent_token()                               # restart: same token, open tabs stay signed in
    assert stat.S_IMODE(os.stat(S.TOKEN_FILE).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(S.TOKEN_FILE.parent).st_mode) == 0o700
    b = S.persistent_token(rotate=True)
    assert b != a and len(b) >= 32


def test_a_world_readable_token_file_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "TOKEN_FILE", tmp_path / "studio" / "session-token")
    a = S.persistent_token()
    os.chmod(S.TOKEN_FILE, 0o644)
    assert S.persistent_token() != a
