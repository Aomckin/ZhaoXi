# 朝汐侧 v0.1.1 交付记录

日期：2026-10-06。package_version：0.1.1，requires_sdk：>=1,<2。

## 交付

- record_purchase：items + 稳定 idempotency_key；每行name/quantity/unit必填，price/spec选填；根级total/merchant/payment_method/note选填。直接POST /api/v1/purchases/record，无查询/建商品前置。
- validate_purchase：相同购买参数，无键，POST /purchases/validate，READ + NONE；成功明确未写入，超时unknown_outcome=false。
- wubu_inventory_event：按名称/规格/别名调用后端事务动作，consume/adjust需quantity，open/finish/discard不填；固定source=agent。
- wubu：旧入口保留，契约同步33操作，包括PUT改单、DELETE撤销；三种购买路径均用purchase_id；预检查正确识别为只读。
- 中文购买确认直接使用服务返回的金额和库存快照，展示warnings/validation_status；错误保留服务code/message/retryable/suggested_action/candidates。
- 原Connection refused按需启动实现不变，所有工具共享配置过的同一客户端。超时不盲重试，写入确认策略不变。
- 单改使用原source/external_id、行id/item_id、expected_updated_at；不自动查询新版本或分开操作费用/库存。稳定键及原DTO透传。

## 文件

修改：client.py、contract.json、package.py、pyproject.toml、README.md、sync_schema.py、tool.py、tests/test_wubu.py。
新增：high_level.py、results.py、verify_live.py、LIVE_VERIFICATION.json、tests/test_v011.py、本记录。
autostart.py及test_autostart.py保留。
全部文件均位于朝汐tools/wubu_tool，没有安装或修改其余朝汐源码、配置、虚拟环境、Git、数据或缓存。
Python命令全部使用-B，不启动/重启朝汐。保留已有缓存与他人的文件改动。

## 验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/wubu_tool/tests -v
.\.venv\Scripts\python.exe -B -m tools.wubu_tool.verify_live
```

28项unittest全部通过，路由测试逐项覆盖33个高级操作。真实SDK discover_tool_packages查到wubu-tool 0.1.1，
create_tools返回record_purchase、validate_purchase、wubu_inventory_event、wubu；测试直接检查其实际schema，
购买根级仅items/key必填，明细仅name/quantity/unit必填，常用工具schema不暴露nullable。

写入回归使用脚本化模拟HTTP服务：一瓶2L可乐5.5、首次东方树叶900ml、再次购买同Item的1→3响应、
别名查询/购买/消耗/纠正、双规格候选、同键购买/消耗/纠正/用完/维护、版本与行标识保留、删改重放/409、
警告/结构化错误、纯读预检查及网络分类。它验证客户端适配与请求/响应传递，不是实际物簿数据库事务验收。

真实服务healthz确认0.1.1，四次SDK→HTTP预检查通过：2L可乐、900ml东方树叶、2000ml规格等价、金额/规格警告。
只发送GET及POST /purchases/validate，没有正式购买/库存/删改请求，自动启动关闭。
商品/购买/费用/库存历史的全部分页API快照前后一致，详情及实际schema见LIVE_VERIFICATION.json。
这不是本对话对数据库文件的直接检查；物簿源码与非docs文件未读取。

## 加载与限制

用户需要让朝汐重新加载工具/重启，并在工具控制界面核对新工具的启用状态；本对话未执行。
没有自然语言端到端验收，没有临时物簿二进制→SQLite写入测试；更简洁schema不能保证模型供应商永不返回格式错误。
旧高级DTO保持原样，因此高级新事件由调用方填写source=agent；改单保持原source/external_id。
启动脚本仍使用物簿正式启动入口，自动启动只支持默认8026；自定义端口需关闭自启动。
