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


def test_episode_grouping_by_folder_and_number() -> None:
    first = extract("光与影的传说1.rmvb", dirs=("光与影的传说",))
    third = extract("光与影的传说3.rmvb", dirs=("光与影的传说",))
    assert first["title"] == "光与影的传说"
    assert first["is_episode"] is True
    assert first["episode"] == 1
    assert first["episode_key"] == third["episode_key"]

    # 外传与正片共享前缀但标题不同，应单独成组。
    side = extract("光与影的传说外传1.rmvb", dirs=("光与影的传说",))
    assert side["episode_key"] != first["episode_key"]
    assert side["title"] == "光与影的传说外传"


def test_episode_only_filename_uses_folder_title() -> None:
    features = extract("第3集.rmvb", dirs=("光与影的传说",))
    assert features["title"] == "光与影的传说"
    assert features["episode"] == 3
    assert features["episode_key"]

    numeric = extract("03.mp4", dirs=("某部剧",))
    assert numeric["title"] == "某部剧"
    assert numeric["episode"] == 3


def test_episode_markers_and_sequel_guard() -> None:
    episode = extract("The Lair Episode 1.mp4", dirs=("The Lair",))
    assert episode["title"] == "The Lair"
    assert episode["episode_key"]

    season = extract("Show.S01E03.mkv", dirs=("Show",))
    assert season["title"] == "Show"
    assert season["episode"] == "S01E03"

    # 独立续集不应仅因结尾数字被当成剧集。
    sequel = extract("Toy Story 2.mp4", dirs=("Toy Story 2",))
    assert "episode_key" not in sequel
    assert sequel["title"] == "Toy Story 2"


def test_episode_key_scoped_to_parent_folder() -> None:
    a = extract("Show1.mp4", dirs=("Show",))
    b = extract("Show1.mp4", dirs=("Show",))
    assert a["episode_key"] == b["episode_key"]

    other = FeaturePipeline().extract(
        FileRef(filename="Show1.mp4", rel_path="其他/Show/Show1.mp4", dirs=("Show",))
    )
    assert other["episode_key"] != a["episode_key"]


def test_chinese_episode_number() -> None:
    features = extract("某剧 第十二集.mp4", dirs=("某剧",))
    assert features["title"] == "某剧"
    assert features["episode"] == 12
    assert features["episode_key"]
