from db import get_db


def add_entry(game_name: str, server_name: str, source_type: str, feed_url: str) -> str:
    """카탈로그에 피드를 추가한다. 이미 있으면 'duplicate', 아니면 'ok'."""
    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT id FROM game_catalog WHERE game_name=? AND server_name=? AND feed_url=?",
            (game_name, server_name, feed_url),
        ).fetchone()
        if exists:
            return "duplicate"
        conn.execute(
            "INSERT INTO game_catalog (game_name, server_name, source_type, feed_url) VALUES (?,?,?,?)",
            (game_name, server_name, source_type, feed_url),
        )
        conn.commit()
        return "ok"
    finally:
        conn.close()


def remove_entries(game_name: str, server_name: str, feed_url: str | None = None) -> int:
    """카탈로그에서 게임/서버(및 선택적으로 특정 URL)의 피드를 삭제하고 삭제된 행 수를 반환한다."""
    conn = get_db()
    try:
        if feed_url:
            deleted = conn.execute(
                "DELETE FROM game_catalog WHERE game_name=? AND server_name=? AND feed_url=?",
                (game_name, server_name, feed_url),
            ).rowcount
        else:
            deleted = conn.execute(
                "DELETE FROM game_catalog WHERE game_name=? AND server_name=?",
                (game_name, server_name),
            ).rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_entries(game_name: str, server_name: str) -> list[dict]:
    """특정 게임/서버에 등록된 모든 피드를 반환한다."""
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, game_name, server_name, source_type, feed_url FROM game_catalog "
            "WHERE game_name=? AND server_name=?",
            (game_name, server_name),
        ).fetchall()]
    finally:
        conn.close()


def list_all() -> list[dict]:
    """카탈로그 전체를 반환한다."""
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, game_name, server_name, source_type, feed_url FROM game_catalog "
            "ORDER BY game_name, server_name, source_type"
        ).fetchall()]
    finally:
        conn.close()


def search_game_names(current: str) -> list[str]:
    """자동완성용: 입력값을 포함하는 게임 이름 목록(중복 제거, 최대 25개)."""
    conn = get_db()
    try:
        return [r["game_name"] for r in conn.execute(
            "SELECT DISTINCT game_name FROM game_catalog WHERE game_name LIKE ? "
            "ORDER BY game_name LIMIT 25",
            (f"%{current}%",),
        ).fetchall()]
    finally:
        conn.close()


def search_server_names(game_name: str, current: str) -> list[str]:
    """자동완성용: 특정 게임에 속한 서버 이름 목록(중복 제거, 최대 25개)."""
    conn = get_db()
    try:
        return [r["server_name"] for r in conn.execute(
            "SELECT DISTINCT server_name FROM game_catalog "
            "WHERE game_name=? AND server_name LIKE ? "
            "ORDER BY server_name LIMIT 25",
            (game_name, f"%{current}%"),
        ).fetchall()]
    finally:
        conn.close()
