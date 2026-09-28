"""Runtime ownership and diagnostics for independent source plugins."""
import asyncio
from datetime import UTC, datetime
from zhaoxi.plugins.loader import load
from zhaoxi.sdk.external_source import SendResult

class PluginRegistry:
    def __init__(self, sink):
        self.sink = sink
        self._plugins = {}
        self._tasks = {}
        self._state = {}

    def register(self, manifest, *, plugin=None, kwargs=None, enabled=False):
        if manifest.id in self._state:
            raise ValueError(f"duplicate plugin id: {manifest.id}")
        self._state[manifest.id] = {"manifest": manifest, "enabled": enabled,
                                    "status": "disabled", "last_error": None,
                                    "last_event": None, "last_send": None, "kwargs": kwargs or {}}
        if plugin is not None:
            self._plugins[manifest.id] = plugin

    async def enable(self, plugin_id):
        state = self._state[plugin_id]
        if plugin_id in self._tasks and not self._tasks[plugin_id].done():
            return
        state["enabled"] = True
        try:
            plugin = self._plugins.get(plugin_id)
            if plugin is None:
                plugin = load(state["manifest"], **state["kwargs"])
                self._plugins[plugin_id] = plugin
            task = asyncio.create_task(plugin.start(_SourceSink(self, plugin_id)), name=f"source-{plugin_id}")
            self._tasks[plugin_id] = task
            state["status"] = "running"
            task.add_done_callback(lambda done, ident=plugin_id: self._finished(ident, done))
            await asyncio.sleep(0)
        except Exception as exc:
            state["status"] = "degraded"
            state["last_error"] = type(exc).__name__

    def _finished(self, plugin_id, task):
        state = self._state[plugin_id]
        if not state["enabled"]:
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            error = None
        state["status"] = "degraded"
        state["last_error"] = type(error).__name__ if error else "UnexpectedStop"

    async def disable(self, plugin_id):
        state = self._state[plugin_id]
        state["enabled"] = False
        plugin = self._plugins.get(plugin_id)
        if plugin is not None:
            try:
                await plugin.stop()
            except Exception as exc:
                state["last_error"] = type(exc).__name__
        task = self._tasks.pop(plugin_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        state["status"] = "disabled"

    async def restart(self, plugin_id):
        await self.disable(plugin_id)
        await self.enable(plugin_id)

    async def stop(self):
        for plugin_id in list(self._state):
            await self.disable(plugin_id)

    async def send(self, target, content):
        state = self._state.get(target.source_plugin)
        task = self._tasks.get(target.source_plugin)
        if not state or not state["enabled"] or task is None or task.done():
            return SendResult(sent=False, error="source unavailable")
        try:
            result = await self._plugins[target.source_plugin].send(target, content)
            state["last_send"] = datetime.now(UTC).isoformat()
            if not result.sent:
                state["status"] = "degraded"
                state["last_error"] = result.error or "SendFailed"
            else:
                state["status"] = "running"
                state["last_error"] = None
            return result
        except Exception as exc:
            state["last_error"] = type(exc).__name__
            state["status"] = "degraded"
            return SendResult(sent=False, error=type(exc).__name__)

    def diagnostics(self):
        result = []
        for plugin_id, state in self._state.items():
            manifest = state["manifest"]
            item = {"plugin_id": plugin_id, "name": manifest.name,
                    "version": manifest.version, "enabled": state["enabled"],
                    "status": state["status"], "last_error": state["last_error"],
                    "last_event": state["last_event"], "last_send": state["last_send"],
                    "capabilities": manifest.capabilities.model_dump()}
            plugin = self._plugins.get(plugin_id)
            if plugin:
                try:
                    item["plugin"] = plugin.diagnostics()
                    if item["status"] == "running" and item["plugin"].get("last_error") and not item["plugin"].get("connected", True):
                        item["status"] = "degraded"
                        item["last_error"] = item["plugin"]["last_error"]
                except Exception as exc:
                    item["last_error"] = type(exc).__name__
            result.append(item)
        return result

class _SourceSink:
    def __init__(self, registry, plugin_id):
        self.registry, self.plugin_id = registry, plugin_id

    async def emit(self, observation):
        state = self.registry._state[self.plugin_id]
        if not state["enabled"]:
            return
        if observation.source_plugin != self.plugin_id:
            observation = observation.model_copy(update={"source_plugin": self.plugin_id})
        state["last_event"] = datetime.now(UTC).isoformat()
        await self.registry.sink.emit(observation)
