import logging
import pytest

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


def test_eight_categories_cover_exact_payload_without_counting_images_as_text():
    messages = [Message(role=Role.SYSTEM, content="persona1234memory5678cognitionEXTRA", metadata={
        "prompt_components":[{"name":"system.personality","chars":11},
                             {"name":"memory.recall","chars":10},
                             {"name":"runtime.current_cognition","chars":9}]}),
                Message(role=Role.USER,content="secret body",images=["data:image/png;base64,AAAA"]),
                Message(role=Role.TOOL,content="private receipt",name="probe",tool_call_id="one")]
    report = collect_prompt_diagnostics(messages,[{"type":"function","function":{"name":"probe"}}],model="synthetic")
    parts = report["context_breakdown"]
    assert set(parts) == {"system","persona","tool_schemas","timeline","tool_results","images","memory","cognition"}
    assert sum(p["chars"] for p in parts.values()) == report["input_chars"]
    assert parts["persona"]["chars"] == 11 and parts["memory"]["chars"] == 10
    assert parts["cognition"]["chars"] == 9 and parts["system"]["chars"] > 0
    assert parts["images"]["count"] == 1 and parts["images"]["tokens"] is None
    assert parts["images"]["estimated_tokens"] is None
    assert "secret" not in str(parts) and "AAAA" not in str(parts)


@pytest.mark.parametrize("image_tokens", [None, 7])
async def test_actual_provider_attempt_keeps_breakdown_in_final_metrics_without_budget(image_tokens):
    import httpx
    from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
    from zhaoxi.models.resilient import ResilientProvider
    from zhaoxi.observability import action_trace_scope
    from zhaoxi.reliability import CorrelationContext, correlation_scope
    def transport(request):
        return httpx.Response(200,json={"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],
                                       "usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12,
                                                "prompt_tokens_details":{"image_tokens":image_tokens}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        provider = ResilientProvider([OpenAICompatibleProvider(base_url="https://synthetic.test/v1",api_key="test",model="synthetic",client=client)])
        with correlation_scope(CorrelationContext(trace_id="breakdown",request_id="breakdown")), action_trace_scope() as trace:
            await provider.generate([Message(role=Role.USER,content="private-input",images=["data:image/png;base64,AAAA"])])
            call = trace.metrics()["llm_calls"][0]
            assert call["prompt_tokens"] == 10 and call["context_breakdown"]["timeline"]["chars"] > 0
            assert "private-input" not in str(call["context_breakdown"])
            assert call["context_breakdown"]["images"]["tokens"] == image_tokens
            finished = next(e for e in trace.events if e.event_type == "llm_call_finished")
            assert finished.metadata["context_breakdown"] == call["context_breakdown"]
