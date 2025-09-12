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
    if hasattr(client, "responses"):
        resp = client.responses.create(model=LLM_MODEL, input=prompt)
        return resp.output_text
    elif hasattr(client, "chat"):
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
        if isinstance(resp, dict):
            return resp["choices"][0]["message"]["content"]
        return resp.choices[0].message["content"]
    else:
        raise RuntimeError("Geen geldige OpenAI client gevonden")


def run_assistant(
    message: str,
    *,
    poll_interval: float = 1.0,
    timeout: float = 60.0,
    max_poll_interval: float | None = None,
) -> str:
    """Gebruik de Assistants API als LLM_ASSISTANT_ID beschikbaar is.

    To limit network egress the run status is polled with an exponential
    backoff. A timeout and explicit failure-state handling ensure that the
    function exits even if the API stops responding or reports an error.
    ``max_poll_interval`` caps the backoff so that waits never grow without
    bound.
    """
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
        assistant_id=LLM_ASSISTANT_ID,
    )

    # 3. Wacht tot hij klaar is met een timeout en backoff-strategie
    start = time.monotonic()
    max_poll_interval = max_poll_interval or poll_interval * 4
    wait = poll_interval
    while True:
        if time.monotonic() - start >= timeout:
            raise TimeoutError("Assistant run timed out")
        time.sleep(wait)
        status = client.beta.threads.runs.retrieve(
            thread_id=thread.id, run_id=run.id
        )
        if status.status == "completed":
            break
        if status.status in {"failed", "cancelled", "cancelling"}:
            raise RuntimeError(f"Assistant run ended with status: {status.status}")
        wait = min(wait * 2, max_poll_interval)

    # 4. Pak het laatste bericht van de assistant
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    for msg in reversed(messages.data):
        if msg.role == "assistant":
            return msg.content[0].text.value

    return "No response from assistant"
