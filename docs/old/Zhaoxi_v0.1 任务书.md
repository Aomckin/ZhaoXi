# Zhaoxi v0.1 · Awakening 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.1 · Awakening**  
> 定位：Zhaoxi Core 第一版  
> 目标：**让朝汐第一次作为一个完整、可扩展的 Agent 独立运行。**
>
> 本版本只建设“朝汐本体”，不接入 Life HUD、GitHub、Calendar、Gmail 等真实业务系统。  
> 这些能力全部属于后续独立的 Tools。

---

# 1. 本版本一句话目标

完成一条真正可运行的 Agent 主链路：

```text
用户输入
→ 构造上下文
→ 调用模型
→ 模型决定直接回答 / 调用 Tool
→ 执行 Tool
→ 把结果返回模型
→ 模型生成最终回复
```

v0.1 完成后，朝汐至少应该能够：

```text
用户：现在几点？
朝汐：识别需要工具 → 调 current_time → 返回自然语言结果

用户：12 * 17 等于多少？
朝汐：识别需要工具 → 调 calculator → 返回结果

用户：今天有点累。
朝汐：不调用工具 → 直接正常对话
```

验收重点不是“功能多”，而是：

> **Core 架构正确，并且后续新增真实 Tool 时不需要改 Agent 主流程。**

---

# 2. 技术方向

朝汐主体使用 Python。

建议：

- Python 3.12+，如当前项目已固定版本则沿用
- Pydantic v2：配置、消息、Tool Schema、结构化数据模型
- httpx：模型 HTTP 调用
- PyYAML：人格配置
- python-dotenv：本地环境变量
- pytest：测试
- 标准 logging 或轻量封装：日志

可以加入 Typer / Rich 做 CLI，但不是必须条件。

## 明确禁止

v0.1 不要为了“Agent 感”过早引入：

- LangChain
- LangGraph
- CrewAI
- AutoGen
- 多 Agent
- 向量数据库
- RAG
- 长期 Memory
- MCP 全家桶
- 复杂 Workflow Engine

除非项目已经明确依赖，否则优先自己完成最小 Agent Runtime。

目的：

> **先真正理解并拥有自己的 Agent Core，而不是让框架替项目决定架构。**

---

# 3. 顶层架构

建议目录：

```text
Zhaoxi/
├── src/
│   └── zhaoxi/
│       ├── core/
│       │   ├── agent.py
│       │   ├── context.py
│       │   ├── conversation.py
│       │   └── message.py
│       │
│       ├── models/
│       │   ├── base.py
│       │   ├── openai_compatible.py
│       │   └── types.py
│       │
│       ├── tools/
│       │   ├── base.py
│       │   ├── registry.py
│       │   └── builtin/
│       │       ├── echo.py
│       │       ├── calculator.py
│       │       └── current_time.py
│       │
│       ├── personality/
│       │   ├── loader.py
│       │   └── zhaoxi_v1.yaml
│       │
│       ├── session/
│       │   ├── base.py
│       │   └── memory.py
│       │
│       ├── config/
│       │   ├── settings.py
│       │   └── logging.py
│       │
│       └── cli.py
│
├── tests/
│   ├── core/
│   ├── models/
│   ├── tools/
│   └── integration/
│
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── main.py
```

允许根据实际项目风格微调，但必须保持以下边界：

```text
Core
Models
Tools
Personality
Session
Config
Interface
```

不能把所有逻辑堆进 `main.py`。

---

# 4. Core 设计

## 4.1 Message

定义统一消息模型。

至少支持：

```text
role:
- system
- user
- assistant
- tool

content
tool_calls
tool_call_id
name
metadata
timestamp
```

内部所有 Provider、Conversation、Agent Runtime 尽量统一使用自己的 Message 类型。

不要让 OpenAI / Gemini 等第三方 API 的消息结构直接污染整个项目。

---

## 4.2 Conversation

负责当前会话。

职责：

- 保存当前 Session 消息
- 追加 user / assistant / tool 消息
- 获取最近上下文
- 清空 Session
- 基础 Token / 条数裁剪
- 为 Agent 构建 messages

v0.1 可以只使用内存保存。

明确：

> Conversation 是短期会话状态，不是长期 Memory。

---

## 4.3 Context Builder

负责构造每次模型调用需要的完整 Context。

推荐组合：

```text
Personality / System Prompt
+
当前运行规则
+
可用 Tool 定义
+
最近 Conversation
+
本轮输入
```

Context 构造逻辑集中管理。

禁止在 CLI、Provider 或 Tool 内拼 Prompt。

---

# 5. Model Provider 抽象

## 5.1 Base Provider

定义统一接口，例如概念上：

```python
class ModelProvider(ABC):
    async def generate(
        self,
        messages,
        tools=None,
        **kwargs
    ) -> ModelResponse:
        ...
```

具体签名可调整。

必须抽象出：

- 输入消息
- Tool Schema
- 模型参数
- 普通文本回复
- Tool Call 回复
- Provider Error

Core 不知道具体供应商。

---

## 5.2 第一版 Provider

优先实现一个：

> **OpenAI-compatible Provider**

配置：

```env
ZHAOXI_MODEL_BASE_URL=
ZHAOXI_MODEL_API_KEY=
ZHAOXI_MODEL_NAME=
```

这样可以兼容大量支持 OpenAI 风格接口的模型服务。

如果开发方便，也可以额外实现官方 OpenAI Provider，但不得让 Core 与其耦合。

---

## 5.3 ModelResponse

内部统一结构至少包含：

```text
content
tool_calls
finish_reason
usage
raw_metadata
```

Tool Call 至少包含：

```text
id
name
arguments
```

不得让 Core 到处读取厂商私有字段。

---

# 6. Tool System

这是 v0.1 的核心之一。

目标：

> **后续新增 Life HUD Tool 时，只需要注册 Tool，不改 Agent Runtime。**

---

## 6.1 Tool Base

每个 Tool 至少拥有：

```text
name
description
input_schema
execute()
```

建议：

```python
class Tool(ABC):
    name: str
    description: str

    def schema(self) -> dict:
        ...

    async def execute(self, arguments: dict) -> ToolResult:
        ...
```

---

## 6.2 ToolResult

统一 Tool 执行结果。

建议字段：

```text
success
content
data
error
metadata
```

Tool 发生异常时：

- 不允许直接炸穿 Agent Runtime
- 捕获后转成 ToolResult
- 交给模型判断如何向用户解释

---

## 6.3 Tool Registry

实现统一注册中心。

至少支持：

```text
register(tool)
unregister(name)
get(name)
list()
schemas()
```

禁止：

```python
if tool_name == "calculator":
    ...
elif tool_name == "current_time":
    ...
```

Agent Runtime 只能通过 Registry 找工具。

---

# 7. v0.1 内置测试 Tools

只实现少量工具验证架构。

---

## 7.1 echo

用途：

- 验证参数解析
- 验证 Tool Call
- 验证 Tool Result

输入：

```text
message: string
```

输出原内容。

---

## 7.2 calculator

只处理安全的基础数学表达式。

支持：

```text
+
-
*
/
%
**
()
```

要求：

- 禁止直接 `eval()` 任意 Python
- 使用安全解析方式
- 非法表达式返回明确错误

---

## 7.3 current_time

返回当前时间。

至少包含：

```text
ISO datetime
timezone
human readable
```

v0.1 可以使用系统本地时区。

后续再扩展为真正的时间 / 日历 Tool。

---

# 8. Agent Runtime

实现朝汐最核心的循环。

伪流程：

```text
1. receive(user_message)

2. Conversation.add(user)

3. build_context()

4. provider.generate()

5. if direct response:
       save assistant message
       return

6. if tool calls:
       for each call:
           validate arguments
           find tool
           execute
           append tool result

7. provider.generate() again

8. repeat until:
       final response
       max steps
       timeout
       cancelled
       unrecoverable error
```

---

## 8.1 v0.1 必须支持

- 直接回答
- 单 Tool Call
- 同一轮多个 Tool Call
- Tool Result 回填
- 再次模型推理
- 最大迭代次数
- Tool 不存在
- Tool 参数错误
- Tool 执行异常
- Provider 异常
- 超时
- 最终回复

---

## 8.2 默认限制

建议：

```text
max_agent_steps = 8
```

达到最大步骤：

- 停止继续执行
- 给出可理解的错误
- 写日志

避免模型无限 Tool Loop。

---

## 8.3 不实现 Planner

v0.1 的多步执行只是 Agent Loop 自然产生的 Tool Calling。

不要额外实现：

- Task Planner
- Plan Tree
- DAG
- Workflow
- Autonomous Task

这些属于后续版本。

---

# 9. Personality

朝汐人格属于 Core，不是 UI 皮肤。

建立独立配置，例如：

```text
src/zhaoxi/personality/zhaoxi_v1.yaml
```

建议结构：

```yaml
identity:
  name: 朝汐
  romanization: Zhaoxi
  role: personal agent

relationship:
  ...

tone:
  ...

behavior:
  ...

boundaries:
  ...

service_style:
  ...
```

---

## 9.1 v0.1 人格目标

先保证：

- 知道自己是谁
- 知道自己的角色
- 有稳定称呼方式
- 有基础犬娘女仆风格
- 不影响任务执行清晰度
- 不过度角色扮演
- 遇到 Tool Error 时仍然准确说明事实

人格配置由 Loader 转成 System Prompt。

不要把长 Persona 字符串硬编码在 Agent 类中。

---

# 10. Session

v0.1 只做轻量 Session。

接口建议：

```text
create
get
save
delete
list
```

第一版可实现：

```text
InMemorySessionStore
```

用途：

- 同一次启动中的多个会话
- 为后续持久化预留接口

暂时不要做：

- SQLite 长期对话
- Memory
- Embedding
- 对话检索

---

# 11. Config

建立统一 Settings。

支持：

```text
.env
环境变量
默认配置
```

至少：

```env
ZHAOXI_MODEL_BASE_URL=
ZHAOXI_MODEL_API_KEY=
ZHAOXI_MODEL_NAME=

ZHAOXI_LOG_LEVEL=INFO
ZHAOXI_MAX_AGENT_STEPS=8
```

提供 `.env.example`。

`.env` 必须写入 `.gitignore`。

严禁提交 API Key。

---

# 12. Logging

日志至少区分：

```text
APP
MODEL
AGENT
TOOL
ERROR
```

每次 Agent 请求建议生成：

```text
request_id / trace_id
```

日志能够看出：

```text
收到输入
→ 第一次模型调用
→ 请求哪个 Tool
→ Tool 参数
→ Tool 执行结果
→ 第二次模型调用
→ 最终回答
```

注意：

- API Key 绝不能进日志
- 默认不要完整记录敏感环境变量
- 原始 Provider Response 可放 DEBUG，而不是 INFO

---

# 13. CLI

v0.1 只需要最简单的可交互入口。

例如：

```bash
python main.py
```

出现：

```text
Zhaoxi v0.1 · Awakening

You > 
```

支持：

```text
普通聊天

/clear
清空当前 Conversation

/tools
显示注册 Tool

/exit
退出
```

可选：

```text
/debug
/session
```

CLI 只负责输入输出。

禁止把 Agent 业务逻辑写进 CLI。

---

# 14. Error Handling

统一异常类型，例如：

```text
ZhaoxiError
├── ConfigError
├── ProviderError
├── ToolError
├── ToolNotFoundError
├── ToolValidationError
├── AgentLoopError
└── SessionError
```

不要求层级完全一致，但必须统一处理。

最终用户不应看到一大坨 Python Traceback。

开发日志中需要保留 Traceback。

---

# 15. Testing

v0.1 必须有测试，不接受“能跑就算完成”。

---

## 15.1 Tool Tests

覆盖：

- Registry 注册
- 重名处理
- Tool 查找
- Tool Schema
- calculator 正常表达式
- calculator 非法输入
- echo
- current_time

---

## 15.2 Provider Mock

不要让测试依赖真实 LLM API。

实现 Fake / Mock Provider：

```text
输入特定消息
→ 返回直接回复

输入特定消息
→ 返回 Tool Call

收到 Tool Result
→ 返回最终回复
```

---

## 15.3 Agent Integration Tests

至少：

### Case A：直接回答

```text
User
→ Model
→ Final
```

### Case B：Tool Call

```text
User
→ Model asks calculator
→ Tool
→ Model
→ Final
```

### Case C：Tool Error

```text
User
→ Model calls invalid tool
→ Tool error
→ Model
→ Graceful final response
```

### Case D：循环保护

模型不断请求工具时：

```text
达到 max_agent_steps
→ Runtime 自动终止
```

---

# 16. README

README 至少说明：

## Zhaoxi 是什么

明确：

> Zhaoxi 是个人 Agent Core。

不是：

- Life HUD 后端
- ChatBot Demo
- 多 Agent 框架

---

## Architecture

至少展示：

```text
Interface
   ↓
Zhaoxi Core
   ↓
Tool Registry
   ↓
Tools
```

---

## Quick Start

包含：

```text
环境要求
安装
.env
运行
测试
```

---

## 当前能力

v0.1：

- Conversation
- Personality
- Model Provider
- Agent Runtime
- Tool Calling
- Built-in Tools

---

## Roadmap

简要链接后续：

```text
v0.2 Memory
v0.3 Planner
v0.4 Permission
...
```

---

# 17. v0.1 非目标

以下内容明确不做，Coding Agent 不要顺手扩展：

- Life HUD 接入
- GitHub 接入
- Calendar 接入
- Gmail 接入
- 文件搜索
- 浏览器
- 天气
- 长期 Memory
- Embedding
- Vector DB
- RAG
- Planner
- Workflow
- 主动 Agent
- 定时任务
- 权限确认系统
- Desktop GUI
- Web UI
- Voice
- TTS
- QQ Bot
- 多 Agent
- 自动化设备控制

如果为了未来扩展需要预留接口，可以预留。

**不要提前实现。**

---

# 18. 代码质量要求

## 必须

- 清晰模块边界
- 类型标注
- Docstring 用于公共接口
- 避免超长函数
- 避免循环依赖
- 配置与代码分离
- Provider 与 Core 解耦
- Tools 与 Core 解耦
- CLI 与 Core 解耦
- 测试不依赖真实 API
- `.env` 不提交

## 不要

- 一个 `agent.py` 写几千行
- 大量魔法字符串
- 到处读取环境变量
- Tool 名硬编码分支
- Core 读取第三方 Provider 私有响应
- 为“可能以后用到”创建几十层抽象

原则：

> **能支撑下一阶段扩展的最小正确架构。**

---

# 19. 完成后的预期调用链

```text
CLI
 │
 ▼
ZhaoxiAgent
 │
 ├── Conversation
 ├── Personality
 ├── ContextBuilder
 │
 ▼
ModelProvider
 │
 ▼
Tool Call
 │
 ▼
ToolRegistry
 │
 ▼
Tool.execute()
 │
 ▼
ToolResult
 │
 ▼
Conversation
 │
 ▼
ModelProvider
 │
 ▼
Final Response
```

后续 Life HUD 接入时应当只是：

```text
ToolRegistry.register(LifeHudTool)
```

而不是重新改造整条 Agent 链路。

---

# 20. 最终验收清单

## 启动

- [ ] 项目能够正常安装依赖
- [ ] `.env.example` 完整
- [ ] 缺少关键模型配置时给出清晰提示
- [ ] CLI 能正常启动

## Conversation

- [ ] 能连续多轮聊天
- [ ] `/clear` 有效
- [ ] Session 与 Core 解耦

## Model

- [ ] OpenAI-compatible Provider 可用
- [ ] Provider 可替换
- [ ] Core 不依赖厂商私有类型

## Tools

- [ ] Tool Base 完成
- [ ] Tool Registry 完成
- [ ] Tool Schema 可传给模型
- [ ] echo 可用
- [ ] calculator 可用
- [ ] current_time 可用

## Agent

- [ ] 直接回答成功
- [ ] Tool Call 成功
- [ ] Tool Result 可回填
- [ ] 模型能够基于 Tool Result 给出最终回答
- [ ] Tool 参数错误不会使程序崩溃
- [ ] Tool 不存在不会使程序崩溃
- [ ] Provider Error 有统一处理
- [ ] max_agent_steps 有效

## Personality

- [ ] 人格独立配置
- [ ] `朝汐 / Zhaoxi` 名称正确
- [ ] 人格不会污染 Core 代码

## Engineering

- [ ] pytest 通过
- [ ] 无 API Key 泄露
- [ ] README 完成
- [ ] 基础日志完成
- [ ] 目录结构清晰

---

# 21. 版本完成标准

当下面三种交互全部真实跑通时，v0.1 才算完成。

### ① 不需要 Tool

```text
暗苟：今天有点累。

朝汐：
直接根据 Conversation + Personality 正常回复。
```

### ② 自动调用 Tool

```text
暗苟：现在几点？

朝汐：
识别问题
→ current_time
→ 获取真实结果
→ 自然回答
```

### ③ Tool 参与推理

```text
暗苟：帮我算一下 17 * 23，再告诉我结果。

朝汐：
→ calculator
→ 获得 391
→ 返回最终自然语言回复
```

并且从日志中能够完整追踪：

```text
User
→ Model
→ Tool Call
→ Tool Result
→ Model
→ Final
```

---

# 22. 本版本结束后的下一步

v0.1 完成后不要继续偷偷扩功能。

先验收 Core。

确认架构没有以下问题：

```text
新增 Tool 是否需要改 Agent？
切换模型是否需要改 Core？
更换 CLI 为 Web 是否需要改 Agent？
Personality 是否可以独立修改？
Tool Error 是否能够被 Runtime 正常消化？
```

全部通过后：

> **Zhaoxi v0.1 · Awakening 正式结束。**

下一阶段：

```text
Zhaoxi Core v0.2 · Memory
```

以及第一件真正属于朝汐的外部工具：

```text
lifehud-tool
```

---

# 最终原则

> **v0.1 不是为了让朝汐“什么都会”。**
>
> **v0.1 是为了让朝汐拥有一个以后可以不断学会新东西，而不需要反复换脑子的身体。**

先让她醒来。

然后，再把世界一件一件递到她手里。
