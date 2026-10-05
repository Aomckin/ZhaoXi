"""External source assembly and Web-owned background-task lifecycle."""
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import UTC, datetime
from fastapi import FastAPI
from zhaoxi.interfaces.setup import StartupUnavailableAgent
from zhaoxi.reliability import TaskSupervisor
logger = logging.getLogger("WEB")


def build_external_runtime(configured, core):
    perception = None
    source_runtime = None
    if configured.perception_enabled and not isinstance(core, StartupUnavailableAgent):
        try:
            from zhaoxi.perception import PerceptionRuntime
            from zhaoxi.plugins.runtime import PluginRuntime
            from zhaoxi.plugins.source_router import PerceptionSink
            from zhaoxi.plugins.loader import discover
            import tomllib
            perception = PerceptionRuntime(configured, core)
            core.perception = perception
            source_runtime = PluginRuntime(None)
            source_runtime.sink = PerceptionSink(perception, source_runtime)
            perception.sources = source_runtime
            plugin_dir = Path(__file__).resolve().parents[2] / "zhaoxi_ext"
            discovery_errors = []
            manifests = discover(plugin_dir, discovery_errors)
            for plugin_id, manifest in discover(Path("plugins/external_sources"), discovery_errors).items():
                if plugin_id in manifests:
                    discovery_errors.append((plugin_id, "DuplicatePluginId"))
                else:
                    manifests[plugin_id] = manifest
            for bad_id, error in discovery_errors:
                from zhaoxi.plugins.manifests import PluginManifest
                safe_id = "invalid_" + re.sub(r"[^a-z0-9_]", "_", bad_id.lower())
                broken = PluginManifest(id=safe_id, name=bad_id, version="invalid",
                                        entrypoint="invalid:Invalid")
                if safe_id in source_runtime._state:
                    continue
                source_runtime.register(broken)
                source_runtime._state[safe_id]["status"] = "degraded"
                source_runtime._state[safe_id]["last_error"] = error
                logger.warning("external source manifest failed id=%s error=%s", bad_id, error)
            for manifest in manifests.values():
                config_path = Path("config/plugins") / (manifest.id + ".toml")
                try:
                    if config_path.is_file():
                        with config_path.open("rb") as stream:
                            enabled = bool(tomllib.load(stream).get("enabled", False))
                    else:
                        enabled = False
                    source_runtime.register(manifest, enabled=enabled)
                except Exception as exc:
                    source_runtime.register(manifest)
                    state = source_runtime._state[manifest.id]
                    state["status"] = "degraded"
                    state["last_error"] = type(exc).__name__
        except Exception as exc:
            logger.warning("perception startup degraded type=%s", type(exc).__name__)
    return perception, source_runtime


def web_lifespan(core, configured, adapter, events, voice_runtime, perception, source_runtime):
    supervisor = TaskSupervisor()

    async def proactive_loop() -> None:
        while True:
            await asyncio.sleep(1)
            scheduler = getattr(core, "proactive_scheduler", None)
            runtime = getattr(core, "proactive", None)
            state = getattr(core, "proactive_state", None)
            if scheduler is None or runtime is None or state is None:
                continue
            try:
                emitted = await scheduler.tick()
                for event in emitted:
                    deliveries = await runtime.process(event, datetime.now(UTC), state)
                    for delivery in deliveries:
                        await events.publish({
                            "type": "proactive",
                            "delivery": delivery.model_dump(mode="json"),
                        })
            except Exception as exc:
                logger.warning("proactive web loop failed type=%s", type(exc).__name__)


    async def internal_activity_loop() -> None:
        while True:
            activity = getattr(core, "internal_activity", None)
            if activity is not None:
                try:
                    if activity.control.presence()["heartbeat_enabled"]:
                        await activity.run_tick()
                except Exception as exc:
                    logger.warning("internal activity loop failed type=%s", type(exc).__name__)
            if activity is not None:
                await activity.control.wait_interval()
            else:
                await asyncio.sleep(configured.proactive_heartbeat_seconds)


    @asynccontextmanager
    async def lifespan(_: FastAPI):
        supervisor.start()
        adapter.gateway.maintenance_queue().start()
        if getattr(core, "internal_activity", None):
            core.internal_activity.publish_status = events.publish_nowait
        heartbeat = getattr(core, "proactive_heartbeat", None)
        worker = getattr(core, "proactive_worker", None)
        if heartbeat is not None and worker is not None:
            if getattr(heartbeat.presence, "run", None):
                supervisor.create(heartbeat.presence.run(), name="zhaoxi-desktop-activity")
            supervisor.create(heartbeat.run(), name="zhaoxi-tidal-heartbeat")
            supervisor.create(worker.run(events.publish), name="zhaoxi-tidal-decisions")
        else:
            supervisor.create(proactive_loop(), name="zhaoxi-proactive-web")
            supervisor.create(internal_activity_loop(), name="zhaoxi-internal-activity")
        if perception is not None:
            supervisor.create(perception.run(), name="zhaoxi-perception")
        if source_runtime is not None:
            for source in source_runtime.diagnostics():
                if source["enabled"]:
                    await source_runtime.enable(source["plugin_id"])
        try:
            yield
        finally:
            if source_runtime is not None:
                await source_runtime.stop()
            if perception is not None:
                try:
                    await asyncio.wait_for(perception.flush(force=True), timeout=5)
                except Exception as exc:
                    logger.warning("perception shutdown flush deferred type=%s", type(exc).__name__)
            if voice_runtime is not None:
                await voice_runtime.cancel("application_shutdown")
            await adapter.gateway.maintenance_queue().shutdown(configured.shutdown_grace_seconds)
            result = await supervisor.shutdown(
                configured.shutdown_grace_seconds, cancel_immediately=True
            )
            registry = getattr(core, "registry", None)
            provider_errors = registry.close_providers() if registry is not None else []
            if provider_errors:
                logger.warning("ToolProvider shutdown failures=%s", provider_errors)
            logger.info(
                "runtime shutdown completed=%s cancelled=%s",
                result["completed"],
                result["cancelled"],
            )


    return supervisor, lifespan
