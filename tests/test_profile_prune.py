"""Tests for prune_profile_caches."""

from pathlib import Path

from linkedin_mcp_server.core.browser import prune_profile_caches

CACHE_DIRS = [
    "Cache",
    "Code Cache",
    "GPUCache",
    "GraphiteDawnCache",
    "DawnWebGPUCache",
    "DawnGraphiteCache",
    "component_crx_cache",
    "ShaderCache",
    "GrShaderCache",
]
STATE = ["Cookies", "Login Data", "Preferences"]
STATE_DIRS = ["Local Storage", "IndexedDB", "Session Storage"]


def _build(profile: Path) -> None:
    default = profile / "Default"
    for base in (profile, default):
        for name in CACHE_DIRS:
            d = base / name
            d.mkdir(parents=True)
            (d / "blob").write_bytes(b"x" * 100)
    for name in STATE:
        (default / name).write_bytes(b"state")
    for name in STATE_DIRS:
        d = default / name
        d.mkdir(exist_ok=True)
        (d / "leveldb").write_bytes(b"state")


def test_prunes_caches_and_keeps_state(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    _build(profile)
    freed = prune_profile_caches(profile)
    assert freed >= 100 * len(CACHE_DIRS) * 2
    for base in (profile, profile / "Default"):
        for name in CACHE_DIRS:
            assert not (base / name).exists()
    for name in STATE:
        assert (profile / "Default" / name).read_bytes() == b"state"
    for name in STATE_DIRS:
        assert (profile / "Default" / name / "leveldb").exists()


def test_missing_dir_is_noop(tmp_path: Path) -> None:
    assert prune_profile_caches(tmp_path / "nope") == 0


def test_empty_profile_frees_nothing(tmp_path: Path) -> None:
    assert prune_profile_caches(tmp_path) == 0
