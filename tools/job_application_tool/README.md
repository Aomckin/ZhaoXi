# JobApplication Tool Package

Safe browser-local assistance for job application forms. The Browser Profile is
the only profile data source. Zhaoxi receives six high-level Tools; no Tool can
submit an application, confirm a declaration, upload a file, execute arbitrary
JavaScript, or bypass the browser-side safety policy.

The companion extension connects to `native_host.py` using Chrome Native
Messaging. The native host relays bounded requests over a same-user local IPC
endpoint; it is not an HTTP service.

See `browser_extension/README.md` for explicit setup. The installer is never run
automatically. AI mapping is a reserved orchestrator extension point in v0.1;
the shipped path reports `local_only_v0.1` and never sends Profile values away.

## v0.1 adapters

- Page: Generic, Moka, Beisen, Feishu
- Control: Native HTML, Ant Design, Element UI/Plus

## Development

```powershell
pytest -q tools/job_application_tool/tests
```
