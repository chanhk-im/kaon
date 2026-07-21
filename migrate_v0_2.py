"""
v0.1 -> v0.2 1회성 DB 마이그레이션 스크립트.

v0.1의 subscriptions(game_name, source_type, feed_url 직접 보관)/channels(guild_id, game_name)
구조를, v0.2의 game_catalog 참조 구조로 옮긴다. 서버(지역) 구분이 없던 기존 데이터는
전부 DEFAULT_SERVER_NAME 서버로 이관한다.

실행 전 자동으로 DB 파일을 백업하고, 기존 테이블은 삭제하지 않고 *_v01 접미사로 남겨둔다.
이미 마이그레이션된 DB(= subscriptions에 catalog_id 컬럼이 있는 경우)에서는 아무 것도 하지 않는다.

사용법: python migrate_v0_2.py
(.env의 DATA_DIR 설정을 그대로 사용한다)
"""
import shutil
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from db import DB_PATH  # noqa: E402  (load_dotenv 이후 import 되어야 DATA_DIR 반영됨)

DEFAULT_SERVER_NAME = "기본"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if not _table_exists(conn, "subscriptions"):
        print("subscriptions 테이블이 없습니다. 마이그레이션할 데이터가 없어 새 스키마로 바로 초기화합니다.")
        conn.close()
        from db import init_db
        init_db()
        return

    if _has_column(conn, "subscriptions", "catalog_id"):
        print("이미 v0.2 스키마입니다. 마이그레이션을 건너뜁니다.")
        conn.close()
        return

    if not _has_column(conn, "subscriptions", "feed_url"):
        raise RuntimeError(
            "subscriptions 테이블 구조를 인식할 수 없습니다. 수동으로 확인해주세요."
        )

    backup_path = f"{DB_PATH}.pre-v0.2.{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}.bak"
    conn.close()
    shutil.copy2(DB_PATH, backup_path)
    print(f"백업 완료: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")

        conn.execute("ALTER TABLE subscriptions RENAME TO subscriptions_v01")
        conn.execute("ALTER TABLE channels RENAME TO channels_v01")

        conn.executescript("""
            CREATE TABLE game_catalog (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name    TEXT NOT NULL,
                server_name  TEXT NOT NULL,
                source_type  TEXT NOT NULL,
                feed_url     TEXT NOT NULL,
                UNIQUE(game_name, server_name, feed_url)
            );
            CREATE TABLE subscriptions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT NOT NULL,
                catalog_id   INTEGER NOT NULL REFERENCES game_catalog(id),
                last_sent_at TEXT,
                UNIQUE(guild_id, catalog_id)
            );
            CREATE TABLE channels (
                guild_id    TEXT NOT NULL,
                game_name   TEXT NOT NULL,
                server_name TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                PRIMARY KEY(guild_id, game_name, server_name)
            );
            CREATE TABLE IF NOT EXISTS command_channels (
                guild_id    TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                PRIMARY KEY(guild_id, channel_id)
            );
        """)

        old_subs = conn.execute("SELECT * FROM subscriptions_v01").fetchall()
        old_channels = conn.execute("SELECT * FROM channels_v01").fetchall()

        catalog_id_map: dict[tuple[str, str], int] = {}
        for r in old_subs:
            key = (r["game_name"], r["feed_url"])
            if key in catalog_id_map:
                continue
            cur = conn.execute(
                "INSERT INTO game_catalog (game_name, server_name, source_type, feed_url) "
                "VALUES (?,?,?,?)",
                (r["game_name"], DEFAULT_SERVER_NAME, r["source_type"], r["feed_url"]),
            )
            catalog_id_map[key] = cur.lastrowid

        sub_count = 0
        for r in old_subs:
            catalog_id = catalog_id_map[(r["game_name"], r["feed_url"])]
            conn.execute(
                "INSERT INTO subscriptions (guild_id, catalog_id, last_sent_at) VALUES (?,?,?)",
                (r["guild_id"], catalog_id, r["last_sent_at"]),
            )
            sub_count += 1

        channel_count = 0
        for r in old_channels:
            conn.execute(
                "INSERT INTO channels (guild_id, game_name, server_name, channel_id) VALUES (?,?,?,?)",
                (r["guild_id"], r["game_name"], DEFAULT_SERVER_NAME, r["channel_id"]),
            )
            channel_count += 1

        conn.commit()
        print(
            f"마이그레이션 완료: game_catalog {len(catalog_id_map)}개, "
            f"subscriptions {sub_count}개, channels {channel_count}개."
        )
        print("기존 테이블은 subscriptions_v01 / channels_v01 이름으로 보존했습니다. "
              "정상 동작 확인 후 수동으로 삭제해도 됩니다.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
