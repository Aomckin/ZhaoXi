"""Discover optional sources without importing them during core startup."""
from importlib import import_module, metadata, util
from pathlib import Path
from zhaoxi.plugins.manifests import PluginManifest

def discover(directory: str | Path, errors: list | None = None) -> dict[str, PluginManifest]:
    result = {}
    for path in sorted(Path(directory).glob("*/manifest.toml")):
        try:
            manifest = PluginManifest.read(path)
        except Exception as exc:
            if errors is None:
                raise
            errors.append((path.parent.name, type(exc).__name__))
            continue
        if manifest.id in result:
            raise ValueError(f"duplicate plugin id: {manifest.id}")
        result[manifest.id] = manifest
    for point in metadata.entry_points(group="zhaoxi.external_sources"):
        result.setdefault(point.name, PluginManifest(
            id=point.name, name=point.name, version="installed", entrypoint=point.value))
    return result

def load(manifest: PluginManifest, **kwargs):
    module_name, separator, class_name = manifest.entrypoint.partition(":")
    if not separator or not module_name or not class_name:
        raise ValueError(f"invalid entrypoint for {manifest.id}")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError:
        candidate = (manifest.directory / (module_name.replace(".", "/") + ".py")
                     if manifest.directory else None)
        if candidate is None or not candidate.is_file():
            raise
        spec = util.spec_from_file_location(f"zhaoxi_external_{manifest.id}", candidate)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
    instance = getattr(module, class_name)(**kwargs)
    if instance.plugin_id != manifest.id:
        raise ValueError(f"plugin id mismatch: {manifest.id}")
    return instance
