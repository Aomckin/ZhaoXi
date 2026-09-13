# 朝汐 Browser Companion v0.1

本插件只服务朝汐 `JobApplication Tool Package`。它复用用户当前正常
Chrome/Edge 会话，在当前活动标签页扫描和填写安全字段；不会读取 Cookie、
导出登录态、上传文件、确认声明或提交申请。

## 1. 构建与测试

```powershell
cd tools\job_application_tool\browser_extension
npm install
npm run check
npm test
npm run build
```

构建结果位于：

```text
tools/job_application_tool/browser_extension/dist
```

## 2. 加载扩展

Chrome：

1. 打开 `chrome://extensions`。
2. 开启“开发者模式”。
3. 选择“加载已解压的扩展程序”。
4. 选择上面的 `dist` 目录。
5. 复制扩展卡片显示的 32 位 Extension ID。

Edge 使用 `edge://extensions`，其余步骤相同。

## 3. 安装 Native Messaging Host

在朝汐仓库根目录运行。安装器会检测浏览器、生成绝对路径 manifest，并只写
当前用户的 Chrome/Edge Native Messaging 注册项；无需手工编辑注册表。

```powershell
.\.venv\Scripts\python.exe -m tools.job_application_tool.native_host.install_host `
  --extension-id <EXTENSION_ID> `
  --browser chrome
```

Edge：

```powershell
.\.venv\Scripts\python.exe -m tools.job_application_tool.native_host.install_host `
  --extension-id <EXTENSION_ID> `
  --browser edge
```

同时注册已检测到的 Chrome 和 Edge：

```powershell
.\.venv\Scripts\python.exe -m tools.job_application_tool.native_host.install_host `
  --extension-id <EXTENSION_ID> `
  --browser both
```

扩展重新构建后 ID 通常不变；若 ID 改变，必须重新运行安装器。

## 4. 启动与连接检查

1. 在朝汐仓库根目录的 `.env` 中显式加入
   `ZHAOXI_TOOL_JOB_APPLICATION_ENABLED=true`，然后重启朝汐。
2. 完全退出并重新打开目标浏览器。
3. 打开并登录目标网申页面。
4. 点击扩展图标。
5. 点击“启用并扫描”。这是 `activeTab` 临时授权的唯一入口。
6. Popup 应显示 Native Host 状态、当前 session、PageAdapter、ControlAdapter 和字段数。
7. 在朝汐中调用 `job_application_inspect_page`。

扩展不会扫描后台标签页，也不接受 Agent 指定任意 tab。导航、reload、切换活动
tab、Profile revision 改变或计划过期都会使旧计划失效。

## 5. 推荐验收顺序

```text
job_application_inspect_page
→ 检查 title/origin/path/adapter/字段列表
→ job_application_build_plan
→ 检查各 decision 计数，确认页面尚未变化
→ job_application_apply_safe_fields
→ job_application_get_review
→ 用户检查并手动提交
```

真实字节页面验收必须使用用户当前已登录并显式启用的标签页。不得改用 Fetch、
Playwright 或重新登录来替代这项验收。

## 6. 常见错误

- `browser_bridge_unavailable`：浏览器或 Native Host 未运行；重启浏览器。
- `extension_not_connected`：检查扩展 ID 是否与 Native Host manifest 一致。
- `permission_denied`：在当前页面重新点击扩展图标和“启用并扫描”。
- `content_script_unavailable`：页面不是 HTTP(S) 页面，或 `activeTab` 授权已失效。
- `inspection_expired`：重新执行扫描。
- `page_changed`：页面、活动 tab 或 session 已变化，重新扫描并生成计划。
- `profile_revision_changed`：Profile 已更新，重新生成计划。
- `plan_expired` / `plan_not_ready`：计划过期或已消费，不可重放。
- `write_verification_failed`：控件显示状态或真实 selected/value 状态未通过验证，手动处理。

## 7. 卸载 Native Host

```powershell
.\.venv\Scripts\python.exe -m tools.job_application_tool.native_host.uninstall_host --browser both
```

该命令只删除本 Tool 创建的当前用户 Chrome/Edge 注册项和生成的 host manifest/
launcher，不删除 Browser Profile。扩展可在浏览器扩展页单独移除。

## 安全边界

不存在以下能力或隐藏参数：

```text
submit / apply-now / next-and-submit
confirm-declaration
file-upload
click(selector) / XPath / eval(JavaScript)
force / overwrite_existing / ignore_policy / fill_sensitive
Cookie/token/session 导出
```

填写完成后的唯一终态是：用户检查并手动提交。
