"""
📦 SQLite 저장소
- 메시지 수를 (방, 날짜, 시간, 사람, 종류) 단위로 쌓아둡니다.
- 하루가 지나도 기록이 남기 때문에 기간별 통계를 낼 수 있어요.
  ('오늘' 개수는 오늘 날짜만 골라서 보여주므로 자정이 지나면 자연스럽게 0부터 시작)
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

KINDS = ["text", "photo", "video", "sticker", "gif", "voice", "file", "etc"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS stats (
    chat_id INTEGER NOT NULL,
    day     TEXT    NOT NULL,          -- YYYY-MM-DD (봇 시간대 기준)
    hour    INTEGER NOT NULL,          -- 0~23
    user_id INTEGER NOT NULL,
    kind    TEXT    NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, day, hour, user_id, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS stats_user ON stats (chat_id, user_id, day);

CREATE TABLE IF NOT EXISTS users (
    user_id  INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    username TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title   TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    day     TEXT    NOT NULL,
    ts      TEXT    NOT NULL,
    user_id INTEGER NOT NULL,
    kind    TEXT    NOT NULL           -- join | leave | kick
);
CREATE INDEX IF NOT EXISTS events_chat ON events (chat_id, day);
"""


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(i)).isoformat() for i in range((end - start).days + 1)]


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ─────────────── 쓰기 ───────────────

    def _upsert_user(self, user_id: int, name: str, username: str | None) -> None:
        self.db.execute(
            "INSERT INTO users (user_id, name, username) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username",
            (user_id, name, username),
        )

    def add_message(self, chat_id: int, chat_title: str | None, user_id: int,
                    name: str, username: str | None, kind: str, when: datetime,
                    n: int = 1) -> None:
        self._upsert_user(user_id, name, username)
        self.db.execute(
            "INSERT INTO chats (chat_id, title) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
            (chat_id, chat_title),
        )
        self.db.execute(
            "INSERT INTO stats (chat_id, day, hour, user_id, kind, count) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO UPDATE SET count = count + excluded.count",
            (chat_id, when.date().isoformat(), when.hour, user_id, kind, n),
        )
        self.db.commit()

    def add_event(self, chat_id: int, user_id: int, name: str,
                  username: str | None, kind: str, when: datetime) -> None:
        self._upsert_user(user_id, name, username)
        self.db.execute(
            "INSERT INTO events (chat_id, day, ts, user_id, kind) VALUES (?, ?, ?, ?, ?)",
            (chat_id, when.date().isoformat(), when.isoformat(), user_id, kind),
        )
        self.db.commit()

    def migrate_json(self, path: Path, now: datetime) -> int:
        """예전 counts.json 의 '오늘' 기록을 옮겨옴. 옮긴 사람 수를 돌려줌."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        today, moved = now.date().isoformat(), 0
        for chat_id, entry in data.items():
            if entry.get("date") != today:
                continue
            for uid, u in entry.get("users", {}).items():
                if u.get("count"):
                    self.add_message(int(chat_id), None, int(uid), u.get("name", "?"),
                                     None, "text", now, u["count"])
                    moved += 1
        path.rename(path.with_suffix(path.suffix + ".migrated"))
        return moved

    # ─────────────── 읽기 ───────────────

    def chat_title(self, chat_id: int) -> str | None:
        row = self.db.execute("SELECT title FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
        return row["title"] if row else None

    def first_day(self, chat_id: int) -> str | None:
        row = self.db.execute("SELECT MIN(day) d FROM stats WHERE chat_id=?", (chat_id,)).fetchone()
        return row["d"]

    def user_chats(self, user_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT c.chat_id, c.title, SUM(s.count) cnt FROM stats s "
            "JOIN chats c ON c.chat_id = s.chat_id "
            "WHERE s.user_id=? AND s.chat_id < 0 GROUP BY s.chat_id ORDER BY cnt DESC",
            (user_id,),
        ).fetchall()
        return [{"id": r["chat_id"], "title": r["title"] or "이름 없는 방"} for r in rows]

    def ranking(self, chat_id: int, start: str, end: str, limit: int = 1000) -> list[dict]:
        rows = self.db.execute(
            "SELECT s.user_id, SUM(s.count) cnt, COUNT(DISTINCT s.day) days, "
            "       u.name, u.username "
            "FROM stats s LEFT JOIN users u ON u.user_id = s.user_id "
            "WHERE s.chat_id=? AND s.day BETWEEN ? AND ? "
            "GROUP BY s.user_id ORDER BY cnt DESC, s.user_id LIMIT ?",
            (chat_id, start, end, limit),
        ).fetchall()
        return [
            {"id": r["user_id"], "name": r["name"] or "알 수 없음",
             "username": r["username"], "count": r["cnt"], "days": r["days"]}
            for r in rows
        ]

    def _total(self, chat_id: int, start: str, end: str, user_id: int | None = None) -> int:
        q = "SELECT COALESCE(SUM(count),0) t FROM stats WHERE chat_id=? AND day BETWEEN ? AND ?"
        args = [chat_id, start, end]
        if user_id is not None:
            q += " AND user_id=?"
            args.append(user_id)
        return self.db.execute(q, args).fetchone()["t"]

    def _breakdown(self, chat_id: int, start: date, end: date, user_id: int | None = None) -> dict:
        """일별 / 시간대별 / 요일×시간 / 종류별 집계."""
        s, e = start.isoformat(), end.isoformat()
        where = "chat_id=? AND day BETWEEN ? AND ?"
        args: list = [chat_id, s, e]
        if user_id is not None:
            where += " AND user_id=?"
            args.append(user_id)

        daily = {d: {"day": d, "count": 0, "users": 0} for d in _days(start, end)}
        for r in self.db.execute(
            f"SELECT day, SUM(count) c, COUNT(DISTINCT user_id) u FROM stats WHERE {where} GROUP BY day",
            args,
        ):
            daily[r["day"]].update(count=r["c"], users=r["u"])

        hourly = [0] * 24
        heat = [[0] * 24 for _ in range(7)]  # 월~일 × 0~23시
        for r in self.db.execute(
            f"SELECT day, hour, SUM(count) c FROM stats WHERE {where} GROUP BY day, hour", args
        ):
            hourly[r["hour"]] += r["c"]
            heat[date.fromisoformat(r["day"]).weekday()][r["hour"]] += r["c"]

        kinds = {k: 0 for k in KINDS}
        for r in self.db.execute(
            f"SELECT kind, SUM(count) c FROM stats WHERE {where} GROUP BY kind", args
        ):
            kinds[r["kind"] if r["kind"] in kinds else "etc"] += r["c"]

        daily_list = list(daily.values())
        total = sum(d["count"] for d in daily_list)
        peak_day = max(daily_list, key=lambda d: d["count"]) if total else None
        peak_hour = max(range(24), key=lambda h: hourly[h]) if total else None
        return {
            "total": total,
            "daily": daily_list,
            "hourly": hourly,
            "heatmap": heat,
            "kinds": kinds,
            "peak_day": peak_day and {"day": peak_day["day"], "count": peak_day["count"]},
            "peak_hour": None if peak_hour is None else {"hour": peak_hour, "count": hourly[peak_hour]},
        }

    def range_stats(self, chat_id: int, start: date, end: date) -> dict:
        days = (end - start).days + 1
        b = self._breakdown(chat_id, start, end)
        prev_end = start - timedelta(1)
        prev_start = prev_end - timedelta(days - 1)
        ranking = self.ranking(chat_id, start.isoformat(), end.isoformat())

        events = {"join": 0, "leave": 0, "kick": 0}
        for r in self.db.execute(
            "SELECT kind, COUNT(*) c FROM events WHERE chat_id=? AND day BETWEEN ? AND ? GROUP BY kind",
            (chat_id, start.isoformat(), end.isoformat()),
        ):
            events[r["kind"]] = r["c"]

        return {
            "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
            "summary": {
                "total": b["total"],
                "prev_total": self._total(chat_id, prev_start.isoformat(), prev_end.isoformat()),
                "users": len(ranking),
                "avg": round(b["total"] / days, 1),
                "peak_day": b["peak_day"],
                "peak_hour": b["peak_hour"],
            },
            "daily": b["daily"],
            "hourly": b["hourly"],
            "heatmap": b["heatmap"],
            "kinds": b["kinds"],
            "events": events,
            "ranking": ranking,
        }

    def user_stats(self, chat_id: int, user_id: int, start: date, end: date) -> dict | None:
        s, e = start.isoformat(), end.isoformat()
        ranking = self.ranking(chat_id, s, e)
        total = sum(r["count"] for r in ranking)
        rank, me = None, None
        for i, r in enumerate(ranking):
            if r["id"] == user_id:
                # 동점자는 같은 등수
                rank = 1 + sum(1 for x in ranking[:i] if x["count"] > r["count"])
                me = r
                break
        u = self.db.execute("SELECT name, username FROM users WHERE user_id=?", (user_id,)).fetchone()
        if u is None:
            return None
        b = self._breakdown(chat_id, start, end, user_id)
        days = (end - start).days + 1
        return {
            "user": {"id": user_id, "name": u["name"], "username": u["username"]},
            "range": {"start": s, "end": e, "days": days},
            "count": b["total"],
            "rank": rank,
            "of": len(ranking),
            "share": round(b["total"] / total * 100, 1) if total else 0,
            "active_days": me["days"] if me else 0,
            "avg": round(b["total"] / days, 1),
            "peak_day": b["peak_day"],
            "peak_hour": b["peak_hour"],
            "daily": b["daily"],
            "hourly": b["hourly"],
            "kinds": b["kinds"],
        }
