import pytest
from types import SimpleNamespace

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.errors import ProviderError
from zhaoxi.reliability.retry import (
    BudgetExtensionRequest, BudgetPolicy, budget_stage_scope,
    consume_provider_budget, provider_budget_scope, record_provider_tokens,
)


def policy():
    return BudgetPolicy(1000, 400, 200, 1600, 200)


def request(stage="tool_execution", remaining=1, extra=300, **evidence):
    return BudgetExtensionRequest(
        reason="有明确剩余操作", remaining_actions=remaining,
        estimated_extra_tokens=extra, stage=stage,
        progress_evidence=evidence,
    )


def test_two_runtime_approved_extensions_never_cross_hard_limit():
    with provider_budget_scope(8, policy=policy()) as budget:
        record_provider_tokens(790)
        first = budget.request_extension(request(completed_actions=1, last_success_step=2))
        assert first["approved_extra"] == 300
        assert budget.max_total_tokens == 1300
        record_provider_tokens(170)
        second = budget.request_extension(request("finalization", 0, 200, completed_actions=2))
        assert second["approved_extra"] == 200
        assert budget.max_total_tokens == 1500
        third = budget.request_extension(request("finalization", 0, 100, completed_actions=2))
        assert third["reason_code"] == "extension_limit"
        assert budget.extension_count == 2
        with budget_stage_scope("finalization"):
            with pytest.raises(ProviderError, match="Token"):
                record_provider_tokens(641)


def test_repeated_failure_and_unverified_remaining_actions_are_rejected():
    with provider_budget_scope(8, policy=policy()) as budget:
        record_provider_tokens(790)
        assert budget.request_extension(request(new_result=True, repeated_error_count=2))["reason_code"] == "repeated_failure"
        assert budget.request_extension(request(completed_actions=1, remaining_actions_verified=False))["reason_code"] == "remaining_actions_mismatch"
        assert budget.request_extension(request())["reason_code"] == "no_progress"
        assert budget.extension_count == 0


def test_finalization_can_spend_reserved_tokens_without_opening_tool_budget():
    with provider_budget_scope(8, policy=policy()) as budget:
        record_provider_tokens(850)
        with pytest.raises(ProviderError, match="受控扩容"):
            consume_provider_budget()
        with budget_stage_scope("finalization"):
            consume_provider_budget()
            record_provider_tokens(100)
        assert budget.reserve_entered is True
        assert budget.stage_usage == {"planning": 850, "finalization": 100}


def test_second_extension_cannot_resume_broad_planning():
    with provider_budget_scope(8, policy=policy()) as budget:
        record_provider_tokens(790)
        assert budget.request_extension(request(completed_actions=1))["approved_extra"] == 300
        record_provider_tokens(160)
        result = budget.request_extension(request("planning", 2, 150, completed_actions=2))
        assert result["reason_code"] == "second_extension_restricted"


def test_ordinary_request_does_not_receive_unneeded_extension():
    with provider_budget_scope(8, policy=policy()) as budget:
        result = budget.request_extension(request(completed_actions=1))
        assert result["reason_code"] == "not_needed"
        assert budget.extension_count == 0


def test_one_completed_tool_does_not_force_early_final_reply():
    action = SimpleNamespace(status="completed", tool_name="echo", failure_kind=None,
                             step_id=1)
    trace = SimpleNamespace(actions=[action])
    with provider_budget_scope(8, policy=policy()) as budget:
        record_provider_tokens(700)
        assert ZhaoxiAgent._budget_mode(True, trace, 2) == ("tool_execution", False)
        assert budget.extension_count == 0
