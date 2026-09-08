from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.personality import ExpressionLoader, PersonalityLoader


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
