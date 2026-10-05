"""Assembly must share isolated state paths with backup and model preferences."""
from pathlib import Path
import sqlite3

import pytest

from zhaoxi.bootstrap.runtime import build_agent
from zhaoxi.bootstrap.storage import build_data_store_specs
from zhaoxi.config.settings import Settings


def test_assembled_stores_and_backup_share_the_isolated_paths(isolated_runtime):
    settings = Settings(model_api_key="test-key", model_name="test-model", archive_enabled=False)
    agent = build_agent(settings)
    specs = {item.name: item for item in build_data_store_specs(settings, archive_enabled=False)}
    assert all(item.path.resolve().is_relative_to(isolated_runtime) for item in specs.values())
    assert agent.experience_stream.path == specs["experience"].path == Path(settings.experience_db_path)
    assert Path(agent.provider.providers[0].thinking_settings_path) == Path(settings.model_settings_path)
    assert agent.current_cognition is agent.runtime.current_cognition is agent.context_builder.current_cognition_service
    agent.runtime.agenda = None
    assert agent.agenda is None
    agent.agenda = "replacement"
    assert agent.runtime.agenda == "replacement"
    assert "agenda" not in agent.__dict__


@pytest.mark.parametrize("uri", [False, True])
def test_production_sqlite_access_is_rejected_before_open(uri):
    path = Path(__file__).parents[2] / ".zhaoxi/test-isolation-canary.db"
    database = path.resolve().as_uri() + "?mode=rwc" if uri else path
    with pytest.raises(AssertionError, match="production SQLite"):
        sqlite3.connect(database, uri=uri)


def test_production_file_write_is_rejected_before_open():
    path = Path(__file__).parents[2] / "data/test-isolation-canary.json"
    with pytest.raises(AssertionError, match="production state"):
        path.write_text("must not be written", encoding="utf-8")
