"""Lightweight wrapper around the OpenAI API.

This module centralises access to the ChatGPT ``gpt-4o-mini`` model.  It
expects the ``OPENAI_API_KEY`` environment variable to be set.  The
``constants`` module exposes ``LLM_API_KEY`` and ``LLM_MODEL`` which are used
here to create the client lazily so tests that do not require the API do not
attempt to connect.
"""

from __future__ import annotations

from openai import OpenAI

from constants import LLM_API_KEY, LLM_MODEL

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Return a cached OpenAI client.

    The client is initialised on first use.  A ``RuntimeError`` is raised when
    no API key is configured to make failures explicit.
    """

    global _client
    if _client is None:
        if not LLM_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=LLM_API_KEY)
    return _client


def complete(prompt: str) -> str:
    """Generate a response for ``prompt`` using the configured model."""

    client = get_client()
    response = client.responses.create(model=LLM_MODEL, input=prompt)
    return response.output_text
