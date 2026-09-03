from pathlib import Path

import pytest

from scripts.catalog.upload_bundle import _package_tier_guard


@pytest.mark.parametrize("directory", ["media", "archives"])
def test_package_directories_are_refused_without_override(tmp_path, capsys, directory):
    package = tmp_path / directory / "clip-one" / "package.tar.gz"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"package")

    result = _package_tier_guard([package], tmp_path, allow_media=False)

    assert result == 2
    error = capsys.readouterr().err
    assert "s3://6thsense-processed/imported/<cohort>/" in error
    assert "needs the pipeline" in error


def test_allow_media_explicitly_bypasses_the_package_guard(tmp_path):
    package = tmp_path / "media" / "clip-one" / "video" / "left.mp4"
    assert _package_tier_guard([package], tmp_path, allow_media=True) is None


def test_preview_directories_remain_uploadable(tmp_path):
    poster = tmp_path / "posters" / "clip-one.jpg"
    preview = tmp_path / "previews" / "clip-one.mp4"
    assert _package_tier_guard([poster, preview], tmp_path, allow_media=False) is None
