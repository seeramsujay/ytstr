"""
Unit tests for CacheManager bounded caching, sliding window pruning, and --save export.
"""
import tempfile
from pathlib import Path
from ytstr.core.types import Track
from ytstr.downloader.cache import CacheManager, sanitize_filename


def test_sanitize_filename():
    assert sanitize_filename("Artist / Title ? * : < > |") == "Artist Title"
    assert sanitize_filename("   A   B   ") == "A B"
    assert sanitize_filename("") == "untitled"


def test_cache_manager_sliding_window():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = CacheManager(session_id="test_session")
        mgr.raw_dir = Path(tmpdir) / "raw"
        mgr.raw_dir.mkdir(parents=True)

        # Create mock cached files for tracks 0, 1, 2, 3
        for i in range(4):
            f = mgr.raw_dir / f"{i}.opus"
            f.write_text(f"dummy audio data {i}" * 100)

        # Active is track 3. Tracks < 3 - 1 = 2 (i.e. 0 and 1) should be pruned
        mgr.prune_earlier_than(3)

        assert not (mgr.raw_dir / "0.opus").exists()
        assert not (mgr.raw_dir / "1.opus").exists()
        assert (mgr.raw_dir / "2.opus").exists()
        assert (mgr.raw_dir / "3.opus").exists()


def test_cache_manager_save_file_by_file():
    with tempfile.TemporaryDirectory() as tmp_cache, tempfile.TemporaryDirectory() as tmp_save:
        mgr = CacheManager(session_id="save_session", save_dir=tmp_save)
        mgr.raw_dir = Path(tmp_cache) / "raw"
        mgr.raw_dir.mkdir(parents=True)

        track_file = mgr.raw_dir / "0.opus"
        track_file.write_text("audio contents" * 100)

        track = Track(id="xyz123", title="My Song", artist="Great Artist")

        mgr.on_track_finished(0, track)

        exported = Path(tmp_save) / "Great Artist - My Song.opus"
        assert exported.exists()
        assert "audio contents" in exported.read_text()


def test_cache_manager_cleanup():
    mgr = CacheManager(session_id="cleanup_session")
    assert mgr.session_dir.exists()
    mgr.cleanup()
    assert not mgr.session_dir.exists()
