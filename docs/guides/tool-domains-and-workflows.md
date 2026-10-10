# 动态能力域与工作流管理（v1.4.8）

## 工具自描述

工具类可以声明 `domain`、`domain_description`、`domain_boundaries`，并沿用实际 `group`、`summary`、启用/可用/暴露状态。Registry Manifest 每轮生成 Tool Domain Map，模型在调用能力发现工具之前已经能读到职责摘要。领域用途不授予权限；未随轮携带的具体工具仍按工具组加载。

```python
class PlantCareTool(Tool):
    domain = "植物养护"
    domain_description = "管理植物观察与养护计划。"
    domain_boundaries = "不代替医疗、财务或日程系统。"
```

新增工具在自身实现或 Provider 中提供这些可选元数据，无需修改 `tools/domain_map.py`。没有元数据时回退到注册 group/工具说明，不编造职责边界；不把固定四领域或工具名映射塞进提示生成器。可用性改变后下一轮重新读取，不缓存旧能力快照。

## 工作流

Dashboard 的“工作流”展示真实目录、输入和依赖可用状态，支持新增/编辑 JSON、启停、移除及最近执行记录。管理页保存定义不会执行工具。新增/编辑时按 `WorkflowDefinition` 契约提供 ID、version、name、inputs、steps；图必须无环，有终止节点，工具名已注册。版本不能比同 ID 当前最高版本更低。

Owner 管理覆盖保存到 workflow DB 同目录的 `.management.json` 文件；使用临时文件替换原子保存，不修改安装包的 YAML。删掉流程会形成持久目录移除记录；已有运行保存的定义快照保留，输入/权限续跑仍走原状态机。

HTTP 入口为 `GET /api/workflows`、`GET /api/workflows/{id}`、`PUT /api/workflows/{id}` 和 `DELETE /api/workflows/{id}`，使用现有本机/桌面鉴权。Router 只选当前 enabled 且依赖 available 的流程；旧提示不能绕过停用状态。

历史 Iron Curtain 演示仍只是两条具体注册流程，不代表日用任务已经被覆盖。日用业务模板需要先确定真实工具契约和使用情境，再登记和验证；不自动生成一批空壳流程充数。
