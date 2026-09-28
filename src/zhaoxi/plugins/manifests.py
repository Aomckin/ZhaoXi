"""Validated plugin manifests."""
from pathlib import Path
import tomllib
from pydantic import BaseModel, Field
from zhaoxi.sdk.external_source import SourceCapabilities

class PluginManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    version: str
    entrypoint: str
    capabilities: SourceCapabilities = Field(default_factory=SourceCapabilities)
    directory: Path | None = Field(default=None, exclude=True)

    @classmethod
    def read(cls, path: str | Path) -> "PluginManifest":
        with Path(path).open("rb") as stream:
            return cls.model_validate({**tomllib.load(stream), "directory": Path(path).parent})
