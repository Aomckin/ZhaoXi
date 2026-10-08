# 纯图片占位句与主动回复缺图修复

日期：2026-10-08。用户反馈：19:28 单独发送图片，程序隐式补写“请查看这些图片。”；19:32 主动回复又称图片没上传。程序重启后，占位句也在图片气泡中显示。

## 查证与根因

19:28:48 本地用户消息 `7aaed6d4fb1e4c4395dfe158b5b9ffde` 的正文确实是占位句，附带一张图片；前台请求为 `6a1259aa-d591-4ec3-b74c-50ba65c49f32`。Web API 之前把图片输入的空文本替换成这句话，统一接口又要求非空文本。纯图实时展示使用前端草稿的空文字；重启恢复使用服务端保存的占位文字，因此出现展示不一致。

19:32:01 Heartbeat `59968d2e7ad44f7189917d7ba3469744` 调用模型并交付 COMMENT，没有模型错误。ConversationBeatLoop 原先仅将认知时间线的 role/content 放进 JSON，未发送 Message.images 的图片内容块。因此模型能读取假用户文字，却无法在该主动请求中重新查看图片。日志与代码能证明输入缺图，不能保证模型有图后每次都作出正确视觉判断。

## 修复行为

- 本地入口接受“空文本 + 图片”，拒绝文本与图片同时为空。Web、重生成、视觉上下文、Provider 与外部图片回复不再补写这两种查看图片占位句。纯图保留空正文，模型接收图片内容块；内部来源提示与用户文字分开。
- 纯图仍走一次视觉回复且不主动调用业务工具。后续有明确文字要求时，历史原图引用与 LifeHUD 工具链继续可用。发图被明确记为有附件的真实互动，仍能结束主动续聊的等待状态并恢复额度，不依赖占位文字。
- Heartbeat、普通主动决策及对话延续决策附上近期认知时间线中的历史缩略图，沿用最长边 512 像素、JPEG quality 65。JSON 保留原事件 ID、角色、来源、频道、图片数量、实际附上数量和序号，图片字节单独放进模型的多模态消息。
- 每个历史事件独立附图，保留每条消息最多 20 张的已有保护；没有新增历史图片数量限制，30 张历史图已验证可全部附上。既有近期时间线范围、预算、超时和无工具约束仍有效；不可读图片标明历史附件不可用，提示模型不要误说用户未上传，也不将历史图片当成新请求。自身表情不重复当作用户照片发送。
- 新本地消息持久化 `input_text_present`，认知事件也保留此标记。用户真实输入“请查看这些图片。”并附图时仍保留文字。旧本地带图记录没有该标记且正文完全等于“请查看这些图片。”或“请查看图片。”时按历史占位句清理；图片、消息 ID 和时间不变。旧记录无法严格区分用户恰好手动输入的同一句话，这一兼容规则只针对两个完整句子，不清理其他文字或 QQ 来源。
- Session 在正常加载时清理旧占位句；ExperienceStream 在读取投影时清理，原始事件 payload 不改写。无需直接迁移正式数据库。恢复到浏览器后，空正文走现有 image-only DOM，只显示图片和时间。

## 验证

关联回归 **546 项通过**，覆盖图片、历史原图、主动消息、统一接口、认知时间线、工具恢复、权限与 LifeHUD。最后收窄本地旧记录清理范围后，图片/认知事件/接口/Session **183 项通过**；补齐图片互动额度后，主动消息/接口 **139 项通过**。这些范围重叠，不相加作为全量测试数。

针对性检查包含纯图 HTTP 输入、Provider 图片内容块无伪造文本、保存/重载旧占位句、真实同句文字保留、原事件不可变、图片重生成不丢 ID/时间/附件、五张大照片变为历史缩略图、30 张历史图完整传递、不可用图片、第三方来源及排除自身表情、纯图互动恢复主动额度。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/web/test_images.py tests/web/test_lifehud_history_images.py tests/proactive tests/interfaces tests/cognitive_stream tests/core/test_loop_safety.py tests/core/test_tool_retry.py tests/permission tests/cognitive tools/lifehud_tool/tests tests/perception/test_v131.py -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-image-only-proactive-final
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/web/test_images.py tests/cognitive_stream tests/interfaces tests/session -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-image-only-compat-final
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/proactive tests/interfaces -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-image-only-beat-budget
# 设置 ZHAOXI_PLAYWRIGHT 指向已安装的 playwright 包后：
node tests/web/image_only_reload_smoke.cjs
```

隔离 Edge 浏览器执行真实 restore / reply-renderer / addMessageBubble 函数，验证初次加载与页面重载均仅有图片和时间、没有文字气泡或占位句，并无脚本错误，共 **3 项检查通过**。页面由 Playwright 本地路由提供，没有连接正式服务。报告在 `.pytest_cache/image-only-reload-acceptance.json`。

[结构化证据](evidence/2026-10-08-image-only-and-proactive-vision.json)。未调用真实模型、重放正式业务、修改正式数据库或重启正式进程；图片上传和业务写入均模拟。源码尚未提交。需完全退出托盘再启动加载 Python 修复，进程内“重启 Core”不会重新导入这些模块。真实视觉效果需加载新代码后验收。
