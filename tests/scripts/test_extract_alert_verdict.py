"""Tests for scripts.extract_alert_verdict."""

from __future__ import annotations

import json

from scripts.extract_alert_verdict import extract


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


def test_no_verdict_returns_none():
    assert extract("No verdict here.") is None
    assert extract("[]") is None
