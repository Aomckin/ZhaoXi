from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.personality import (
    CanineExpressionLoader,
    ExpressionLoader,
    FewShotDialoguesLoader,
    PersonalityLoader,
)


def _stage_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if (line.strip().startswith("（") and line.strip().endswith("）"))
            or (line.strip().startswith("(") and line.strip().endswith(")"))]


def test_personality_and_expression_are_independent_versioned_prompts():
    personality = PersonalityLoader.load_prompt()
    expression = ExpressionLoader.load_prompt()

    assert "人格设定" in personality
    assert "identity:" in personality
    assert "表达方式" not in personality
    assert "表达方式" in expression
    assert "rhythm:" in expression
    assert "只决定怎么说，不改变事实与人格" in expression


def test_context_places_expression_after_identity_and_before_runtime_rules():
    system = ContextBuilder(
        "PERSONALITY",
        expression_prompt="EXPRESSION",
    ).build(Conversation())[0].content

    assert system.index("PERSONALITY") < system.index("EXPRESSION") < system.index("运行规则")


def test_expression_input_remains_optional_for_existing_context_callers():
    context = ContextBuilder("PERSONALITY")

    assert context.character_prompt == "PERSONALITY"
    assert "PERSONALITY" in context.build(Conversation())[0].content


def test_canine_expression_is_loaded_as_a_separate_prompt():
    prompt = CanineExpressionLoader.load_prompt()

    assert "犬娘行为与情绪" in prompt
    assert "golden_retriever_traits:" in prompt
    assert "犬娘感主要来自行为和情绪" in prompt
    assert "普通回复通常不写，不能形成固定括号节拍" in prompt


def test_few_shot_dialogues_load_all_scenes_and_render_as_examples():
    dialogues = FewShotDialoguesLoader.load()
    prompt = FewShotDialoguesLoader.to_prompt(dialogues)

    assert dialogues
    assert len({item["scene"] for item in dialogues}) == len(dialogues)
    assert all(f"场景：{item['scene']}" in prompt for item in dialogues)
    assert all(f"用户：{item['user']}" in prompt for item in dialogues)
    assert "学习其反应方式与节奏，不要照抄内容" in prompt


def test_few_shot_stage_directions_are_low_frequency_and_agent_work_has_none():
    dialogues = FewShotDialoguesLoader.load()
    counts = [_stage_lines(item["assistant"]) for item in dialogues]
    assert sum(not lines for lines in counts) >= len(dialogues) // 2
    assert all(len(lines) <= 1 for lines in counts)
    work = [item for item in dialogues if item["scene"] in {"技术错误诊断", "工具执行与任务确认"}]
    assert len(work) == 2
    assert all(not _stage_lines(item["assistant"]) for item in work)
    plain_character = next(item["assistant"] for item in dialogues if item["scene"] == "用户卖关子")
    assert "暗苟酱" in plain_character and not _stage_lines(plain_character)


def test_expression_rules_keep_character_while_rejecting_fixed_action_rhythm():
    prompt = ExpressionLoader.load_prompt()
    assert "舞台描写是情绪真正变化时的低频强调手段" in prompt
    assert "技术解释、工具执行、错误诊断" in prompt
    assert "减少动作不等于去角色化" in prompt
