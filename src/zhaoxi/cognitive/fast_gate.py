"""Conservative local gate for the v1.4.1 fast dialogue lane."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class FastDialogueDecision:
    eligible: bool
    reason: str
    continuation_detected: bool = False


class FastDialogueGate:
    """Admit only turns that are safe to answer without routing or tools."""

    _CONTINUATION = (
        "继续", "然后呢", "接着", "刚刚那个", "前面那个", "那两条呢", "剩下的呢",
        "这个再改一下", "按刚才的继续", "照刚才", "上一条", "上一个",
    )
    _ACTION = (
        "记一下", "记住", "写进", "写入", "添加", "删除", "修改", "保存", "收藏",
        "发送", "发给", "提醒我", "打开", "关闭", "执行", "帮我填", "同步", "上传",
        "下载", "创建", "更新", "取消", "完成日程", "开幕", "落幕", "调用工具",
    )
    _RECALL = (
        "你还记得", "还记得", "之前那个", "上次", "以前我们", "我什么时候",
        "之前说过", "以前说过", "回忆一下", "查记忆", "长期记忆",
    )
    _DECISION = ("要不要", "该不该", "选哪个", "值不值得", "去不去", "接不接", "怎么选")
    _EXTERNAL = (
        "查一下", "搜一下", "帮我查", "帮我搜", "看看现在", "最新", "今天有什么",
        "实时", "当前价格", "天气", "几点", "现在时间", "核对", "读取", "检索",
    )
    _COMPUTE = ("计算", "算一下", "算算", "换算")
    _MULTI_STEP = ("先", "然后", "再", "最后", "重新核对", "分步骤")
    _PRIVATE_FACT_DOMAINS = (
        "潮庭", "书库", "项目文档", "长期资料", "lifehud", "agenda", "日程",
    )
    _PERSONAL_FACT = re.compile(
        r"(?:朝汐|暗苟).{0,12}(?:为什么|是谁|哪天|什么时候|是什么|有哪些|多少|设定|身世|资料|记载)"
    )

    def decide(
        self,
        user_message: str,
        *,
        images: list[str] | None = None,
        pending_permission: bool = False,
    ) -> FastDialogueDecision:
        text = " ".join(user_message.casefold().strip().split())
        if not text:
            return FastDialogueDecision(False, "empty_message")
        if images:
            return FastDialogueDecision(False, "image_input")
        if pending_permission:
            return FastDialogueDecision(False, "pending_permission")
        if any(marker in text for marker in self._CONTINUATION):
            return FastDialogueDecision(False, "explicit_continuation", True)
        if any(marker in text for marker in self._ACTION):
            return FastDialogueDecision(False, "explicit_action")
        if any(marker in text for marker in self._RECALL):
            return FastDialogueDecision(False, "explicit_recall")
        if any(marker in text for marker in self._DECISION):
            return FastDialogueDecision(False, "explicit_decision")
        if sum(marker in text for marker in self._MULTI_STEP) >= 2:
            return FastDialogueDecision(False, "multi_step_request")
        if any(marker in text for marker in self._EXTERNAL):
            return FastDialogueDecision(False, "external_or_realtime_query")
        if any(marker in text for marker in self._COMPUTE):
            return FastDialogueDecision(False, "calculation_request")
        if any(domain in text for domain in self._PRIVATE_FACT_DOMAINS):
            return FastDialogueDecision(False, "private_or_structured_fact")
        if self._PERSONAL_FACT.search(text):
            return FastDialogueDecision(False, "personal_fact_recall")
        return FastDialogueDecision(True, "safe_conversation")
