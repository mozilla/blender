"""Tests for scripts.extract_alert_verdict."""

from __future__ import annotations

import json

from scripts.extract_alert_verdict import VERDICT_FILE, extract, final_text, main


VERDICT = {
    "affected": False,
    "confidence": "high",
    "reason": "not used",
    "vulnerable_paths": [],
    "recommended_action": "bump_pr",
}


def test_plain_text_verdict_json_block():
    log = "Some preamble\n```VERDICT_JSON\n" + json.dumps(VERDICT, indent=2) + "\n```\n"
    assert extract(log) == VERDICT


def test_plain_text_fallback_bare_object():
    log = "Analysis complete. " + json.dumps(VERDICT)
    assert extract(log) == VERDICT


def test_json_session_log():
    """--output-format json wraps text in a JSON event array."""
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Here is my verdict:\n\n"
                            "```VERDICT_JSON\n"
                            + json.dumps(VERDICT, indent=2)
                            + "\n```"
                        ),
                    }
                ],
            },
        },
        {"type": "result", "subtype": "success"},
    ]
    log = json.dumps(events)
    assert extract(log) == VERDICT


def test_json_log_with_stderr_noise_and_result_event():
    """Real-world case: 2>&1 prepends a trust warning, and the verdict
    lives in the result event of a single-line JSON stream."""
    text = "I have enough evidence.\n```VERDICT_JSON\n" + json.dumps(VERDICT) + "\n```"
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "result": text},
    ]
    log = "Ignoring 3 permissions.allow entries: workspace not trusted.\n"
    log += json.dumps(events)
    assert extract(log) == VERDICT


def test_no_verdict_returns_none():
    assert extract("No verdict here.") is None
    assert extract("[]") is None


def test_final_text_prefers_result_event():
    events = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me look."}]}},
        {"type": "result", "subtype": "success", "result": "Needs .github edits."},
    ]
    log = "Ignoring 3 permissions.allow entries: workspace not trusted.\n"
    log += json.dumps(events)
    assert final_text(log) == "Needs .github edits."


def test_final_text_falls_back_to_last_assistant_text():
    events = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me look."}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Needs .github edits."}]}},
        {"type": "result", "subtype": "success"},
    ]
    assert final_text(json.dumps(events)) == "Needs .github edits."


def test_final_text_plain_text_returns_empty():
    assert final_text("plain text") == ""


def test_main_final_text_prints_answer(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "log"
    log.write_text(json.dumps([{"type": "result", "result": "Needs .github edits."}]))
    monkeypatch.setattr("sys.argv", ["x", "--final-text", str(log)])
    main()
    assert capsys.readouterr().out == "Needs .github edits.\n"
    assert not (tmp_path / VERDICT_FILE).exists()
