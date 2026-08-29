"""Load versioned personality configuration into a system prompt."""

from pathlib import Path
from typing import Any

import yaml

from zhaoxi.errors import ConfigError


class PersonalityLoader:
    """Read personality YAML without coupling it to the agent runtime."""

    @staticmethod
    def load(path: str | Path | None = None) -> dict[str, Any]:
        target = Path(path) if path else Path(__file__).with_name("zhaoxi_v1.yaml")
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"无法加载人格配置 {target}：{exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("人格配置必须是 YAML 对象。")
        return data

    @staticmethod
    def to_prompt(config: dict[str, Any]) -> str:
        lines = ["以下是你必须稳定遵循的人格设定："]
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

