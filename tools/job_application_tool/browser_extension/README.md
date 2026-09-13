# Browser Companion setup

1. Run `npm install && npm run build` and load the generated `dist` directory as
   an unpacked extension from `chrome://extensions` or `edge://extensions`.
2. Copy the generated extension id.
3. From the Zhaoxi workspace, explicitly install the current-user Native
   Messaging manifest:

   ```powershell
   .\.venv\Scripts\python.exe -m tools.job_application_tool.native_host.install_host --extension-id <extension-id> --browser chrome
   ```

4. Restart the browser. On the target recruitment tab, open the extension popup
   and click `启用并扫描` to grant temporary `activeTab` access. Tool calls never
   broaden site access by themselves.

Full Chinese instructions and troubleshooting are in `../README_ZHAOXI_BROWSER.md`.

The extension keeps the Browser Profile as the sole profile source. It does not
offer submission, declaration confirmation, file upload, arbitrary selector,
or arbitrary JavaScript commands.
