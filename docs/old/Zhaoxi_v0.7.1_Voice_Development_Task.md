# Zhaoxi v0.7.1 · Voice 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.7.1 · Voice**  
> 开发基线：**v0.7 · Presence**  
> 主平台：**Windows 10，单用户、本机运行**  
> 目标：**在不复制 Agent Core 的前提下，为现有 Desktop Presence 增加可控、可取消、可复核的按键说话与语音播报能力。**

本任务书承接：

- `docs/Zhaoxi_v0.7_Presence_Development_Task.md` 中明确延后的 Voice 边界；
- `src/zhaoxi/interfaces/` 的 UnifiedMessage / UnifiedResponse / InterfaceGateway；
- `src/zhaoxi/desktop/` 的单实例 Desktop Host、托盘、快捷键与通知；
- 现有 Permission、Proactive、Quiet / Night 和本地安全边界。

核心原则：

> **Voice 是新的输入与输出方式，不是第二套朝汐。**

语音输入最终必须形成普通 `UnifiedMessage`，语音输出只能播报 Core 已经生成的安全自然语言回复。Recorder、STT 和 TTS 都不能选 Tool、执行 Workflow、批准权限或直接修改 Memory。

---

## 1. 版本定位

v0.7 已经完成：

```text
Desktop / Web / CLI
  ↓
Interface Gateway
  ↓
同一个 Zhaoxi Core
```

v0.7.1 在 Desktop 入口旁增加 Voice Adapter：

```text
Push-to-talk
  ↓
Audio Recorder
  ↓
STT Provider
  ↓
Transcript Review
  ↓
UnifiedMessage(channel=voice, origin=user)
  ↓
Interface Gateway → Zhaoxi Core
  ↓
UnifiedResponse
  ↓
可选 TTS Provider → Audio Player
```

本版解决的是：

> **用户主动按下按钮或快捷键，说一句话，确认转写后交给朝汐；朝汐回复后，可以按用户设置选择是否播报，并且随时能够停止。**

本版不解决“朝汐一直听着”“唤醒词叫醒”“远场麦克风阵列”等常驻监听问题。

---

## 2. 成功标准

v0.7.1 必须同时满足：

1. Desktop UI 提供明确的开始录音、停止、取消和状态反馈；
2. Recorder 有最大时长、大小、采样参数和单实例限制，不会无限录音；
3. 至少一个可实际使用的 STT Provider 能把中文语音转为可编辑 transcript；
4. transcript 默认先展示给用户复核，默认不自动发送；
5. 用户确认后，语音输入通过 `InterfaceGateway` 进入同一 Session 和 Core；
6. 至少一个可实际使用的 TTS Provider 能播报最终回复，并能立即停止；
7. TTS 不朗读 Debug、Tool JSON、Permission 内部字段、通知 payload 或隐藏内容；
8. Permission 仍通过可见 Permission Card 处理，语音不得直接批准 DANGEROUS 操作；
9. Quiet / Night、用户静音和当前交互状态能够确定性控制自动播报；
10. 无麦克风、设备断开、STT/TTS 超时、Provider 离线和取消操作均能恢复到文字交互；
11. 临时音频在成功、失败、取消和正常退出路径上均能清理；
12. Web、CLI 和 v0.7 Desktop 原有文字路径无回归；
13. 主要自动化测试不依赖真实麦克风、扬声器、云服务或真实 sleep。

---

## 3. 范围与优先级

### P0 · 发布阻塞

- Voice 领域模型与状态机；
- Audio Recorder 契约和一个 Windows 可用实现；
- Push-to-talk UI；
- STT Provider 契约和至少一个可用实现；
- transcript 复核、编辑、重试、取消和发送；
- `InterfaceChannel.VOICE` 与 Interface Gateway 接入；
- TTS Provider 契约和至少一个可用实现；
- TTS 播放、中断、队列清理和状态反馈；
- Quiet / Night / 用户静音播报策略；
- 临时文件、隐私、安全和错误恢复；
- Fake Recorder / STT / TTS 自动化测试；
- 本体完成后的集中黑盒冒烟。

### P1 · 体验完善

- 独立 Push-to-talk 快捷键，且与桌面呼出快捷键不冲突；
- 输入音量指示；
- STT language hint 和设备选择；
- TTS 语速、音量和声音选择；
- 用户主动点击“重播”；
- 长回复播报前确认或自动摘要为短播报文本；
- 录音开始和结束的非侵扰提示音。

### P2 · 有余量再做

- transcript 局部时间戳；
- 多候选转写；
- VAD 辅助停止，但不能替代用户可控停止；
- 本地 STT Provider 实验实现；
- 对常见专有名词的本地提示词表。

P1 / P2 未完成不阻塞 v0.7.1。不得为了高级音频体验推迟取消、清理、安全和文字降级路径。

---

## 4. 明确不做

本版不做：

- 唤醒词；
- 持续后台监听；
- 应用隐藏时自动开启麦克风；
- 未经操作就自动上传音频；
- 多人说话分离、说话人识别或声纹认证；
- 用声音识别用户身份；
- 语音克隆；
- 情感识别或根据声音推断健康状态；
- 远场降噪、回声消除和麦克风阵列优化；
- 电话、QQ、Discord 等实时语音通话入口；
- 完整流式 Agent 回答；
- 让 STT transcript 绕过用户确认直接执行高风险操作；
- 安装器、卸载器、开机自启、签名或干净环境发布工程；这些继续留给 v0.9；
- 为 Voice 重写 Conversation、Planner、Workflow、Permission 或 Proactive Core。

唤醒词和持续监听必须另立版本，并重新评估隐私、功耗、误唤醒与常驻资源占用。

---

## 5. 架构边界

### 5.1 目标结构

```text
Desktop UI
  ├─ Text Input ──────────────────────────────┐
  │                                           │
  └─ Push-to-talk                             │
       ↓                                      │
     VoiceRuntime                             │
       ├─ AudioRecorder                       │
       ├─ SpeechToTextProvider                │
       └─ TranscriptReview                    │
              ↓                               │
       UnifiedMessage(channel=voice) ─────────┤
                                              ↓
                                      InterfaceGateway
                                              ↓
                                         Zhaoxi Core
                                              ↓
                                       UnifiedResponse
                                              ↓
                                   SpeechPolicy → TTS → Player
```

必须保证：

- VoiceRuntime 不导入具体 Tool；
- STT 返回文本，不返回“应调用哪个 Tool”的指令；
- transcript 在用户确认前不是用户消息，不进入 Conversation、Memory 或 Planner；
- TTS 只接受经过 Voice Output Sanitizer 的最终用户可见文本；
- Voice Adapter 不直接操作 Permission Store；
- Voice 失败不影响文字输入、托盘、通知和 Core 生命周期；
- Voice 组件由 Desktop Host 在应用边界组装，可用 Fake 独立测试。

### 5.2 建议目录

```text
src/zhaoxi/
  voice/
    __init__.py
    models.py          # AudioSpec / Transcript / VoiceStatus / VoiceError
    recorder.py        # AudioRecorder ABC + Windows implementation
    stt.py             # SpeechToTextProvider ABC
    tts.py             # TextToSpeechProvider ABC
    player.py          # AudioPlayer / SpeechHandle
    policy.py          # 自动播报确定性策略
    sanitizer.py       # TTS 文本清洗和长度限制
    runtime.py         # Voice 状态机、取消、超时、清理
    providers/
      fake.py
      openai_stt.py    # 或 Spike 选定的首个真实 STT
      windows_tts.py   # 或 Spike 选定的首个真实 TTS
```

```text
tests/
  voice/
    test_models.py
    test_recorder.py
    test_runtime.py
    test_policy.py
    test_sanitizer.py
    test_provider_contracts.py
```

---

## 6. 技术 Spike 与 Provider 选择

阶段 1 先完成短 Spike，不直接把未经验证的音频库写进主链路。

### 6.1 Recorder Spike

至少比较并验证：

- Windows 麦克风设备枚举；
- 16 kHz、mono、PCM WAV 录制；
- 开始、停止、取消；
- 设备断开和占用；
- 60 秒上限；
- Python 3.12+ / 3.13 兼容性；
- 依赖大小和是否需要额外系统运行库。

优先选择边界单一、支持 callback 或 async bridge、能够明确关闭 stream 的实现。

### 6.2 STT Spike

至少验证一个真实 Provider：

- 中文普通话识别；
- WAV 输入；
- 超时和取消；
- 空音频、静音和过长音频；
- HTTP 错误清洗；
- 云端上传前的显式配置与 UI 标识。

首版可优先实现 OpenAI-compatible transcription Adapter，复用现有 `httpx`、Base URL、API Key 和超时习惯，但不得把聊天模型接口与音频接口硬编码为同一 Provider。

本地 Whisper 可作为 P2，不作为 v0.7.1 默认发布阻塞项，避免把模型下载、GPU/CPU 性能和打包体积一起拖入本版。

### 6.3 TTS Spike

至少验证：

- 中文声音可用性；
- 开始播报、停止和重复停止；
- 长文本；
- 切换声音、语速和音量；
- 设备缺失或切换；
- Python 进程退出时资源释放。

优先选择 Windows 本地 TTS，保证文字不必上传云端即可播报。若本地声音不可用，可保留云端 Provider，但不能成为唯一实现。

### 6.4 ADR 输出

Spike 完成后新增 ADR，记录：

- Recorder / STT / TTS 候选；
- 最终选择与版本范围；
- 数据是否离开本机；
- 取消语义；
- 线程和事件循环模型；
- 临时文件策略；
- 已知平台限制；
- 后续替换成本。

---

## 7. 领域模型

### 7.1 AudioSpec

最小字段：

```text
sample_rate_hz
channels
sample_width_bytes
encoding          # pcm_s16le / wav
max_seconds
max_bytes
```

首版推荐固定为：

```text
16000 Hz / mono / signed 16-bit PCM / WAV
```

Provider 如需其他格式，应在 Adapter 内转换，不让 UI 猜测音频格式。

### 7.2 AudioCapture

```text
capture_id
path
spec
started_at
stopped_at
duration_seconds
byte_size
device_id
sha256
```

要求：

- path 只能位于配置的临时音频目录；
- duration 和 byte_size 必须由实际文件或帧数计算；
- 不把音频内容写进日志、Trace 或模型上下文；
- capture_id 与 request_id 分离。

### 7.3 Transcript

```text
transcript_id
capture_id
text
language
provider
duration_seconds
created_at
confidence        # Provider 不提供时允许为空
```

Transcript 是“候选用户输入”，不是 Conversation Message。只有用户确认后才创建 `UnifiedMessage`。

### 7.4 VoiceStatus

```text
IDLE
RECORDING
TRANSCRIBING
REVIEWING
SENDING
SPEAKING
CANCELLING
FAILED
```

状态变化必须带：

```text
operation_id
previous_status
status
reason
timestamp
```

UI 只根据状态渲染，不自行推断 Recorder 或 Provider 是否仍在运行。

---

## 8. Voice 状态机

### 8.1 输入状态机

```text
IDLE → RECORDING → TRANSCRIBING → REVIEWING → SENDING → IDLE
  │         │              │            │          │
  └─────────┴──────────────┴────────────┴──────────┘
                    cancel / fail / timeout
                              ↓
                        CANCELLING
                              ↓
                            IDLE
```

规则：

- 同一时刻只允许一个录音和一个 STT 操作；
- `start_recording` 只能从 IDLE；
- `stop_recording` 只能从 RECORDING；
- `confirm_transcript` 只能从 REVIEWING；
- `retry_transcription` 复用已有 capture，不能偷偷重录；
- `cancel` 在所有非 IDLE 状态下幂等；
- 失败后必须保存可理解错误，但最终回到可再次录音或打字的状态；
- SENDING 后由 Interface Gateway 管理 Session 串行，不创建第二把不一致的锁。

### 8.2 输出状态机

```text
IDLE → SPEAKING → IDLE
           │
        stop / new input / quiet / exit
           ↓
        CANCELLING → IDLE
```

规则：

- 新的用户输入默认停止当前播报；
- 新的回复不叠加播放，首版不做多段队列；
- stop 重复调用安全；
- Desktop 退出前必须先停止 TTS；
- 语音播放失败不改变文字回复的成功状态。

---

## 9. Recorder

Recorder 契约建议：

```text
AudioRecorder.list_devices() -> list[AudioDevice]
AudioRecorder.start(spec, device_id) -> RecordingHandle
RecordingHandle.stop() -> AudioCapture
RecordingHandle.cancel() -> None
RecordingHandle.level() -> optional float
```

要求：

- start 成功后 UI 才显示“正在录音”；
- 使用 monotonic clock 计算上限；
- 达到最大时长自动停止并进入 TRANSCRIBING，但明确提示已触发上限；
- 写入随机命名的临时文件，不使用用户输入拼路径；
- 文件创建采用排他方式或安全临时文件 API；
- 设备枚举结果只保存稳定 ID 和展示名称；
- 设备断开后关闭 stream、清理不完整文件并回到文字路径；
- Recorder 回调不直接调用 Agent 或修改 UI；
- 音量指示数据限频，不写入日志。

默认上限建议：

```text
最大时长：60 秒
最大文件：4 MiB
静音不自动发送
```

---

## 10. STT Provider

接口建议：

```text
SpeechToTextProvider.transcribe(
    capture,
    language_hint,
    timeout_seconds,
    cancel_token,
) -> Transcript
```

要求：

- Provider 只读取受控 AudioCapture；
- 上传前检查大小、格式和时长；
- 云端 Provider 必须在设置中明确标记“音频会离开本机”；
- 未配置 Key 时返回可操作错误，不输出 traceback；
- 超时、认证失败、限流、格式错误和服务端错误分型；
- STT 不自动修饰成朝汐人格，不改写为命令；
- 空 transcript、仅标点或低可信结果进入 REVIEWING 并提示，不自动发送；
- Provider 原始 JSON 不进入普通 UI；
- 自动重试仅允许明确无副作用且没有得到结果的瞬时网络错误；
- 同一 capture 的重试次数有上限。

### Transcript Review

UI 至少支持：

```text
识别结果文本框
[发送] [重新识别] [重新录音] [取消]
```

要求：

- 用户可编辑；
- 默认 `auto_send=false`；
- 点击发送时使用编辑后的文本；
- 发送后 transcript 不单独写入 Memory；
- Conversation 只看到最终确认文本；
- Activity 标记输入来自 voice，但普通自然语言内容与文字消息一致。

---

## 11. Interface Gateway 接入

新增：

```text
InterfaceChannel.VOICE = "voice"
```

确认 transcript 后构建：

```text
UnifiedMessage(
  channel=VOICE,
  origin=USER,
  session_id=当前 Desktop Session,
  content=用户确认后的 transcript,
  metadata={
    "input_mode": "push_to_talk",
    "stt_provider": "..."
  }
)
```

metadata 只保存非敏感、短小的来源信息；不得放入：

- 音频路径；
- 原始音频；
- API Key；
- 设备底层标识；
- Provider 原始响应；
- 未确认 transcript。

Voice 与 Desktop 共享现有 request ID 幂等和 Session 串行规则。重复点击发送不能造成两次 Agent 执行。

---

## 12. TTS Provider 与播放

接口建议：

```text
TextToSpeechProvider.synthesize(
    text,
    voice,
    rate,
    volume,
    cancel_token,
) -> SpeechOutput | SpeechHandle

SpeechHandle.stop() -> None
SpeechHandle.wait() -> SpeechResult
```

若 Provider 支持直接播放，也必须通过统一 `SpeechHandle` 暴露停止能力。

### 12.1 播报内容

只允许播报：

- 最终 `UnifiedResponse.content`；
- 用户主动点击重播的已显示回复；
- 经 Proactive Policy 允许且 Voice Policy 再允许的短通知文本。

禁止播报：

- Debug Drawer；
- Activity 内部字段；
- ToolResult / WorkflowResult / Planner Trace；
- Permission 参数摘要之外的敏感数据；
- Markdown 链接目标、代码块、长表格和原始 JSON；
- Provider 错误详情或 traceback。

### 12.2 TTS Sanitizer

最小处理：

- 去 Markdown 结构符号；
- 代码块替换为“回复中包含代码，请查看屏幕”；
- URL 替换为“链接”；
- 超长文本截断或要求用户点击播报；
- 连续空白归一化；
- 保留中文标点带来的自然停顿；
- 结果为空时不调用 TTS。

Sanitizer 只改变播报副本，不改写聊天区原回复。

---

## 13. Voice Output Policy

自动播报由确定性策略决定，不交给模型自由判断。

输入：

```text
voice_enabled
auto_speak
response_origin
response_length
quiet_state
night_state
desktop_visible
user_is_recording
permission_pending
current_speech
explicit_user_action
```

输出：

```text
SPEAK_NOW
TEXT_ONLY(reason)
REQUIRE_CLICK(reason)
STOP_CURRENT(reason)
```

默认矩阵：

| 场景 | 默认行为 |
|---|---|
| 用户通过 Voice 发起，短普通回复 | auto_speak 开启时播报 |
| 用户通过文字发起 | 默认只显示文字 |
| Quiet Mode | 不自动播报 |
| Night Mode | 不自动播报 |
| Permission 等待 | 只显示卡片，不自动朗读敏感摘要 |
| 正在录音 | 停止当前 TTS，不启动新 TTS |
| Proactive INFO / NOTICE | 默认不自动播报 |
| Proactive IMPORTANT / URGENT | 默认仍只通知；用户显式开启后才能播报 |
| 用户点击“朗读” | 在非全局静音时播报 |

即使 Proactive Priority 为 URGENT，也不能绕过用户的 Voice 静音或 Night 禁播策略。

---

## 14. Desktop UI

### 14.1 输入区

建议状态：

```text
IDLE           [按住说话]
RECORDING      ● 正在录音 00:12  [停止] [取消]
TRANSCRIBING   正在识别…          [取消]
REVIEWING      [可编辑 transcript] [发送] [重试] [重录] [取消]
FAILED         识别失败：可恢复原因 [重试] [打字]
```

要求：

- 录音状态必须显眼，不能只靠颜色；
- 开始和停止均有文字反馈；
- 不允许双击创建两个 Recorder；
- 页面刷新或 SSE 重连不能让后台 Recorder 失去控制；
- Desktop Host 退出时取消 VoiceRuntime；
- Web 独立模式默认不显示麦克风按钮，除非明确启用并满足安全条件。

### 14.2 输出区

每条 assistant 回复可提供：

```text
[朗读] / [停止朗读]
```

只显示当前有效动作。播报状态不得污染 Conversation 消息内容。

### 14.3 快捷键

P1 可增加独立 Push-to-talk 快捷键。要求：

- 与桌面呼出快捷键分别配置；
- 注册失败时保留 UI 按钮；
- 不使用通用键盘记录 Hook；
- 松开事件丢失时仍由最大时长兜底；
- 应用退出时注销。

---

## 15. 配置

建议新增：

```dotenv
ZHAOXI_VOICE_ENABLED=false
ZHAOXI_VOICE_AUTO_SEND=false
ZHAOXI_VOICE_AUTO_SPEAK=false
ZHAOXI_VOICE_LANGUAGE=zh-CN
ZHAOXI_VOICE_MAX_SECONDS=60
ZHAOXI_VOICE_MAX_BYTES=4194304
ZHAOXI_VOICE_TEMP_DIR=.zhaoxi/tmp/voice
ZHAOXI_VOICE_DEVICE_ID=

ZHAOXI_STT_PROVIDER=disabled
ZHAOXI_STT_BASE_URL=
ZHAOXI_STT_API_KEY=
ZHAOXI_STT_MODEL=
ZHAOXI_STT_TIMEOUT_SECONDS=45
ZHAOXI_STT_MAX_RETRIES=1

ZHAOXI_TTS_PROVIDER=windows
ZHAOXI_TTS_VOICE=
ZHAOXI_TTS_RATE=0
ZHAOXI_TTS_VOLUME=100
ZHAOXI_TTS_MAX_CHARS=1200
```

要求：

- Voice 默认关闭；
- auto-send 和 auto-speak 默认关闭；
- STT Key 与聊天模型 Key 分开配置，允许用户显式选择复用但不默认假设；
- 配置验证失败定位到具体字段；
- Voice 配置错误只禁用 Voice，不应阻止文字 Core 启动；
- Provider disabled 时 UI 显示可操作说明；
- 新增配置同步 `.env.example`、配置测试、README 和 `CODEBASE_STATUS.md`。

---

## 16. 临时文件与数据生命周期

推荐流程：

```text
创建安全临时 WAV
→ Recorder 写入
→ stop 后封口并校验
→ STT 读取
→ transcript 进入 REVIEWING
→ 成功 / 取消 / 失败后删除 WAV
```

要求：

- 默认不长期保存录音；
- 不把录音纳入 Memory；
- 不把录音提交 Git；
- `.gitignore` 覆盖临时音频目录；
- 删除失败时记录文件 ID 和错误类型，不记录 transcript；
- 启动时只清理 Voice 临时目录中超过安全时间窗的孤儿文件；
- 清理范围必须解析并验证在配置的 Voice 临时目录内；
- 不递归删除 `.zhaoxi` 根目录；
- 文件名不得包含用户文本；
- 测试只使用 pytest 临时目录。

---

## 17. 安全与隐私

1. 麦克风只能由用户可见动作启动；
2. RECORDING 状态必须持续可见；
3. 应用隐藏、锁屏或退出时按策略停止录音；
4. 云端 STT 必须在设置中明确说明音频会上传到哪个 Provider；
5. transcript 确认前不进入 Core、Memory、日志或审计正文；
6. Voice metadata 不保存音频路径和设备底层信息；
7. TTS 不读取隐藏字段、密钥、完整路径和原始外部 payload；
8. Voice 入口不能绕过 Permission Gateway；
9. DANGEROUS 操作不得仅凭语音“确认”直接执行；
10. Voice API 继续受 v0.7 Desktop bootstrap Cookie 和 loopback 边界保护；
11. 上传请求日志不记录音频正文、Authorization 或 transcript；
12. 音频哈希仅用于本次生命周期内的去重与诊断，不作为长期用户标识。

---

## 18. 可观测性与错误体验

日志事件至少包含：

```text
voice_record_start
voice_record_stop
voice_record_cancel
voice_transcribe_start
voice_transcribe_finish
voice_transcribe_fail
voice_review_confirm
voice_speak_start
voice_speak_stop
voice_speak_fail
voice_temp_cleanup
```

允许记录：

- operation_id / capture_id；
- Provider 名称；
- 状态、耗时、音频时长和大小；
- 错误类型和可恢复性；
- 是否由用户取消。

禁止记录：

- 音频内容；
- transcript 正文；
- API Key；
- Provider 原始响应；
- 完整设备标识；
- 最终用户消息正文。

错误分层：

- 设备错误：提示选择设备或改用文字；
- 配置错误：提示缺少的 Provider 配置；
- 网络错误：允许有界重试；
- 识别结果为空：回到 REVIEWING / 重录，不当作系统异常；
- TTS 错误：保留文字回复，不把整次 Agent 请求标成失败；
- 清理错误：后台有限重试并记录，不阻塞文字对话。

---

## 19. 开发流程

### 阶段 0：冻结 v0.7 基线

工作：

- 跑 v0.7 全量测试、编译与 diff 检查；
- 实机确认 Desktop、托盘、快捷键、Cookie bootstrap 和文字聊天仍可用；
- 冻结 UnifiedMessage / UnifiedResponse / InterfaceGateway 契约；
- 明确当前 Quiet / Night 状态来源；
- 建立 Voice 不得绕过 Permission 的回归测试入口。

退出条件：v0.7 的 138 项测试基线可重复，Voice 开发不会用“顺便重构桌面”扩大范围。

### 阶段 1：Recorder / STT / TTS Spike 与 ADR

工作：

- 验证 Windows Recorder；
- 验证一个真实中文 STT；
- 验证一个本地可停止 TTS；
- 验证线程、async bridge、取消和退出；
- 固定首版依赖和 Provider 契约；
- 写 ADR。

退出条件：完成“录 5 秒 → 转写 → 播报固定文本 → 中途停止”的独立实验，所有资源可释放。

### 阶段 2：领域模型与 Fake 纵向切片

工作：

- AudioSpec / AudioCapture / Transcript / VoiceStatus；
- VoiceRuntime 状态机；
- Fake Recorder / STT / TTS / Player；
- cancel token、Clock 和临时目录；
- 状态转换与非法调用测试。

退出条件：无真实设备和网络即可覆盖成功、取消、超时、失败和重复调用。

### 阶段 3：Recorder 与临时文件

工作：

- 设备枚举；
- 开始、停止、取消；
- 时长和大小上限；
- WAV 校验；
- 设备断开恢复；
- 孤儿临时文件清理；
- Desktop 生命周期接入。

退出条件：连续录制、取消 20 次无 stream、线程和临时文件泄漏；达到上限能确定性停止。

### 阶段 4：STT 与 Transcript Review

工作：

- 实现 Provider Adapter；
- 分型超时、认证、限流、格式和服务错误；
- Review UI；
- 编辑、重试、重录、取消；
- 添加 `InterfaceChannel.VOICE`；
- 确认后通过 Gateway 发送；
- request ID 防重复。

退出条件：真实中文语音能够转写、编辑并进入同一 Desktop Session；取消前不污染 Conversation。

### 阶段 5：TTS 与 Voice Policy

工作：

- 实现首个本地 TTS；
- SpeechHandle 与 stop；
- Sanitizer；
- Voice Output Policy；
- 回复朗读按钮；
- auto-speak；
- Quiet / Night / 输入中断；
- Desktop 退出清理。

退出条件：短回复可播报并立即停止；Quiet / Night 不自动出声；TTS 失败不影响文字回复。

### 阶段 6：Desktop UI 纵向闭环

工作：

- 完成所有 Voice 状态 UI；
- 防重复点击；
- 页面刷新与 SSE 重连恢复；
- Voice 设置最小入口；
- 可选 P1 Push-to-talk 快捷键；
- 错误提示与文字降级。

退出条件：用户无需终端即可完成“录音 → 转写 → 复核 → 发送 → 回复 → 播报 → 停止”。

### 阶段 7：硬化与交付

工作：

- 全量自动化测试；
- Voice 并发、取消和退出压力；
- 隐私与日志审计；
- 检查临时音频清理；
- 更新版本号、README、`.env.example`、`CODEBASE_STATUS.md`；
- 本体开发完成后进行一次集中黑盒冒烟；
- 检查 Git diff 中无录音、transcript、Key、数据库或日志。

退出条件：P0 全部通过；P1 / P2 未完成项有明确记录；安装发布工程仍留给 v0.9。

---

## 20. 测试矩阵

### Models / State Machine

- AudioSpec 边界；
- 时区、ID 和路径约束；
- 全部合法状态转换；
- 非法 start / stop / confirm / retry 拒绝；
- cancel 幂等；
- 同一时刻单 Recorder / STT / TTS；
- operation_id 防旧结果覆盖新状态。

### Recorder

- start / stop / cancel；
- 最大时长和最大字节；
- 空音频和静音；
- 设备缺失、占用、断开和切换；
- WAV header 与实际帧数；
- callback 异常隔离；
- 连续 20 次不泄漏；
- 临时文件成功、失败、取消和退出清理；
- 孤儿清理不越界。

### STT

- Fake 成功、空文本、低可信、超时和取消；
- 认证、限流、4xx、5xx 和格式错误；
- 音频大小与格式预检；
- 有界重试；
- Provider 原始错误不进 UI；
- 云端上传配置提示；
- transcript 默认不自动发送；
- 编辑后的文本才进入 Gateway。

### Interface / Permission

- VOICE channel 可用；
- 非 user origin 仍被拒绝；
- 同 request ID 不重复执行；
- 当前 Session 串行；
- transcript 确认前 Conversation 不变化；
- WRITE 仍进入 Permission Card；
- DANGEROUS 不因 voice origin 获得放行；
- deny 后不播报成功声明。

### TTS / Policy

- Sanitizer 清理 Markdown、代码、URL 和 JSON；
- 超长文本策略；
- speak / stop / repeated stop；
- 新输入中断；
- Quiet / Night 禁止自动播报；
- auto-speak 默认关闭；
- 用户点击朗读；
- Permission 等待文本不自动播报；
- TTS 失败保留文字成功状态；
- Desktop 退出释放播放器。

### UI / Lifecycle

- 状态文本和按钮；
- 防重复录音；
- Review 编辑、重试、重录和取消；
- 页面刷新 / SSE 重连；
- Desktop 隐藏、显示和退出；
- 快捷键冲突降级；
- Voice disabled 时不加载设备和 Provider；
- 配置错误不阻止文字 Core。

### 回归

- v0.7 的 138 项测试全部通过；
- Web 独立模式正常；
- CLI 正常；
- Desktop 单实例、托盘、快捷键和通知正常；
- API bootstrap Cookie 边界不变；
- Proactive Quiet / Night 行为不回归；
- 不使用真实 API Key 运行自动化测试。

测试分层：

```text
纯单元测试：模型、状态机、策略、Sanitizer、配置
Provider 合约测试：Fake Recorder / STT / TTS / Player
HTTP Mock 测试：真实 STT Adapter 请求与错误映射
进程集成测试：Desktop 生命周期、取消、资源释放
Windows 集中冒烟：麦克风、中文 STT、TTS、停止和权限
```

自动化测试不得依赖真实 sleep；Clock、Recorder、Provider、Player 和临时目录均需可注入。

---

## 21. 集中黑盒冒烟验收

人工验收只在朝汐本体开发和自动化测试完成后集中执行，不在每个阶段重复跑全套。保留四条主链路。

### Case A：语音输入闭环

从 Desktop 点击按键说话，说一句中文。确认录音状态可见，停止后得到可编辑 transcript；修改一个词并发送，聊天区只出现修改后的文本，Core 正常回复。

### Case B：取消、故障与文字降级

分别在 RECORDING、TRANSCRIBING 和 SPEAKING 中取消一次；再模拟麦克风不可用和 STT 离线。所有状态回到可用，临时文件被清理，文字输入仍能继续聊天。

### Case C：TTS、Quiet 与 Night

主动点击朗读一条短回复并中途停止。开启 auto-speak 后验证 Voice 请求的短回复可播报；打开 Quiet 或模拟 Night 后不再自动出声，文字回复仍显示。

### Case D：Permission 与退出

用语音提出 WRITE 请求，确认仍显示 Permission Card，拒绝后不执行也不播报成功。分别在录音和播报中退出 Desktop，确认进程有界结束，无残留音频、设备占用、线程或锁。

---

## 22. 交付物

- `src/zhaoxi/voice/` 领域模型、Runtime、Recorder、STT、TTS、Policy 和 Sanitizer；
- `tests/voice/` 完整 Fake 与合约测试；
- Desktop Voice UI 与 Gateway 接入；
- Recorder / STT / TTS 技术选型 ADR；
- Voice 配置与隐私说明；
- 更新后的 README、`.env.example`、版本号和 `CODEBASE_STATUS.md`；
- 本体开发完成后的集中黑盒冒烟结果；
- Git 中不包含真实录音、transcript、API Key、数据库、日志或用户数据。

---

## 23. Definition of Done

v0.7.1 完成必须满足：

1. P0 全部完成并有自动化证据；
2. Windows 实机可以完成 Push-to-talk、中文 STT、transcript 复核和发送；
3. Voice 消息通过 Interface Gateway 进入同一 Core 和 Session；
4. 至少一个可用 TTS 能播报最终回复并立即停止；
5. Quiet / Night、用户静音、录音中和 Permission 等待场景按确定性策略处理；
6. Voice 不绕过 Permission，DANGEROUS 不接受仅凭语音的隐式批准；
7. Recorder、STT、TTS、Player 和临时文件在成功、失败、取消和退出后可释放；
8. Voice disabled 或 Provider 配置错误时，文字 Core 仍可正常启动和使用；
9. 全量自动化测试通过，测试数与验证命令写入 `CODEBASE_STATUS.md`；
10. 集中黑盒冒烟四条主链路通过；
11. 版本号、README、`.env.example`、任务书和交接文档一致；
12. 唤醒词、持续监听和发布工程没有混入本版。

---

## 24. 推荐提交切片

```text
1. docs: freeze v0.7.1 voice contracts and provider ADR
2. feat: add voice models runtime and fake providers
3. feat: add bounded Windows audio recorder
4. feat: add STT provider and transcript review
5. feat: route confirmed voice input through interface gateway
6. feat: add stoppable TTS and speech sanitizer
7. feat: integrate voice policy and desktop controls
8. test: harden cancellation cleanup privacy and regressions
9. docs: finalize v0.7.1 delivery and codebase status
```

每个切片必须保持文字入口可用。涉及设备、线程或临时文件的切片必须同时提交取消、关闭和测试路径。

---

## 25. 一句话验收

> **当用户可以明确按下按钮说话，在看见并确认转写后把它交给同一个朝汐 Core；当朝汐回复时可以选择朗读并随时停止；当设备、网络、Quiet、Night、Permission 或退出介入时，语音能力仍然可控、不越权、不残留且始终能退回文字，v0.7.1 才算完成。**
