import os

import pytest

from zhaoxi.voice.temp_store import VoiceTempStore


def test_temp_store_only_removes_scoped_capture_files(tmp_path):
    store = VoiceTempStore(tmp_path / "voice")
    capture = store.create_wav_path()
    capture.write_bytes(b"wav")
    store.remove(capture)
    assert not capture.exists()

    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"keep")
    with pytest.raises(ValueError, match="之外"):
        store.remove(outside)
    assert outside.exists()


def test_orphan_cleanup_is_pattern_and_age_bounded(tmp_path):
    store = VoiceTempStore(tmp_path / "voice")
    old_capture = store.create_wav_path()
    old_capture.write_bytes(b"old")
    os.utime(old_capture, (10, 10))
    unrelated = store.root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    assert store.cleanup_orphans(older_than_seconds=100, now=1000) == 1
    assert not old_capture.exists()
    assert unrelated.exists()

