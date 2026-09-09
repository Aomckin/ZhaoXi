"""Explicit opt-in live-model smoke test; isolated inbox and accelerated daytime clock."""
import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.personality.loader import ExpressionLoader, PersonalityLoader
from zhaoxi.proactive.beat import ConversationBeatLoop
from zhaoxi.proactive.decision import ModelDecision
from zhaoxi.proactive.heartbeat import TidalHeartbeat
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.policy import InterruptPolicy, PolicyState
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.scheduler import Scheduler
from zhaoxi.proactive.store import InMemoryProactiveStore
from zhaoxi.proactive.worker import DecisionWorker
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.tools.registry import ToolRegistry


async def main():
    settings = Settings()
    provider = ResilientProvider([OpenAICompatibleProvider(base_url=settings.model_base_url, api_key=settings.model_api_key,
        model=settings.model_name, timeout=30, max_tokens=1200)])
    conversation = Conversation()
    context = ContextBuilder(PersonalityLoader.load_prompt(), expression_prompt=ExpressionLoader.load_prompt())
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=context, conversation=conversation)
    await agent.run_direct('认可你是我的犬娘了。')
    state = PolicyState()
    now = datetime.now(UTC).replace(hour=4, minute=0, second=0, microsecond=0)
    state.interaction.interact(now)
    beat = ConversationBeatLoop(settings, state.interaction, conversation)
    beat.note_user_message('认可你是我的犬娘了。', now)
    beat.note_assistant(now)
    store = InMemoryProactiveStore()
    runtime = ProactiveRuntime(store, InboxNotificationSink(store), InterruptPolicy())
    heartbeat = TidalHeartbeat(runtime, Scheduler(store), state, settings, MetricRegistry())
    heartbeat.continuation = beat
    worker = DecisionWorker(heartbeat, ModelDecision(provider, context.character_prompt, conversation=conversation))
    for seconds in (settings.active_beat_min_silence_seconds+1,
                    settings.active_beat_min_silence_seconds+settings.active_beat_cooldown_seconds+2):
        deliveries = await worker.tick(now+timedelta(seconds=seconds))
        print(json.dumps({'open_thread': beat.open_thread is not None, 'beat_count': beat.session.beat_count,
            'action': beat.session.last_beat_result, 'failure': beat.model_failure, 'delivery_count': len(deliveries),
            'model_diagnostics': beat.model_diagnostics,
            'content': deliveries[0].content if deliveries else None}, ensure_ascii=False))
        if deliveries:
            return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True, help='Use configured model API (up to three calls).')
    parser.parse_args()
    asyncio.run(main())
