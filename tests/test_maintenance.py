"""删除记录后的图片清理、启动清理与迁移备份。"""

from __future__ import annotations

import base64
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from vbob.db import Database

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n2kAAAAASUVORK5CYII="
)


def scan(client: TestClient, root_id: int) -> None:
    response = client.post("/api/scans", json={"root_id": root_id})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return
        time.sleep(0.05)
    raise AssertionError("scan timed out")


def setup_video(client: TestClient, tmp_path: Path) -> int:
    media = tmp_path / "media"
    media.mkdir()
    (media / "SSIS-001.mp4").write_bytes(b"video")
    client.put("/api/settings", json={"scan": {"min_size_mb": 0}})
    root = client.post("/api/scan-roots", json={"path": str(media)}).json()
    scan(client, root["id"])
    return client.get("/api/videos").json()["items"][0]["id"]


def test_delete_video_removes_cover_file(client: TestClient, tmp_path: Path) -> None:
    video_id = setup_video(client, tmp_path)
    response = client.post(
        f"/api/videos/{video_id}/cover",
        files={"file": ("cover.png", PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    data_dir = Path(client.app.state.data_dir)
    cover = data_dir / "covers" / "videos" / f"{video_id}.png"
    assert cover.is_file()

    assert client.delete(f"/api/videos/{video_id}").status_code == 204
    assert not cover.exists()


def test_delete_actress_removes_cover_file(client: TestClient, tmp_path: Path) -> None:
    created = client.post("/api/actresses", json={"name": "测试演员"}).json()
    actress_id = created["id"]
    response = client.post(
        f"/api/actresses/{actress_id}/cover",
        files={"file": ("cover.png", PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    data_dir = Path(client.app.state.data_dir)
    cover = data_dir / "covers" / "actresses" / f"{actress_id}.png"
    assert cover.is_file()

    assert client.delete(f"/api/actresses/{actress_id}").status_code == 204
    assert not cover.exists()


def test_cleanup_unused_images_keeps_referenced_files(
    client: TestClient, tmp_path: Path
) -> None:
    video_id = setup_video(client, tmp_path)
    client.post(
        f"/api/videos/{video_id}/cover",
        files={"file": ("cover.png", PNG, "image/png")},
    )
    data_dir = Path(client.app.state.data_dir)
    kept = data_dir / "covers" / "videos" / f"{video_id}.png"
    orphan = data_dir / "covers" / "videos" / "9999.png"
    orphan.write_bytes(PNG)
    orphan_screenshot = data_dir / "screenshots" / "9999.png"
    orphan_screenshot.write_bytes(PNG)

    removed = client.app.state.store.cleanup_unused_images()

    assert removed == 2
    assert kept.is_file()
    assert not orphan.exists()
    assert not orphan_screenshot.exists()


def test_migration_creates_backup_before_upgrade(tmp_path, monkeypatch) -> None:
    """已有数据库应用新迁移前，先复制一份到 backups/。"""
    import vbob.db as db_module

    db_path = tmp_path / "vbob.db"
    Database(db_path).migrate()

    # 复制全部迁移，并追加一个新版本，模拟升级场景。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for sql_file in Path(db_module.MIGRATIONS_DIR).glob("*.sql"):
        shutil.copy(sql_file, migrations / sql_file.name)
    (migrations / "9999_extra.sql").write_text(
        "CREATE TABLE probe_table (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations)

    db = Database(db_path)
    db.migrate()

    backups = sorted((tmp_path / "backups").glob("vbob-*.db"))
    assert len(backups) == 1
    # 备份里没有新表，说明备份发生在迁移执行之前。
    with Database(backups[0]).connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "probe_table" not in tables
    with db.connection() as conn:
        assert {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
        } >= {"0001", "9999"}


def test_cover_cache_header_depends_on_version(client: TestClient, tmp_path: Path) -> None:
    video_id = setup_video(client, tmp_path)
    client.post(
        f"/api/videos/{video_id}/cover",
        files={"file": ("cover.png", PNG, "image/png")},
    )
    plain = client.get(f"/api/videos/{video_id}/cover")
    assert plain.headers["cache-control"] == "no-cache"
    versioned = client.get(f"/api/videos/{video_id}/cover", params={"v": "abc"})
    assert "max-age" in versioned.headers["cache-control"]
