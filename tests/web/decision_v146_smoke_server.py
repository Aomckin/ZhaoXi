"""Isolated fixture for Decision 2 dashboard acceptance; no production models."""
import os
from pathlib import Path
import uvicorn
import zhaoxi.core.agent
from dashboard_fixture import dashboard_core
from zhaoxi.decision.awareness import DecisionAwareness
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.web.app import create_app

if __name__ == "__main__":
    path = Path(".zhaoxi/v146-browser-fixture")
    path.mkdir(parents=True, exist_ok=True)
    core, settings = dashboard_core(path)
    settings.dev_browser_ui = False
    core.decision_mode = "agency"
    core.decision_awareness = DecisionAwareness(history=ChoiceHistory(path / "choices"))
    trace = DecisionAwarenessTrace(mode="ADVISE", agent_recommendation="去打舞萌",
        predicted_user_choice="继续项目", context_sources=["agenda","current_cognition"],
        principle_ids=["protect_today_mainline"])
    core.decision_awareness.recent_traces.append(trace.model_dump(mode="json"))
    core.decision_awareness.history.record("smoke-cola", DecisionAwarenessTrace(
        mode="PICK",agent_recommendation="两瓶"), "可乐", scope="owner:desktop:local")
    core.decision_awareness.history.feedback("smoke-cola","三瓶",scope="owner:desktop:local",overridden=True)
    core.tool_executor.recent_decision_guard_events = [
        {"tool":"payment","flags":["high_impact_action"],"status":"require_confirmation"}]
    if os.environ.get("ZHAOXI_DECISION_REPLY_PATCH_SMOKE") == "1":
        core.last_reply_protocol = {"status":"failed", "error_code":"empty_model_reply", "input_chars":3}
        core.decision_awareness.recent_traces[-1]["context_sources"].append("current_image")
    core.internal_activity.control.update("presence",{"heartbeat_enabled":False})
    uvicorn.run(create_app(agent=core, settings=settings, api_token="decision-ui-test"),
                host="127.0.0.1",port=18766)
