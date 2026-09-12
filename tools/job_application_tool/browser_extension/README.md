# Browser Companion setup

1. Open `chrome://extensions`, enable Developer mode, and load this directory as
   an unpacked extension.
2. Copy the generated extension id.
3. From the Zhaoxi workspace, explicitly install the current-user Native
   Messaging manifest:

   ```powershell
   .\.venv\Scripts\python.exe -m tools.job_application_tool.install_native_host --extension-id <extension-id>
   ```

4. Reload the extension. On each recruitment origin, click the extension icon
   once to grant optional access for that origin. Tool calls never request site
   access by themselves.

The extension keeps the Browser Profile as the sole profile source. It does not
offer submission, declaration confirmation, file upload, arbitrary selector,
or arbitrary JavaScript commands.
