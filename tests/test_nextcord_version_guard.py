import pytest

import main


def test_nextcord_version_accepts_post_release(monkeypatch):
    monkeypatch.setattr(main.nextcord, "__version__", "2.6.0.post1")
    # Should not raise for post releases or other suffixes.
    main._ensure_nextcord_version()


def test_nextcord_version_rejects_old_release(monkeypatch):
    monkeypatch.setattr(main.nextcord, "__version__", "2.5.9")
    with pytest.raises(RuntimeError, match=r"Nextcord 2\.6\.0\+ is required"):
        main._ensure_nextcord_version()


def test_nextcord_version_invalid(monkeypatch):
    monkeypatch.setattr(main.nextcord, "__version__", "invalid-version")
    with pytest.raises(RuntimeError, match="Unable to parse Nextcord version"):
        main._ensure_nextcord_version()
