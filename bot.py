"""
💬 하루 채팅 카운터 봇
- 채팅방의 오늘 채팅 개수를 셉니다.
- 매일 자정(기본: 한국 시간)에 0으로 초기화됩니다.
- /채팅 (또는 /chat) 으로 오늘의 채팅 개수를 확인합니다.
"""

import json
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN", "")
TZ = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Asia/Seoul"))
DATA_FILE = Path(os.environ.get("DATA_FILE", "counts.json"))

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("haru")


# ─────────────────────────── 저장소 ───────────────────────────

def load_data() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data: dict) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)


DATA = load_data()  # { "chat_id": {"date": "YYYY-MM-DD", "count": int} }


def now() -> datetime:
    return datetime.now(TZ)


def today_entry(chat_id: int) -> dict:
    """오늘 날짜의 기록을 돌려줌. 날짜가 바뀌었으면 0으로 초기화(자정 리셋)."""
    key = str(chat_id)
    today = now().date().isoformat()
    entry = DATA.get(key)
    if entry is None or entry.get("date") != today:
        entry = {"date": today, "count": 0}
        DATA[key] = entry
    return entry


# ─────────────────────────── 꾸미기 ───────────────────────────

def mood(count: int) -> str:
    if count == 0:
        return random.choice([
            "🦗 <i>귀뚤귀뚤… 아직 아무도 말이 없어요</i>",
            "😴 <i>조용한 하루의 시작이에요</i>",
        ])
    if count < 50:
        return random.choice([
            "🌱 <i>새싹처럼 조금씩 자라는 중!</i>",
            "☕ <i>여유로운 대화가 오가는 중이에요</i>",
        ])
    if count < 200:
        return random.choice([
            "💬 <i>오늘 수다 꽤 떠는데요?</i>",
            "✨ <i>분위기 좋아요, 계속 가보자고!</i>",
        ])
    if count < 500:
        return random.choice([
            "🔥 <i>채팅방이 뜨겁게 달아오르는 중!</i>",
            "🚀 <i>대화 엔진 풀가동!</i>",
        ])
    if count < 1000:
        return random.choice([
            "🌋 <i>이 정도면 폭발 직전이에요!</i>",
            "🎉 <i>오늘 무슨 일 있어요?! 엄청나요</i>",
        ])
    return random.choice([
        "👑 <i>전설의 수다방 등극…!</i>",
        "🏆 <i>키보드가 버티고 있나요? 대기록이에요!</i>",
    ])


def time_left_text() -> str:
    n = now()
    midnight = datetime.combine(n.date() + timedelta(days=1), datetime.min.time(), TZ)
    left = midnight - n
    hours, rem = divmod(int(left.total_seconds()), 3600)
    minutes = rem // 60
    return f"{hours}시간 {minutes}분" if hours else f"{minutes}분"


def build_message(chat_title: str | None, count: int) -> str:
    n = now()
    date_text = f"{n.year}년 {n.month}월 {n.day}일 ({WEEKDAYS[n.weekday()]})"
    title = f"🏠 <b>{escape(chat_title)}</b>\n" if chat_title else ""
    return (
        f"📊 <b>오늘의 채팅 현황</b>\n"
        f"{title}"
        f"\n"
        f"<blockquote>📅 <i>{date_text}</i>\n"
        f"💬 오늘 채팅 <b>{count:,}</b>개</blockquote>\n"
        f"\n"
        f"{mood(count)}\n"
        f"\n"
        f"⏰ <i>자정 초기화까지</i> <b>{time_left_text()}</b>"
    )


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ─────────────────────────── 핸들러 ───────────────────────────

async def count_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    entry = today_entry(msg.chat_id)
    entry["count"] += 1
    save_data(DATA)


async def show_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    entry = today_entry(chat.id)
    title = chat.title if chat.type != "private" else None
    await msg.reply_text(
        build_message(title, entry["count"]), parse_mode=ParseMode.HTML
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "👋 <b>안녕하세요! 하루 채팅 카운터예요</b>\n"
        "\n"
        "<blockquote>💬 이 방의 <b>오늘 채팅 개수</b>를 세고 있어요\n"
        "🌙 매일 <i>자정</i>에 0으로 초기화돼요</blockquote>\n"
        "\n"
        "👉 <b>/채팅</b> 을 입력해서 확인해보세요!",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────── 실행 ───────────────────────────

def main() -> None:
    if not TOKEN:
        raise SystemExit("❌ BOT_TOKEN 환경변수를 설정해주세요.")

    app = Application.builder().token(TOKEN).build()

    # /채팅 은 텔레그램 규격상 '명령어'로 인식되지 않으므로 정규식으로 받음
    korean_cmd = filters.Regex(r"^/채팅(@\w+)?(\s|$)")

    app.add_handler(CommandHandler(["chat", "count"], show_count))
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(korean_cmd, show_count))

    # 명령어를 제외한 모든 새 메시지(텍스트·사진·스티커·영상 등)를 카운트
    app.add_handler(
        MessageHandler(
            filters.UpdateType.MESSAGE & ~filters.COMMAND & ~korean_cmd
            & ~filters.StatusUpdate.ALL,
            count_message,
        ),
        group=1,
    )

    log.info("🤖 봇 시작! (시간대: %s, 저장 파일: %s)", TZ, DATA_FILE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
