from app import selection


def test_summarize_batch_goes_background():
    alias, rationale = selection.pick("summarize this log", latency="batch")
    assert alias == "background"
    assert rationale


def test_code_interactive_goes_fast():
    alias, _ = selection.pick("write and debug this python code", latency="interactive")
    assert alias == "fast"


def test_reasoning_signal_goes_reasoning():
    alias, _ = selection.pick("reason through this proof step by step", latency="interactive")
    assert alias == "reasoning"


def test_large_context_goes_fast():
    alias, _ = selection.pick("do a thing", latency="interactive", est_context=20000)
    assert alias == "fast"


def test_unknown_defaults_fast():
    alias, _ = selection.pick("hello there", latency="interactive")
    assert alias == "fast"


def test_parse_decision_valid():
    out = selection._parse_decision('{"alias":"background","model":"qwen2.5:7b","rationale":"x","confidence":0.9}')
    assert out is not None and out[0] == "background"


def test_parse_decision_rejects_unknown_alias():
    assert selection._parse_decision('{"alias":"nonexistent","model":"m","rationale":"x","confidence":1}') is None


def test_parse_decision_strips_think_tags():
    raw = '<think>let me think</think>\n{"alias":"fast","model":"qwen2.5-7b-instruct","rationale":"r","confidence":0.8}'
    out = selection._parse_decision(raw)
    assert out is not None and out[0] == "fast"


def test_system_prompt_loads_and_injects():
    msgs = selection._build_messages("summarize", "batch", 0)
    sys = msgs[0]["content"]
    assert "{{models}}" not in sys
    assert "background" in sys  # registry injected
