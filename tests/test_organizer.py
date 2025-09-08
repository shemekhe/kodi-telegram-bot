import os
import tempfile

import config
from organizer import parse_filename, build_final_path


def test_parse_movie_basic():
    p = parse_filename("Bullet.Train.2022.1080p.BluRay.mkv")
    assert p.category == "movie"
    assert p.title == "Bullet Train"
    assert p.year == 2022
    assert p.normalized_stem == "Bullet Train (2022)"


def test_parse_movie_with_edition_and_group():
    p = parse_filename("The.Matrix.1999.1080p.Remastered.BluRay.x265.Group.mkv")
    assert p.category == "movie"
    assert p.year == 1999
    assert "Matrix" in p.title
    assert p.normalized_stem == "The Matrix (1999)"


def test_parse_series_alt_formats():
    # 1x05 pattern
    p = parse_filename("Show.Name.1x05.1080p.WEB-DL.mkv")
    assert p.category == "series" and p.season == 1 and p.episode == 5
    # 205 numeric pattern
    p2 = parse_filename("Show.Name.205.720p.HDTV.mkv")
    assert p2.category == "series" and p2.season == 2 and p2.episode == 5
    # multi-episode pattern picks first
    p3 = parse_filename("Show.Name.S02E05E06.1080p.WEB.mkv")
    assert p3.category == "series" and p3.season == 2 and p3.episode == 5


def test_parse_series_weird_season_token():
    p = parse_filename("The.Mentalist.SO4E24.720p.WEB-DL.mkv")
    assert p.category == "series"
    assert p.season == 4 and p.episode == 24
    assert p.title == "The Mentalist"
    assert p.normalized_stem.startswith("The Mentalist S04E24")


def test_build_final_path_movie(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(config, "DOWNLOAD_DIR", td)
        monkeypatch.setattr(config, "ORGANIZE_MEDIA", True)
        path, fname = build_final_path("Finch.2021.1080p.WEB-DL.mkv", base_dir=td)
        assert fname.startswith("Finch (2021)")
        assert path.endswith(f"{config.MOVIES_DIR_NAME}/Finch (2021)/Finch (2021).mkv")
        assert os.path.exists(os.path.dirname(path))


def test_build_final_path_series(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(config, "DOWNLOAD_DIR", td)
        monkeypatch.setattr(config, "ORGANIZE_MEDIA", True)
        path, fname = build_final_path("The.Mentalist.S02E06.720p.WEB-DL.mkv", base_dir=td)
        assert "Season 2" in path
        assert fname.startswith("The Mentalist S02E06")
        assert os.path.exists(os.path.dirname(path))


def test_build_final_path_other(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(config, "DOWNLOAD_DIR", td)
        monkeypatch.setattr(config, "ORGANIZE_MEDIA", True)
        path, fname = build_final_path("Random.File.Without.Year.mkv", base_dir=td)
        assert fname == "Random.File.Without.Year.mkv"  # unchanged
        assert path.startswith(os.path.join(td, config.OTHER_DIR_NAME))


def test_forced_category_override(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(config, "DOWNLOAD_DIR", td)
        monkeypatch.setattr(config, "ORGANIZE_MEDIA", True)
        # Ambiguous: no year but force movie
    path, _ = build_final_path("Some.Random.Name.mkv", base_dir=td, forced_category="movie")
    assert config.MOVIES_DIR_NAME in path
