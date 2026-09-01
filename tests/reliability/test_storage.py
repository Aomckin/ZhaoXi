import json
import sqlite3

import pytest

from zhaoxi.reliability.storage import BackupError, BackupManager, DataStoreSpec


def make_db(path, value):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE data(value TEXT)")
        connection.execute("INSERT INTO data VALUES (?)", (value,))


def read_db(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM data").fetchone()[0]


def test_verified_backup_and_restore_with_safeguard(tmp_path):
    source = tmp_path / "state.db"
    make_db(source, "before")
    manager = BackupManager(
        tmp_path / "backups",
        [DataStoreSpec("state", source)],
        retention_count=3,
    )
    backup = manager.create()
    assert manager.verify(backup)["files"][0]["name"] == "state"

    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE data SET value='after'")
    safeguard = manager.restore(backup)

    assert read_db(source) == "before"
    assert manager.verify(safeguard)["backup_id"] == safeguard.name


def test_tampered_backup_is_rejected_before_restore(tmp_path):
    source = tmp_path / "state.db"
    make_db(source, "safe")
    manager = BackupManager(tmp_path / "backups", [DataStoreSpec("state", source)])
    backup = manager.create()
    (backup / "state.db").write_bytes(b"corrupt")

    with pytest.raises(BackupError, match="大小|校验"):
        manager.restore(backup)
    assert read_db(source) == "safe"


def test_backup_path_escape_and_unknown_manifest_item_are_rejected(tmp_path):
    source = tmp_path / "state.db"
    make_db(source, "safe")
    manager = BackupManager(tmp_path / "backups", [DataStoreSpec("state", source)])
    with pytest.raises(BackupError, match="备份目录"):
        manager.verify(tmp_path)

    backup = manager.create()
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["name"] = "unknown"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="未知"):
        manager.verify(backup)


def test_health_marks_corrupt_database_unhealthy(tmp_path):
    path = tmp_path / "broken.db"
    path.write_bytes(b"not sqlite")
    manager = BackupManager(tmp_path / "backups", [DataStoreSpec("broken", path)])
    assert manager.health()["broken"]["healthy"] is False
