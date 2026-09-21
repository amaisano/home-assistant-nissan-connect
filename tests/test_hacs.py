"""Tests for HACS installation metadata."""

import json
from pathlib import Path


def test_hacs_uses_the_release_archive() -> None:
    """Require archive installation using the published release asset name."""
    manifest_path = Path(__file__).resolve().parents[1] / "hacs.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest: dict[str, object] = json.load(manifest_file)

    assert manifest["zip_release"] is True
    assert manifest["filename"] == "mynissan.zip"
