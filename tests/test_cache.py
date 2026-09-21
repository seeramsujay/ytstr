"""
Unit tests for CacheManager bounded caching, sliding window pruning, and --save export.
"""
import tempfile
from pathlib import Path
from ytstr.core.types import Track
from ytstr.downloader.cache import (
    CacheManager,
    MAX_CACHE_TRACK_SIZE_BYTES,
    sanitize_filename,
)


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


def test_cache_manager_window_retention_and_30mb_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = CacheManager(session_id="window_test")
        mgr.raw_dir = Path(tmpdir) / "raw"
        mgr.raw_dir.mkdir(parents=True)

        tracks = [
            Track(id=f"track_{i}", title=f"Track {i}", artist="Artist")
            for i in range(6)
        ]

        # Populate cache files for tracks 0..5
        for i, t in enumerate(tracks):
            path = mgr.get_track_cache_path(t, "opus")
            path.write_bytes(b"A" * 2048)

        # Active is track 2.
        # Window: active=2, next1=3, next2=4, prev=1 (2048 bytes <= 30MB -> kept).
        # Out of window: 0 (< 1), 5 (> 4) -> pruned.
        mgr.prune_window(2, tracks)

        assert not mgr.track_is_cached(tracks[0])
        assert mgr.track_is_cached(tracks[1])
        assert mgr.track_is_cached(tracks[2])
        assert mgr.track_is_cached(tracks[3])
        assert mgr.track_is_cached(tracks[4])
        assert not mgr.track_is_cached(tracks[5])

        # Test 30 MB limit on previous track:
        # If track 1 is larger than 30 MB, it should be evicted
        oversized_bytes = (30 * 1024 * 1024) + 1024
        p1 = mgr.get_track_cache_path(tracks[1], "opus")
        p1.write_bytes(b"B" * 1024)
        # Truncate / simulate size without allocating 30MB memory
        with open(p1, "wb") as f:
            f.seek(oversized_bytes - 1)
            f.write(b"\0")

        assert p1.stat().st_size > MAX_CACHE_TRACK_SIZE_BYTES

        mgr.prune_window(2, tracks)
        assert not mgr.track_is_cached(tracks[1]), "Previous track > 30MB must be pruned"
        assert mgr.track_is_cached(tracks[2]), "Active track must be kept"
        assert mgr.track_is_cached(tracks[3]), "Next track 1 must be kept"
        assert mgr.track_is_cached(tracks[4]), "Next track 2 must be kept"


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
