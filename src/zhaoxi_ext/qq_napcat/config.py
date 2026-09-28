"""QQ/NapCat plugin configuration, independent of core Settings."""
from pathlib import Path
import os
import tomllib
from dotenv import dotenv_values
from pydantic import BaseModel, Field

class QQConfig(BaseModel):
    enabled: bool = False
    ws_url: str = "ws://127.0.0.1:3001"
    access_token: str = ""
    owner_user_id: str = ""
    bot_user_id: str = ""
    external_bot_user_ids: str = ""
    reconnect_seconds: float = Field(default=5, ge=0.1)
    private_reply_max_segments: int = Field(default=4, ge=1, le=10)
    group_reply_max_segments: int = Field(default=3, ge=1, le=10)
    reply_segment_delay_min_ms: int = Field(default=300, ge=0)
    reply_segment_delay_max_ms: int = Field(default=800, ge=0)
    interface_settings_path: str = ".zhaoxi/interface-settings.json"

    @classmethod
    def load(cls, path: str | Path = "config/plugins/qq_napcat.toml"):
        data = {}
        file = Path(path)
        if file.is_file():
            with file.open("rb") as stream:
                data.update(tomllib.load(stream))
        # Environment settings remain a one-release migration path.
        legacy = {**dotenv_values(".env"), **os.environ}
        if "interface_settings_path" not in data and legacy.get("ZHAOXI_INTERFACE_SETTINGS_PATH"):
            data["interface_settings_path"] = legacy["ZHAOXI_INTERFACE_SETTINGS_PATH"]
        for name in cls.model_fields:
            old_name = "ZHAOXI_QQ_" + name.upper()
            if name not in data and old_name in legacy:
                data[name] = legacy[old_name]
        return cls.model_validate(data)
