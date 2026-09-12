import logging

from zhaoxi.core.message import Message, Role
from zhaoxi.models.prompt_diagnostics import collect_prompt_diagnostics, log_prompt_diagnostics, log_prompt_usage


def test_prompt_diagnostics_logs_lengths_and_names_without_content(caplog):
    secret = "do-not-log-this"
    messages = [
        Message(role=Role.SYSTEM, content=secret, metadata={"prompt_components": [
            {"name": "system.personality", "chars": len(secret)},
        ]}),
        Message(role=Role.USER, content="private-user-text"),
    ]
    tools = [{"type": "function", "function": {"name": "lookup", "description": "private-tool-text"}}]

    with caplog.at_level(logging.DEBUG, logger="PROMPT"):
        log_prompt_diagnostics(messages, tools, model="test-model")

    output = caplog.text
    assert "system.personality" in output
    assert "tool_schema.lookup" in output
    assert "conversation_history.1.user" in output
    assert secret not in output
    assert "private-user-text" not in output
    assert "private-tool-text" not in output


def test_prompt_usage_supports_prompt_and_input_token_names(caplog):
    with caplog.at_level(logging.DEBUG, logger="PROMPT"):
        log_prompt_usage({"prompt_tokens": 123, "completion_tokens": 4, "total_tokens": 127}, model="m")
        log_prompt_usage({"input_tokens": 55, "output_tokens": 6}, model="m")
    assert "prompt_tokens=123" in caplog.text
    assert "prompt_tokens=55" in caplog.text


def test_prompt_diagnostic_components_cover_the_exact_input():
    report = collect_prompt_diagnostics(
        [Message(role=Role.SYSTEM, content="system"), Message(role=Role.USER, content="hello")],
        [{"type": "function", "function": {"name": "lookup"}}],
        model="m",
    )
    assert sum(item["chars"] for item in report["components"]) == report["input_chars"]
    assert round(sum(item["percent"] for item in report["components"]), 1) == 100.0


def test_prompt_diagnostics_include_router_counts_without_user_content(caplog):
    router = {
        "router_mode": "dynamic",
        "persistent_tools_count": 2,
        "matched_dynamic_groups": ["time"],
        "total_exposed_tools_count": 3,
        "total_registered_tools_count": 34,
        "filtered_tools_count": 31,
    }
    with caplog.at_level(logging.DEBUG, logger="PROMPT"):
        log_prompt_diagnostics(
            [Message(role=Role.USER, content="private-router-input")], [],
            model="m", tool_router=router,
        )
    assert '"router_mode":"dynamic"' in caplog.text
    assert '"filtered_tools_count":31' in caplog.text
    assert "private-router-input" not in caplog.text
