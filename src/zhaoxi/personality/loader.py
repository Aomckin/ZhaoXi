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
