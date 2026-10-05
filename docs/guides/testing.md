# 测试指南

更新：2026-10-05。从仓库根目录运行；使用装有 dev 依赖的 Python，以及 Node.js。

## 统一入口

```powershell
.\.venv\Scripts\python.exe scripts/test.py
.\.venv\Scripts\python.exe scripts/test.py --suite core
.\.venv\Scripts\python.exe scripts/test.py --suite tools
.\.venv\Scripts\python.exe scripts/test.py --suite web
```

| 套件 | 内容 |
| --- | --- |
| `core` | `pytest tests`，包含核心单元、接口与装配集成测试 |
| `tools` | LifeHUD / Career / MCP / MarkItDown Python；Career Node 冒烟与 HTTP API |
| `web` | `tests/web/*.test.cjs`，Node 内置测试运行器，无浏览器 |
| `all`（默认） | 上述全部，顺序执行，任一失败最终返回非零退出码 |

不同 Tool 包的 Python 测试分进程执行，避免同名 `test_package.py` 冲突。缺少 Node 不会静默跳过。MarkItDown 的本地转换测试还要求该工具自己的运行环境已安装。单独跑 `python -m pytest` 只覆盖 Core，不覆盖全部 Tool 和 Node 测试。

## 隔离约束

根 `conftest.py` 的 autouse fixture 清除测试进程继承的 `ZHAOXI_*` / `MCP_*` 配置、关闭 Settings 的 `.env` 读取，并屏蔽 Tool 发现读取本机 `.env`。默认运行时路径重定向到 `tmp_path/runtime`。显式传入测试路径继续有效。

对仓库 `.zhaoxi/`、`data/`、`config/` 的 SQLite 打开及 `Path.open` 写入增加失败保护，避免默认路径遗漏时覆盖真实状态。保护覆盖常用存储入口，不能替代正确注入路径；其他文件 API、子进程以及独立浏览器脚本仍须自行隔离。不要把备份恢复到真实目录作为测试清理方式。

pytest 临时目录为 `.pytest-tmp/`，缓存为 `.pytest_cache/`，均已忽略。`--basetemp` 每次会由 pytest 清空，所以仅用于测试；并行的独立运行须分别指定 `--basetemp=.pytest-tmp-<名字>`。

Career Node 测试只复制代码和空模板到系统临时目录，不复制用户配置或岗位数据；测试服务使用临时端口，关闭子进程后删除受路径检查保护的夹具目录。招聘 API 失败用合成异常验证降级。

## 浏览器与真实服务验收

Playwright 冒烟、原生 Desktop、真实模型/QQ 和记忆迁移验收有独立环境要求，统一离线入口不自动执行。浏览器脚本通过 `ZHAOXI_PLAYWRIGHT` 定位 Playwright，使用本机 Edge。已有脚本的输出目录和 fixture 配置须逐项确认；回复分组脚本本轮改用独立临时目录和可指定输出路径。

回复分组浏览器检查可分两个终端运行：

```powershell
.\.venv\Scripts\python.exe tests/web/reply_group_smoke_server.py
# 另一终端设置 ZHAOXI_PLAYWRIGHT 为已安装的 playwright 包路径，再执行：
node tests/web/reply_group_smoke.cjs
```

服务默认端口 18768，可通过 `ZHAOXI_TEST_PORT` 修改；客户端对应设置 `ZHAOXI_TEST_BASE_URL`。默认报告写入 `.pytest_cache/reply-group-browser-acceptance.json`，可通过 `ZHAOXI_TEST_OUTPUT` 修改；完成后退出夹具服务。

真实凭据、用户数据库和外部连接不能作为离线回归的默认输入。涉及真实模型或业务写入的验收需单独授权并记录输入、隔离方式与失败尝试。

## 测试取舍

优先保留风险较高的行为覆盖：权限续跑、预算停止、工具副作用只执行一次、回复恢复、证据边界、存储迁移和接口交付。不要按测试数量直接删测试。

分段与显示节奏测试直接加载回复模块，避免通过函数在大文件中的位置截取代码；Python 只验证静态资源交付与加载顺序。版本一致性由 release 验证脚本与通用测试维护，避免历史版本测试重复写死当前版本号。历史场景文件可保留，是否合并取决于它是否覆盖独立风险。

最新验证结果及仍需整理的测试见 [维护记录](../maintenance/2026-10-04-architecture-and-tests.md)。
