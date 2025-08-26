"""Lightweight wrapper around the OpenAI API.

This module centralises access to the ChatGPT ``gpt-4o-mini`` model.  It
expects the ``OPENAI_API_KEY`` environment variable to be set.  The
``constants`` module exposes ``LLM_API_KEY`` and ``LLM_MODEL`` which are used
here to create the client lazily so tests that do not require the API do not
attempt to connect.
"""

from __future__ import annotations

try:  # New style OpenAI client (>=1.0)
    from openai import OpenAI
except Exception:  # pragma: no cover - package may be absent or legacy version
    OpenAI = None  # type: ignore

try:  # Legacy package (<1.0) exposes a module level API
    import openai as openai_legacy  # type: ignore
except Exception:  # pragma: no cover - package may be absent
    openai_legacy = None  # type: ignore

from constants import LLM_API_KEY, LLM_MODEL

# The cached client may either be an ``OpenAI`` instance or the legacy
# ``openai`` module depending on which package is available at runtime.
_client: object | None = None


def get_client() -> object:
    """Return a cached OpenAI client.

    The client is initialised on first use.  A ``RuntimeError`` is raised when
    no API key is configured to make failures explicit.
    """

    global _client
    if _client is None:
        if not LLM_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if OpenAI is not None:
            _client = OpenAI(api_key=LLM_API_KEY)
        elif openai_legacy is not None:
            openai_legacy.api_key = LLM_API_KEY
            _client = openai_legacy
        else:
            raise RuntimeError("openai package is not installed")
    return _client


def complete(prompt: str) -> str:
    """Generate a response for ``prompt`` using the configured model or assistant."""

    client = get_client()
    # ``OpenAI`` client exposes a ``responses`` attribute.  The legacy module
    # uses a module level ``ChatCompletion`` factory.  Supporting both avoids
    # silent failures where the bot always returns the fallback acknowledgement
    # if only the old package is installed.
    if hasattr(client, "responses"):
        response = client.responses.create(model=LLM_MODEL, input=prompt)
        return response.output_text

    response = client.ChatCompletion.create(
        model=LLM_MODEL, messages=[{"role": "user", "content": prompt}]
    )
    return response["choices"][0]["message"]["content"]
