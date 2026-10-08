# LifeHUD 续办任务关联历史原图

日期：2026-10-08。用户反馈：当前轮带图记录饮食失败后，下一轮继续完成原任务，模型能看到历史图片，但 Tool 无法将它们存入 LifeHUD。

## 根因

模型侧历史照片已有缩略图；这不能代替工具侧附件传递。Agent 原先只将当前请求 turn_images 传给 LifeHUD，Tool 的 <current-message-image> 占位符也只解析当前附件。文本续办请求没有当前图片，因此该占位符报 attachment_not_found；若续办同时附了新图，它只会指向新图。此前短期 ToolRetryContext 只恢复未执行意图，同样不提供原图引用。此次没有将最近图片默认冒充当前图片，也没有扩大自动重试的行动范围。

## 修复行为

ContextBuilder 在普通会话和认知时间线中，对本地同会话 Owner 的历史原图提供 `<conversation-image:消息ID:序号>` 引用，序号从 1 开始。引用与对应图片描述一起进入模型上下文；模型视觉输入继续沿用原有缩略图/预览规则。正式会话与 ExperienceStream 不增加这段提示文字，不复制图片字节到提示或模型生成参数。

Agent 持有本轮已提供引用到原附件的映射，单独传给 LifeHUD ToolExecutor。LifeHUD 通过执行期间的 SDK 引用解析接口读取原图，沿用已有全部附件先校验、再上传、再写记录的流程。映射不会进入权限请求参数或工具审计；确认及确认后剩余调用保留同一引用快照，历史消息后来从时间线裁剪时仍可使用已确认的图片。

当前 `<current-message-image>` 与索引占位符含义不变。历史图需使用上下文实际提供的明确引用，可以与新图混用并按 images 数组顺序上传。无效、伪造、不可用引用在上传或业务写入前返回 attachment_not_found；没有最新图片兜底，也不从任意路径猜图。公共频道、第三方图片和其他会话的图片不加入此引用映射。清空或未加载的历史原图不保证可用，已有权限与成功写入防重复执行逻辑不变。

## 验证

专项 **340 项通过**，覆盖图片、权限、工具恢复、FAST 升级、LifeHUD 包与业务协议、认知时间线。新增 9 项覆盖：

- 上一轮模拟模型请求失败，下一轮继续保存两张历史图与一张新图；验证上传的原始 PNG 字节、指定顺序、只创建一次记录，工具参数只含引用。
- 直接执行与等待确认两条路径；确认前历史照片从会话移除，待确认快照仍保持已选原图。
- 认知时间线使用原事件 ID 提供引用，解析到原始附件，正式会话正文不被注入引用说明。
- QQ/第三方/其他会话/公共受众图片不暴露工具引用；缺失引用阻止任何上传与记录请求。
- 工具执行结束后 ContextVar 清理，当前附件和历史映射不流入下次调用。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/web/test_lifehud_history_images.py tests/web/test_images.py tests/core/test_loop_safety.py tests/core/test_tool_retry.py tests/interfaces tests/permission tests/cognitive/test_fast_escalation.py tests/tools/test_lifehud_package.py tools/lifehud_tool/tests tests/cognitive_stream -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-history-tool-images-final
```

[结构化证据](evidence/2026-10-08-lifehud-history-images.json)。所有上传与 LifeHUD 写入使用 MockTransport；未调用真实模型、重放正式任务、修改正式数据库或重启。需完全退出托盘再启动后加载源码修复；已有历史照片仍在当前会话/认知上下文时，可继续明确要求关联它们。实际模型是否正确选择引用仍需加载新代码后验收。源码尚未提交。
