import os
os.environ.setdefault("GUILD_ID", "1")
import llm_client
import types
import pytest


def test_complete_responses_client(monkeypatch):
    called = {}

    class DummyClient:
        def __init__(self):
            self.responses = self

        def create(self, **kwargs):
            called.update(kwargs)
            class Resp:
                output_text = "resp"

            return Resp()

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {"model": "gpt-test", "input": "hi"}


def test_complete_legacy_chat_completion(monkeypatch):
    called = {}

    class DummyLegacy:
        class ChatCompletion:
            @staticmethod
            def create(**kwargs):
                called.update(kwargs)
                return {"choices": [{"message": {"content": "resp"}}]}

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyLegacy())
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}]
    }


def test_run_assistant_handles_failure(monkeypatch):
    """Run should raise when the assistant reports a failure state."""
    calls = {"retrieve": 0}

    class DummyRunSteps:
        @staticmethod
        def list(**kwargs):  # pragma: no cover - should not be called
            raise AssertionError("runs.steps.list should not be called")

    class DummyRuns:
        def __init__(self):
            self.steps = DummyRunSteps()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="run")

        def retrieve(self, **kwargs):
            calls["retrieve"] += 1
            return types.SimpleNamespace(status="failed")

    class DummyThreads:
        def __init__(self):
            self.runs = DummyRuns()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="thread")

        class messages:  # pragma: no cover - should not be called
            @staticmethod
            def retrieve(**kwargs):
                raise AssertionError("messages.retrieve should not be called")

    client = types.SimpleNamespace(beta=types.SimpleNamespace(threads=DummyThreads()))

    counter = {"t": 0}

    def sleep(x):
        counter["t"] += x

    def monotonic():
        return counter["t"]

    monkeypatch.setattr(llm_client, "get_client", lambda: client)
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(
        llm_client,
        "time",
        types.SimpleNamespace(monotonic=monotonic, sleep=sleep),
    )

    with pytest.raises(RuntimeError):
        llm_client.run_assistant("hi", timeout=5, poll_interval=1)

    assert calls["retrieve"] == 1


def test_run_assistant_times_out(monkeypatch):
    """Run should time out when the assistant never completes."""
    calls = {"retrieve": 0}

    class DummyRunSteps:
        @staticmethod
        def list(**kwargs):  # pragma: no cover - should not be called
            raise AssertionError("runs.steps.list should not be called")

    class DummyRuns:
        def __init__(self):
            self.steps = DummyRunSteps()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="run")

        def retrieve(self, **kwargs):
            calls["retrieve"] += 1
            return types.SimpleNamespace(status="queued")

    class DummyThreads:
        def __init__(self):
            self.runs = DummyRuns()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="thread")

        class messages:  # pragma: no cover - should not be called
            @staticmethod
            def retrieve(**kwargs):
                raise AssertionError("messages.retrieve should not be called")

    client = types.SimpleNamespace(beta=types.SimpleNamespace(threads=DummyThreads()))

    counter = {"t": 0}

    def sleep(x):
        counter["t"] += x

    def monotonic():
        return counter["t"]

    monkeypatch.setattr(llm_client, "get_client", lambda: client)
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(
        llm_client,
        "time",
        types.SimpleNamespace(monotonic=monotonic, sleep=sleep),
    )

    with pytest.raises(TimeoutError):
        llm_client.run_assistant("hi", timeout=2, poll_interval=1, max_poll_interval=1)

    assert calls["retrieve"] == 2


def test_run_assistant_returns_message(monkeypatch):
    """Run should return the assistant message via run steps."""
    class DummyRunSteps:
        @staticmethod
        def list(**kwargs):
            step = types.SimpleNamespace(
                step_details=types.SimpleNamespace(
                    type="message_creation",
                    message_creation=types.SimpleNamespace(message_id="m1"),
                ),
                type="message_creation",
            )
            return types.SimpleNamespace(data=[step])

    class DummyRuns:
        def __init__(self):
            self.steps = DummyRunSteps()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="run")

        def retrieve(self, **kwargs):
            return types.SimpleNamespace(status="completed")

    class DummyMessages:
        @staticmethod
        def retrieve(**kwargs):
            return types.SimpleNamespace(
                content=[
                    types.SimpleNamespace(
                        type="text",
                        text=types.SimpleNamespace(value="resp"),
                    )
                ]
            )

    class DummyThreads:
        def __init__(self):
            self.runs = DummyRuns()
            self.messages = DummyMessages()

        def create(self, **kwargs):
            return types.SimpleNamespace(id="thread")

    client = types.SimpleNamespace(beta=types.SimpleNamespace(threads=DummyThreads()))

    counter = {"t": 0}

    def sleep(x):
        counter["t"] += x

    def monotonic():
        return counter["t"]

    monkeypatch.setattr(llm_client, "get_client", lambda: client)
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(
        llm_client,
        "time",
        types.SimpleNamespace(monotonic=monotonic, sleep=sleep),
    )

    out = llm_client.run_assistant("hi", timeout=2, poll_interval=1)
    assert out == "resp"
