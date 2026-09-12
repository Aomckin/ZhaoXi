"""Load versioned personality configuration into a system prompt."""

from pathlib import Path
from typing import Any

import yaml

from zhaoxi.errors import ConfigError


class PersonalityLoader:
    """Read one versioned character-prompt YAML document."""

    filename = "zhaoxi_v1.yaml"
    subject = "人格"
    heading = "以下是你必须稳定遵循的人格设定："

    @classmethod
    def load(cls, path: str | Path | None = None) -> dict[str, Any]:
        target = Path(path) if path else Path(__file__).with_name(cls.filename)
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"无法加载{cls.subject}配置 {target}：{exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{cls.subject}配置必须是 YAML 对象。")
        return data

    @classmethod
    def to_prompt(cls, config: dict[str, Any]) -> str:
        lines = [cls.heading]
        for section, values in config.items():
            lines.append(f"\n{section}:")
            if isinstance(values, dict):
                lines.extend(f"- {key}: {value}" for key, value in values.items())
            elif isinstance(values, list):
                lines.extend(f"- {value}" for value in values)
            else:
                lines.append(f"- {values}")
        return "\n".join(lines)

    @classmethod
    def load_prompt(cls, path: str | Path | None = None) -> str:
        return cls.to_prompt(cls.load(path))


class ExpressionLoader(PersonalityLoader):
    """Load reply style separately from stable identity and relationships."""

    filename = "expression_v1.yaml"
    subject = "表达方式"
    heading = "以下是你在最终回复中必须遵循的表达方式；它只决定怎么说，不改变事实与人格："


class CanineExpressionLoader(PersonalityLoader):
    """Load canine behavior cues separately from general expression style."""

    filename = "canine_expression.yaml"
    subject = "犬娘表达"
    heading = "以下规则用于自然呈现朝汐的犬娘行为与情绪，不应机械套用或覆盖当前场景："


class FewShotDialoguesLoader(PersonalityLoader):
    """Load example dialogues used to demonstrate the intended character voice."""

    filename = "few_shot_dialogues.yaml"
    subject = "示例对话"
    heading = "以下是表达风格示例；学习其反应方式与节奏，不要照抄内容："

    @classmethod
    def load(cls, path: str | Path | None = None) -> list[dict[str, str]]:
        target = Path(path) if path else Path(__file__).with_name(cls.filename)
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"无法加载{cls.subject}配置 {target}：{exc}") from exc
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ConfigError(f"{cls.subject}配置必须是 YAML 对象列表。")
        return data

    @classmethod
    def to_prompt(cls, config: list[dict[str, str]]) -> str:
        lines = [cls.heading]
        for item in config:
            scene = str(item.get("scene", "")).strip()
            user = str(item.get("user", "")).strip()
            assistant = str(item.get("assistant", "")).strip()
            if not scene or not user or not assistant:
                raise ConfigError("示例对话必须包含非空的 scene、user 和 assistant。")
            lines.extend((
                f"\n场景：{scene}",
                f"用户：{user}",
                "朝汐：",
                assistant,
            ))
        return "\n".join(lines)
