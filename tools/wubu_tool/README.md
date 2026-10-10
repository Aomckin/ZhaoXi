# 物簿 Tool v0.2.1

朝汐 SDK `>=1,<2` 独立工具包，package_id `wubu-tool`。朝汐自动发现本目录 `package.py`，无需安装依赖。
按物簿 v0.2.1 Account Classes 接入说明及本地 OpenAPI 实现；完整验收见 DELIVERY_V0.2.1.md。

## 工具入口（37 个）

| 名称 | 用途 | 权限 |
|---|---|---|
| `record_purchase` | 常用购买，后端匹配/创建商品及事务落账 | WRITE + LOCAL_STATE，保留朝汐默认确认 |
| `validate_purchase` | 购买预检查，不生成实体或幂等记录 | READ + NONE，无幂等键 |
| `wubu_inventory_event` | 按名称/规格/别名消耗、纠正、开封、用完、丢弃 | WRITE + LOCAL_STATE，保留默认确认 |
| `wubu` | 原高级入口：查询、耐用品、维护、完整购买 DTO、改单删除 | 动态判定；关键写入 WRITE + LOCAL_STATE |

普通购买不先查询、创建商品或分开改库存。商品基础名称、包装规格、数量、库存单位分别填写。
时间/CNY/source=agent 由简化购买后端补齐；按名称库存事件由适配器固定 source=agent。
旧高级调用DTO原样发送，兼容原来源、外部订单和既有幂等指纹；高级新事件填写source=agent，
改单保留原source/external_id，不把既有import/manual事件改为agent。

### record_purchase

只有items和稳定idempotency_key必填；每行name/quantity/unit必填，price/spec选填。
根级account_id/total/merchant/payment_method/note选填。account_id省略由后端使用默认付款账户。price是每库存单位单价，total是实际付款，均为CNY元。
单商品只有总价时省略price并填total；total省略按明细合计。金额全部未知时后端默认0，
朝汐须说明金额未确认，不编造实际付款。耐用品填item_type=DURABLE且quantity=1；服务填UNTRACKED。复杂账单可使用高级完整DTO。

```json
{"items":[{"name":"无糖可乐","spec":"2L","quantity":1,"unit":"瓶","price":5.5}],"idempotency_key":"purchase-20261006-001"}
```

语义是「无糖可乐、每瓶2L、买1瓶、每瓶¥5.50」，不能写quantity=2/unit=L。
首次购买东方树叶900ml同样直接传商品行。resolve_item未找到不阻止购买记账。
结果完整保留purchase_id、expense_amount、name/spec/quantity_added/unit/inventory_after、warnings/validation_status。
中文确认直接使用提交响应的快照，不额外查询；幂等重放返回原提交快照，不是重放时刻最新库存。
PURCHASE_AMOUNT_INCONSISTENT和SPEC_QUANTITY_CONFLICT会显式提示核对，不擅自修改数据。

### validate_purchase

与购买相同参数，无需、也不接受幂等键；只POST `/api/v1/purchases/validate`，不写账。

```json
{"items":[{"name":"东方树叶","spec":"900ml","quantity":1,"unit":"瓶","price":5}]}
```

HTTP虽为POST，权限仍READ/NONE，网络中断unknown_outcome=false。预检查通过不等于已记账。

### wubu_inventory_event

```json
{"action":"consume","name":"零度可乐大瓶","quantity":1,"idempotency_key":"consume-20261006-001"}
```

```json
{"action":"adjust","name":"无糖可乐","spec":"2L","quantity":5,"idempotency_key":"adjust-20261006-001"}
```

```json
{"action":"finish","name":"无糖可乐","spec":"2L","idempotency_key":"finish-20261006-001"}
```

consume.quantity是用掉量（正数），adjust.quantity是实际剩余（可0）；open/finish/discard不填quantity。
只请求 `/api/v1/items/对应动作`，同一后端事务解析名称/规格/别名并修改库存，不创建不存在的物品。
ITEM_AMBIGUOUS保留候选id/name/spec/unit/current_quantity，询问规格；用户选ID后可用高级wubu的item_id操作。

### 高级wubu与改单删除

原operation/query/payload入口保留，已同步65操作；字段见schema的oneOf分支或contract.json。
规格填spec或package_size/package_unit，库存unit分开。金额为元，Item.unit_price_cents为分。
事件时间带时区RFC3339，from含边界/to不含边界。

```json
{"operation":"get_purchase_event","purchase_id":"购买记录ID"}
```

改单先读完整明细，payload.expected_updated_at=刚读取的updated_at，保留原source/external_id及保留行的id/item_id。
operation=amend_purchase_event发送完整PurchaseAmendment到PUT `/api/v1/purchases/{id}`。
删除用delete_purchase_event发送DELETE同一路径：

```json
{"operation":"delete_purchase_event","purchase_id":"购买记录ID","idempotency_key":"delete-20261006-001","payload":{"expected_updated_at":"刚读取的 updated_at"}}
```

GET/PUT/DELETE购买路径均使用purchase_id，其他物品路径使用item_id。
改单/删除不拆成库存和费用操作，不自动补查、替换版本或行标识。重试复用原版本、原键和原DTO；
409需核对，不自动更新版本或换键。高级validate_purchase及record_purchase_event + query.dry_run=true亦为只读。

## 错误、重试与自启动

error.code/message/retryable/suggested_action/candidates、request_id和validation_status完整保留在ToolResult.data。
metadata.retryable优先使用服务返回值；不存在/歧义附中文行动提示。失败不能说已记账，预检查不能说已落账。
关键写入要求1–200个可打印ASCII字符的稳定幂等键，由调用方保存，不自动生成。
超时、连接重置、5xx或无效响应不自动重复业务请求，写入未知结果unknown_outcome=true；读取和预检查为false。
仅OS Connection refused（ECONNREFUSED/10061）触发既有按需启动：隐藏窗口后台执行同级物簿scripts/start.ps1，
健康就绪后原参数/原键继续一次。并发调用共享启动锁，发现/构造工具、健康检查及schema更新不会启动物簿。

配置使用朝汐进程环境（本次不修改.env、开关或安装环境）：

```powershell
$env:ZHAOXI_TOOL_WUBU_ENABLED = 'true'
$env:ZHAOXI_TOOL_WUBU_BASE_URL = 'http://127.0.0.1:8026'
$env:ZHAOXI_TOOL_WUBU_TIMEOUT_SECONDS = '15'
$env:ZHAOXI_TOOL_WUBU_AUTOSTART_ENABLED = 'true' # 默认true，false关闭
$env:ZHAOXI_TOOL_WUBU_PROJECT_DIR = 'E:\桌面\改变世界的魔法\物簿' # 默认朝汐同级
$env:ZHAOXI_TOOL_WUBU_STARTUP_TIMEOUT_SECONDS = '8'
```

仅接受本机HTTP根地址，禁用代理/重定向。自动启动仅支持8026，自定义端口关闭自动启动。
用户需重启朝汐加载新工具，并在工具控制界面核对/启用新名称。本次不重启、启用或安装。

## 验证与范围

从朝汐根目录运行，-B避免写其他目录缓存：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/wubu_tool/tests -v
.\.venv\Scripts\python.exe -B -m tools.wubu_tool.sync_schema
.\.venv\Scripts\python.exe -B -m tools.wubu_tool.verify_live
```

sync_schema仅读当前OpenAPI，更新本目录contract.json；去除请求的readOnly字段，明确规格与库存单位。
verify_live只发送GET和POST `/purchases/validate`，禁用自启动，报告位于LIVE_VERIFICATION.json。
对商品、购买、费用、库存历史全部分页记录做前后SHA256比较；这是API实体快照，不是数据库文件校验。

28项自动测试通过，含旧入口33操作路由/权限、简化购买、首次/再次购买响应、别名、双规格歧义、
幂等重放、预检查只读、改单删除版本与行标识、警告/结构化错误、真实SDK发现及暴露schema、既有自启动8项回归。
写入测试用脚本化模拟HTTP服务，库存/账目响应是测试夹具；它验证适配器，不证明真实SQLite事务或匹配算法。
真实v0.1.1的4次预检查通过：2L可乐、900ml东方树叶、2000ml规格等价、金额/规格警告；API实体前后快照一致。
未向正式物簿发送购买/库存/改单/删除请求，未读改物簿源码或数据库；文件修改全部位于tools/wubu_tool。
未启动临时物簿二进制，未完成朝汐自然语言对话验收。


## v0.2.1 账户、资金与耐用品

保留原四个入口，另提供33个平层工具：账户创建/编辑/查询/统计、默认付款账户、余额、
收入/支出/转账/充值/赠送/退款/调整/对账、资金汇总/分类、耐用品查询/出售/报废/移动/状态/历史/成本及维护。
字段直接填在工具参数根级，不使用operation/payload。所有写操作要求稳定idempotency_key。

- STORAGE自由资金和CONSUMPTION消费储值分开说明；total_value不是自由现金。
- top_up_account区分实付paid_amount和到账credited_amount；赠送BONUS不计普通收入。
- record_refund必须关联原购买或支出，省略account_id回原账户；实际退货才传return_items。
- 售出耐用品用sell_item一次事务入账，不再补record_income；维护费用也由后端一次扣款。
- 商家冲突必须核对；少到账和停用剩余余额警告保留并提示。
- 给朝汐的通用注释在zhaoxi_notes.py，加入全部description；更新后需重新加载工具定义。

隔离真实联调脚本integration_v021.py要求显式--allow-isolated-writes，且只允许已授权127.0.0.1:12555。
它始终关闭自启动；正式服务不用于写入验收。历史v0.1.1交付和报告保留。
