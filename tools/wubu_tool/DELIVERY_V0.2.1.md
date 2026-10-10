# 物簿 tool v0.2.1 交付验收

2026-10-10。仅tools/wubu_tool内修改；正式服务、正式数据库、其他朝汐目录及物簿源码未修改，未升级或重启正式服务。

## 适配结果

- package/pyproject版本0.2.1，本地contract.json为65个operation，保留原四个工具，新增33个平层工具，共37个。
- 购买支持account_id、item_type和location；耐用品逐件quantity=1，服务UNTRACKED。
- ledger_tools.py提供账户、分类、充值、赠送、退款、汇总和耐用品能力；字段验证、权限、稳定键与路径编码随SDK输出。
- 余额回复区分自由资金与消费储值；充值赠送不计普通收入。服务错误、警告、建议行动和幂等重放事实保留。
- zhaoxi_notes.py通用注释导出到全部工具description，朝汐能随工具定义读取；需重新加载定义后生效。
- 原Connection refused按需启动机制保持；验收客户端autostart=false。
- sync_schema.py支持--openapi-file，契约同步自物簿本地internal/web/static/openapi.json v0.2.1。
- verify_live.py更新为v0.2.1纯读取/预检查验收，输出独立版本报告。本次未在正式服务运行。

## 自动化验证

命令：.\\.venv\\Scripts\\python.exe -B -m unittest discover -s tools/wubu_tool/tests -v

36 tests通过，其中8个v0.2.1专项测试。覆盖全部新增工具的schema、权限、写入键必填、稳定重放及冲突、
account路径转义、PATCH参数、布尔查询、BONUS筛选、退款关联、预验证不发请求、服务错误与告警。
既有购买、改单删除、超时未知结果、仅连接拒绝自启动及并发启动锁回归仍通过。

## 真实隔离服务验收

命令：.\\.venv\\Scripts\\python.exe -B -m tools.wubu_tool.integration_v021 --base-url http://127.0.0.1:12555 --allow-isolated-writes

健康响应版本0.2.1；autostart=false；仅委托方提供的临时validation.db写入。
94项检查全部通过，完整请求参数和ToolResult在INTEGRATION_V0.2.1.json。

- 实付100到账110产生TRANSFER_OUT100、TRANSFER_IN100、BONUS10；原键重试返回原结果，余额无重复。
- 普通收入汇总不含BONUS；消费20后余额90；退款10回原账户，再退款5到其他账户。
- 原消费账户统计本金100、赠送10、消费20、退款15、净消费5、余额100、赠送比0.1。
- 改分类只改变当前余额分类，历史不变；停用有余额消费账户保留剩余余额告警；恢复启用。
- 商家冲突失败并提供核对提示；实付10到账8保留少到账告警；自由资金账户不接受赠送。
- 耐用品399加维护50得到总成本449，维护扣款50；移动后STORED库存1、LOST库存0、ACTIVE库存1。
- 售出260原子入账且重放不重复收入；出售和报废后不可恢复ACTIVE。
- 普通收支、转账、绝对余额调整4321.08及对账4320.08、分类写入与资金查询均实际调用。

## 局限与加载

这是SDK→真实HTTP→临时数据库验收，未验证朝汐自然语言选工具、模型参数生成或UI完整会话。
正式服务若仍是旧版本，新接口会返回错误，需由物簿方按其流程升级；本次没有启动、升级或迁移正式服务。
不改朝汐启用配置、环境或运行进程；重新加载tool定义后，37个工具及注释才对当前会话可见。
验收脚本重复运行使用唯一名称/键及余额基线；失败调试与成功轮次的数据留在临时数据库，由委托方清理。
旧DELIVERY_V0.1.1.md与LIVE_VERIFICATION.json保留为历史证据。
