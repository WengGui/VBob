from __future__ import annotations

import pytest

from vbob.extractors import FeaturePipeline, FileRef


def extract(filename: str, dirs: tuple[str, ...] = ()) -> dict:
    return FeaturePipeline().extract(FileRef(filename=filename, rel_path=filename, dirs=dirs))


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("SSIS-001-C.mp4", {"jav_code": "SSIS-001", "jav_family": "standard"}),
        ("[ThZu.Cc]HEYZO-1234_1080p.mp4", {"jav_code": "HEYZO-1234", "jav_family": "heyzo"}),
        ("FC2-PPV-1234567.mp4", {"jav_code": "FC2-PPV-1234567", "jav_family": "fc2"}),
        ("FC2-1234567.mp4", {"jav_code": "FC2-1234567", "jav_family": "fc2"}),
        ("123456-789.mp4", {"jav_code": "123456-789", "jav_family": "uncensored"}),
    ],
)
def test_jav_code_families(filename: str, expected: dict) -> None:
    features = extract(filename)
    for key, value in expected.items():
        assert features[key] == value
    assert features["jav_match_key"]


def test_jav_match_key_ignores_leading_zeros() -> None:
    assert extract("SSIS-001.mp4")["jav_match_key"] == extract("SSIS-01.mp4")["jav_match_key"]


@pytest.mark.parametrize("filename", ["PART-01.mp4", "CD-02.mkv", "WEB-DL.mp4", "S01E02.mkv"])
def test_jav_code_false_positives(filename: str) -> None:
    assert "jav_code" not in extract(filename)


def test_jav_code_from_parent_folder() -> None:
    features = extract("video.mp4", dirs=("SSIS-002",))
    assert features["jav_code"] == "SSIS-002"


def test_title_and_year() -> None:
    features = extract("Some.Movie.2023.1080p.WEB-DL.x264.mkv")
    assert features["title"] == "Some Movie"
    assert features["year"] == 2023


def test_title_with_chinese_brackets() -> None:
    features = extract("【中字】My.Show.2021.1080p.mp4")
    assert features["year"] == 2021
    assert "My Show" in features["title"]
