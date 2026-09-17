"""Model-context-only normalization for repeated, templated stage directions."""

from __future__ import annotations

import re


_PAREN_LINE = re.compile(r"^\s*(?:（(?P<full>[^（）\r\n]+)）|\((?P<half>[^()\r\n]+)\))\s*$")
_ACTION_CUES = re.compile(
    r"(?:朝汐|她|耳朵|犬耳|尾巴|呆毛|歪头|抬头|低头|点头|摇头|凑近|靠近|"
    r"退开|挪|趴|坐|站|抱|缩|抿|鼓起|眨|笑|视线|目光|姿势|顿了|停了)"
)
_TEMPLATE_CUES = re.compile(
    r"(?:耳朵.{0,5}(?:动了动|转了转)|尾巴.{0,5}(?:晃了晃|摇了摇)|歪了歪头|"
    r"凑近了一点|顿了顿|停了一下)"
)
_EMOTIONAL_CHANGE = re.compile(
    r"(?:突然|一下|猛地|僵|垂|竖|压|停住|亮起|躲|扑|红|心虚|赌气|惊|"
    r"安静|憋不住|激动|失落|委屈|开心)"
)
_AGENT_WORK = re.compile(
    r"(?:代码|报错|错误|日志|测试|文件|工具|查询|执行|诊断|整理|任务|确认|权限|"
    r"接口|数据库|配置|部署|修复|版本|commit|debug|traceback)",
    re.IGNORECASE,
)


def _stage_direction(line: str) -> str | None:
    match = _PAREN_LINE.match(line)
    if not match:
        return None
    body = match.group("full") or match.group("half") or ""
    return body if _ACTION_CUES.search(body) else None


def normalize_assistant_history(content: str) -> str:
    """Reduce only clearly repetitive action lines in model-visible history.

    The stored/user-visible message is never passed here by mutation. A single
    expressive action, ordinary parentheses, and inline parentheticals remain.
    """
    lines = content.splitlines()
    actions = [(index, body) for index, line in enumerate(lines) if (body := _stage_direction(line))]
    if not actions:
        return content

    technical = bool(_AGENT_WORK.search(content))
    if technical:
        removable = {
            index for index, body in actions
            if _TEMPLATE_CUES.search(body) or not _EMOTIONAL_CHANGE.search(body)
        }
    elif len(actions) < 3 and not all(_TEMPLATE_CUES.search(body) for _, body in actions):
        return content
    else:
        # Keep one action with real emotional change so character expression is
        # reduced, not erased. Stable ordering breaks equal-score ties.
        keep = max(
            actions,
            key=lambda item: (bool(_EMOTIONAL_CHANGE.search(item[1])), not bool(_TEMPLATE_CUES.search(item[1])), -item[0]),
        )[0]
        removable = {index for index, _ in actions if index != keep}

    normalized = [line for index, line in enumerate(lines) if index not in removable]
    compact: list[str] = []
    for line in normalized:
        if line or not compact or compact[-1]:
            compact.append(line)
    return "\n".join(compact).strip()
