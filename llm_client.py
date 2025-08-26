"""Lightweight wrapper around the OpenAI API for Project Spectre.

Ondersteunt zowel directe model-calls als de nieuwe Assistants API
als een LLM_ASSISTANT_ID in .env staat.
"""

from __future__ import annotations
import os
import time

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

try:
    import openai as openai_legacy
except Exception:
    openai_legacy = None  # type: ignore

from constants import LLM_API_KEY, LLM_MODEL, LLM_ASSISTANT_ID

_client: object | None = None


def get_client() -> object:
    """Return a cached OpenAI client."""
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
    """Fallback: gebruik gewoon model calls zoals voorheen."""
    client = get_client()

    # legacy API of modern API?
    if hasattr(client, "chat"):
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    elif hasattr(client, "ChatCompletion"):
        resp = client.ChatCompletion.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message["content"]
    else:
        raise RuntimeError("Geen geldige OpenAI client gevonden")


def run_assistant(message: str) -> str:
    """Gebruik de Assistants API als LLM_ASSISTANT_ID beschikbaar is."""
    if not LLM_ASSISTANT_ID:
        # fallback naar gewoon model
        return complete(message)

    client = get_client()

    # 1. Maak een thread
    thread = client.beta.threads.create(
        messages=[{"role": "user", "content": message}]
    )

    # 2. Run de assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=LLM_ASSISTANT_ID
    )

    # 3. Wacht tot hij klaar is
    while True:
        status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if status.status == "completed":
            break
        time.sleep(1)

    # 4. Pak het laatste bericht van de assistant
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    for msg in reversed(messages.data):
        if msg.role == "assistant":
            return msg.content[0].text.value

    return "No response from assistant"
