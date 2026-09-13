# JobApplication Tool Package

Safe browser-local assistance for job application forms. The Browser Profile is
the only profile data source. Zhaoxi receives six high-level Tools; no Tool can
submit an application, confirm a declaration, upload a file, execute arbitrary
JavaScript, or bypass the browser-side safety policy.

The companion extension connects to `native_host.host` using Chrome Native
Messaging. The native host relays bounded requests over a same-user local IPC
endpoint; it is not an HTTP service.

See `README_ZHAOXI_BROWSER.md` for explicit setup. The installer is never run
automatically. AI mapping is a reserved orchestrator extension point in v0.1;
the shipped path reports `local_only_v0.1` and never sends Profile values away.

朝汐默认不自动启用落盘即发现的外部 Tool Package。完成浏览器侧安装后，在仓库
根目录的 `.env` 中显式加入 `ZHAOXI_TOOL_JOB_APPLICATION_ENABLED=true`，再重启
朝汐。此开关只启用 Tool 注册，不会授予网页权限；每个页面仍必须由用户在扩展
Popup 中点击“启用并扫描”。

## v0.1 adapters

- Page: Generic, Moka, Beisen, Feishu
- Control: Native HTML, Ant Design, Element UI/Plus

## Development

```powershell
pytest -q tools/job_application_tool/tests
```
