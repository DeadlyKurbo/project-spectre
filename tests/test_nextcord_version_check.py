import importlib

import pytest
import nextcord
import main


def test_requires_modern_nextcord(monkeypatch):
    orig = nextcord.__version__
    monkeypatch.setattr(nextcord, "__version__", "2.5.0a1")
    with pytest.raises(RuntimeError):
        importlib.reload(main)
    monkeypatch.setattr(nextcord, "__version__", orig, raising=False)
    importlib.reload(main)
