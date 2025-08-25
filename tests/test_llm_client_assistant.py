import llm_client


def test_complete_uses_assistant_id(monkeypatch):
    called = {}

    class DummyResp:
        output_text = "resp"

    class DummyClient:
        def __init__(self):
            self.responses = self
        def create(self, **kwargs):
            called.update(kwargs)
            return DummyResp()

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "asst_123")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {"assistant_id": "asst_123", "input": "hi"}


def test_complete_uses_model_when_no_assistant(monkeypatch):
    called = {}

    class DummyResp:
        output_text = "resp"

    class DummyClient:
        def __init__(self):
            self.responses = self
        def create(self, **kwargs):
            called.update(kwargs)
            return DummyResp()

    monkeypatch.setattr(llm_client, "get_client", lambda: DummyClient())
    monkeypatch.setattr(llm_client, "LLM_ASSISTANT_ID", "")
    monkeypatch.setattr(llm_client, "LLM_MODEL", "gpt-test")

    out = llm_client.complete("hi")
    assert out == "resp"
    assert called == {"model": "gpt-test", "input": "hi"}
