import engine.web.app as web_app


def test_storage_is_offered_where_an_ssh_client_exists(monkeypatch):
    monkeypatch.setattr(web_app.shutil, "which", lambda name: "/usr/bin/ssh" if name == "ssh" else None)
    assert web_app.storage_available() is True


def test_storage_is_off_without_an_ssh_client(monkeypatch):
    """The deployed image ships no ssh client, so the web UI there must not offer storage."""
    monkeypatch.setattr(web_app.shutil, "which", lambda name: None)
    assert web_app.storage_available() is False
