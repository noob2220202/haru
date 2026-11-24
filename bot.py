"""
💬 하루 채팅 카운터 봇
- 채팅방의 오늘 채팅 개수를 셉니다.
- 매일 자정(기본: 한국 시간)에 0으로 초기화됩니다.
- /채팅 (또는 /chat) 으로 내 오늘 채팅 개수와 순위를 확인합니다.
- /랭킹 (또는 /rank) 으로 오늘의 채팅 순위를 확인합니다. (페이지당 10명)
- /통계 (또는 /stats) 로 기간별 통계 미니앱을 엽니다.
- /전체태그 (또는 /all) 로 방 인원 전체를 태그합니다. (방 관리자만)
- /방탈출 (또는 /escape) 로 방탈출 사이트 버튼을 띄웁니다.
- 들낙 방지: 스스로 방을 나간 사람은 조용히 영구 차단하고 퇴장 메시지를 지웁니다. (봇이 관리자여야 함)
"""

import asyncio
import math
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import (
    BotCommand,
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from storage import Store
from webapp import StatsServer

TOKEN = os.environ.get("BOT_TOKEN", "")
TZ = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Asia/Seoul"))
DB_FILE = Path(os.environ.get("DB_FILE", "haru.db"))
OLD_JSON = Path(os.environ.get("DATA_FILE", "counts.json"))  # 예전 버전 저장 파일
WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("WEB_PORT", "8765"))  # 0 이면 미니앱 서버 끔
APP_SHORT_NAME = os.environ.get("APP_SHORT_NAME", "")  # /newapp 으로 만든 경우만
ESCAPE_URL = os.environ.get("ESCAPE_URL", "https://haru.pengueverything.cloud/")

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
PAGE_SIZE = 10
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("haru")


# ─────────────────────────── 저장소 ───────────────────────────

STORE = Store(DB_FILE)


def now() -> datetime:
    return datetime.now(TZ)


def today_ranking(chat_id: int) -> list[dict]:
    """오늘 날짜 기록만 모아서 순위로. 날짜가 바뀌면 자연스럽게 0부터(자정 리셋)."""
    today = now().date().isoformat()
    return STORE.ranking(chat_id, today, today)


def message_kind(msg: Message) -> str:
    if msg.text:
        return "text"
    if msg.photo:
        return "photo"
    if msg.video or msg.video_note:
        return "video"
    if msg.sticker:
        return "sticker"
    if msg.animation:
        return "gif"
    if msg.voice or msg.audio:
        return "voice"
    if msg.document:
        return "file"
    return "etc"


def app_link(bot, chat_id: int | None) -> str:
    """미니앱을 여는 t.me 링크. 방 정보는 startapp 파라미터로 넘김."""
    base = f"https://t.me/{bot.username}"
    if APP_SHORT_NAME:
        base += f"/{APP_SHORT_NAME}"
    param = f"c{abs(chat_id)}" if chat_id and chat_id < 0 else "home"
    return f"{base}?startapp={param}"


def stats_button(bot, chat_id: int, label: str = "📊 기간별 통계 보기") -> list:
    return [InlineKeyboardButton(label, url=app_link(bot, chat_id))]


# ─────────────────────────── 꾸미기 ───────────────────────────

def mood(count: int) -> str:
    if count == 0:
        return random.choice([
            "🫥 <i>오늘은 아직 눈팅 중이시네요…</i>",
            "🤐 <i>침묵은 금이라지만, 한마디 해보세요!</i>",
        ])
    if count < 10:
        return random.choice([
            "🌱 <i>슬슬 시동 거는 중!</i>",
            "☕ <i>여유롭게 대화 중이시네요</i>",
        ])
    if count < 30:
        return random.choice([
            "💬 <i>오늘 말 좀 하시는데요?</i>",
            "✨ <i>분위기 메이커 등장!</i>",
        ])
    if count < 100:
        return random.choice([
            "🔥 <i>손가락이 불타고 있어요!</i>",
            "🚀 <i>수다 엔진 풀가동!</i>",
        ])
    if count < 300:
        return random.choice([
            "🌋 <i>오늘 이 방의 주인공은 당신!</i>",
            "🎤 <i>마이크 독점 중이시네요 ㅋㅋ</i>",
        ])
    return random.choice([
        "👑 <i>전설의 수다왕 등극…!</i>",
        "🏆 <i>키보드 괜찮으세요? 대기록이에요!</i>",
    ])


def time_left_text() -> str:
    n = now()
    midnight = datetime.combine(n.date() + timedelta(days=1), datetime.min.time(), TZ)
    left = midnight - n
    hours, rem = divmod(int(left.total_seconds()), 3600)
    minutes = rem // 60
    return f"{hours}시간 {minutes}분" if hours else f"{minutes}분"


def build_message(chat_title: str | None, ranking: list[dict], user) -> str:
    """/채팅: 요청한 사람의 오늘 채팅 개수 + 순위."""
    n = now()
    date_text = f"{n.year}년 {n.month}월 {n.day}일 ({WEEKDAYS[n.weekday()]})"
    title = f"🏠 <i>{escape(chat_title)}</i>\n" if chat_title else ""

    mine = next((u["count"] for u in ranking if u["id"] == user.id), 0)
    if mine:
        rank = 1 + sum(1 for u in ranking if u["count"] > mine)
        icon = MEDALS.get(rank, "🏅")
        rank_line = f"{icon} 오늘 순위 <b>{rank}</b>등 <i>/ {len(ranking)}명</i>"
    else:
        rank_line = "🏅 오늘 순위 <i>아직 없음</i>"

    return (
        f"📊 <b>{escape(user.full_name)}</b>님의 오늘 채팅\n"
        f"{title}"
        f"\n"
        f"<blockquote>📅 <i>{date_text}</i>\n"
        f"💬 내 채팅 <b>{mine:,}</b>개\n"
        f"{rank_line}</blockquote>\n"
        f"\n"
        f"{mood(mine)}\n"
        f"\n"
        f"⏰ <i>자정 초기화까지</i> <b>{time_left_text()}</b>"
    )


def build_ranking(chat_title: str | None, ranking: list[dict], page: int):
    """랭킹 메시지 텍스트와 페이지 버튼을 만듦. page 는 0부터 시작."""
    total = sum(u["count"] for u in ranking)
    pages = max(1, math.ceil(len(ranking) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)

    n = now()
    date_text = f"{n.month}월 {n.day}일 ({WEEKDAYS[n.weekday()]})"
    title = f"🏠 <b>{escape(chat_title)}</b>\n" if chat_title else ""
    head = f"🏆 <b>오늘의 채팅 랭킹</b>\n{title}📅 <i>{date_text}</i>\n\n"

    if not ranking:
        return head + "🦗 <i>아직 아무도 채팅하지 않았어요…\n첫 번째 주인공이 되어보세요!</i>", []

    lines = []
    start = page * PAGE_SIZE
    prev_count, prev_rank = None, 0
    for i, u in enumerate(ranking):
        # 동점자는 같은 등수
        rank = prev_rank if u["count"] == prev_count else i + 1
        prev_count, prev_rank = u["count"], rank
        if i < start:
            continue
        if i >= start + PAGE_SIZE:
            break
        icon = MEDALS.get(rank, f"<b>{rank}.</b>")
        name = u["name"] if len(u["name"]) <= 20 else u["name"][:19] + "…"
        pct = u["count"] / total * 100 if total else 0
        lines.append(
            f"{icon} {escape(name)} — <b>{u['count']:,}</b>개 <i>({pct:.0f}%)</i>"
        )

    text = (
        head
        + "<blockquote>" + "\n".join(lines) + "</blockquote>\n\n"
        + f"💬 <i>총</i> <b>{total:,}</b>개 · 👥 <i>참여</i> <b>{len(ranking)}</b>명\n"
        + f"📄 <i>{page + 1} / {pages} 페이지</i>"
    )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ 이전", callback_data=f"rank:{page - 1}"))
    nav.append(InlineKeyboardButton("🔄 새로고침", callback_data=f"rank:{page}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("다음 ▶️", callback_data=f"rank:{page + 1}"))
    return text, [nav]


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ─────────────────────────── 핸들러 ───────────────────────────

async def count_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    u = msg.from_user
    STORE.add_message(
        msg.chat_id, msg.chat.title, u.id, u.full_name, u.username,
        message_kind(msg), now(),
    )


def chat_title_of(chat) -> str | None:
    return chat.title if chat.type != "private" else None


async def show_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    text = build_message(chat_title_of(chat), today_ranking(chat.id), update.effective_user)
    markup = None
    if chat.type != "private":
        markup = InlineKeyboardMarkup([stats_button(context.bot, chat.id, "📊 자세한 통계")])
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup
    )


def ranking_markup(bot, chat, rows: list) -> InlineKeyboardMarkup | None:
    rows = [r for r in rows if r]
    if chat.type != "private":
        rows.append(stats_button(bot, chat.id))
    return InlineKeyboardMarkup(rows) if rows else None


async def show_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    text, nav = build_ranking(chat_title_of(chat), today_ranking(chat.id), 0)
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=ranking_markup(context.bot, chat, nav),
    )


async def ranking_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat = update.effective_chat
    page = int(query.data.split(":")[1])
    text, nav = build_ranking(chat_title_of(chat), today_ranking(chat.id), page)
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=ranking_markup(context.bot, chat, nav),
        )
        await query.answer()
    except BadRequest as e:
        if "not modified" in str(e).lower():
            await query.answer("✨ 이미 최신 랭킹이에요!")
        else:
            raise


# ─────────────────────────── 전체 태그 ───────────────────────────

TAG_BATCH = 5        # 한 메시지에 태그할 인원 (텔레그램은 한 메시지에서 앞쪽 몇 명에게만 알림을 보냄)
TAG_DELAY = 0        # 메시지 사이 간격(초). 0 = 바로바로 (텔레그램이 막으면 그만큼만 기다림)
TAGGING: dict[int, asyncio.Task] = {}
ANON_ADMIN_BOT = 1087968824  # 익명 관리자로 보낼 때의 발신자


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg, chat = update.effective_message, update.effective_chat
    # '익명 관리자'로 보낸 메시지는 방 자신이 발신자
    if msg.sender_chat and msg.sender_chat.id == chat.id:
        return True
    user = update.effective_user
    if user is None or user.id == ANON_ADMIN_BOT:
        return False
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in (ChatMember.OWNER, ChatMember.ADMINISTRATOR)


def mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{escape(name or "?")}</a>'


async def tag_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat = update.effective_message, update.effective_chat
    if chat.type == "private":
        await msg.reply_text("👥 <i>그룹에서만 쓸 수 있어요</i>", parse_mode=ParseMode.HTML)
        return
    if not await is_admin(update, context):
        await msg.reply_text("🔒 <b>방 관리자만</b> 전체태그를 쓸 수 있어요", parse_mode=ParseMode.HTML)
        return
    if chat.id in TAGGING and not TAGGING[chat.id].done():
        await msg.reply_text(
            "⏳ <i>이미 태그하는 중이에요</i>\n멈추려면 <b>/태그중지</b>", parse_mode=ParseMode.HTML
        )
        return

    members = [m for m in STORE.members(chat.id) if m["id"] != ANON_ADMIN_BOT]
    if not members:
        await msg.reply_text("🦗 <i>아직 태그할 인원을 모르겠어요</i>", parse_mode=ParseMode.HTML)
        return

    # '/전체태그 공지 확인해주세요' 처럼 뒤에 쓴 말을 같이 보여줌
    parts = (msg.text or "").split(maxsplit=1)
    note = parts[1].strip() if len(parts) > 1 else ""
    caller = update.effective_user
    by = "관리자" if caller is None or caller.id == ANON_ADMIN_BOT else escape(caller.full_name)
    batches = [members[i:i + TAG_BATCH] for i in range(0, len(members), TAG_BATCH)]

    head = f"📢 <b>전체 호출</b> <i>· {by}</i>\n"
    if note:
        head += f"\n<blockquote>{escape(note)}</blockquote>\n"
    head += f"\n👥 <b>{len(members)}</b>명 태그할게요 <i>(메시지 {len(batches)}개)</i>"
    await msg.reply_text(head, parse_mode=ParseMode.HTML)

    TAGGING[chat.id] = asyncio.create_task(
        send_tags(context.bot, chat.id, batches, msg.message_id)
    )


async def send_tags(bot, chat_id: int, batches: list[list[dict]], reply_to: int) -> None:
    total = len(batches)
    try:
        for i, batch in enumerate(batches, 1):
            text = f"🔔 <i>{i}/{total}</i>  " + "  ".join(mention(m["id"], m["name"]) for m in batch)
            while True:
                try:
                    await bot.send_message(
                        chat_id, text, parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply_to, allow_sending_without_reply=True,
                    )
                    break
                except RetryAfter as e:  # 텔레그램이 잠깐 쉬라고 하면 기다렸다 재시도
                    await asyncio.sleep(e.retry_after + 1)
            if TAG_DELAY and i < total:
                await asyncio.sleep(TAG_DELAY)
        await bot.send_message(chat_id, "✅ <b>전체 태그 완료!</b>", parse_mode=ParseMode.HTML)
    except asyncio.CancelledError:
        await bot.send_message(chat_id, "🛑 <b>전체 태그를 멈췄어요</b>", parse_mode=ParseMode.HTML)
        raise
    except (BadRequest, Forbidden) as e:
        log.warning("전체태그 실패 chat=%s: %s", chat_id, e)
    finally:
        TAGGING.pop(chat_id, None)


async def stop_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            "🔒 <b>방 관리자만</b> 멈출 수 있어요", parse_mode=ParseMode.HTML
        )
        return
    task = TAGGING.get(chat.id)
    if task and not task.done():
        task.cancel()
    else:
        await update.effective_message.reply_text(
            "💤 <i>지금 태그하는 중이 아니에요</i>", parse_mode=ParseMode.HTML
        )


async def show_escape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🔐 <b>방탈출</b>\n"
        "\n"
        "<blockquote>🗝️ <i>단서를 찾고, 문을 열고, 탈출하세요!</i></blockquote>\n"
        "\n"
        "👇 <i>아래 버튼을 눌러 입장</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚪 방탈출 하러 가기", url=ESCAPE_URL)]]),
    )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    title = f"🏠 <i>{escape(chat.title)}</i>\n" if chat.title else ""
    await update.effective_message.reply_text(
        "📈 <b>채팅 통계</b>\n"
        f"{title}"
        "\n"
        "<blockquote>📅 <b>기간별 순위</b> <i>— 달력에서 시작·끝 선택</i>\n"
        "📊 <b>일별 그래프</b> <i>— 메시지 수 · 참여 인원</i>\n"
        "🕐 <b>시간대 · 요일 분석</b>\n"
        "🧩 <b>메시지 종류</b> <i>— 사진 · 스티커 · 영상…</i>\n"
        "👤 <b>개인별 상세</b> <i>— 순위에서 이름을 눌러보세요</i></blockquote>\n"
        "\n"
        "👇 <i>아래 버튼으로 열어보세요</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([stats_button(context.bot, chat.id, "📊 통계 열기")]),
    )


def is_in(m) -> bool:
    return m.status in (
        ChatMember.OWNER, ChatMember.ADMINISTRATOR, ChatMember.MEMBER
    ) or (m.status == ChatMember.RESTRICTED and m.is_member)


def left_voluntarily(update: Update) -> bool:
    """방에 있던 사람이 '스스로' 나갔는지 판별 (관리자가 내보낸 경우는 제외)."""
    cm = update.chat_member
    old, new = cm.old_chat_member, cm.new_chat_member
    return (
        is_in(old)
        and not is_in(new)
        and new.status != ChatMember.BANNED
        and cm.from_user.id == new.user.id  # 본인이 직접 한 행동
    )


async def on_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cm = update.chat_member
    chat = update.effective_chat
    user = cm.new_chat_member.user
    if user.id == context.bot.id or user.is_bot:
        return

    was, now_in = is_in(cm.old_chat_member), is_in(cm.new_chat_member)
    if not was and now_in:
        kind = "join"
    elif was and not now_in:
        kind = "leave" if left_voluntarily(update) else "kick"
    else:
        return
    STORE.add_event(chat.id, user.id, user.full_name, user.username, kind, now())

    if kind == "leave":
        await ban_leaver(update, context)


async def ban_leaver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.chat_member.new_chat_member.user

    try:
        await context.bot.ban_chat_member(chat.id, user.id)  # until_date 없음 = 영구
        log.info("🚫 들낙 밴 chat=%s user=%s (%s)", chat.id, user.id, user.full_name)
    except (BadRequest, Forbidden) as e:
        log.warning("밴 실패 (차단 권한 확인) chat=%s user=%s: %s", chat.id, user.id, e)


async def delete_leave_notice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """'OOO님이 나갔습니다' 텔레그램 자동 메시지를 지움 (스스로 나간 경우만)."""
    msg = update.message
    left = msg.left_chat_member
    if msg.from_user is None or msg.from_user.id != left.id:
        return  # 관리자가 내보낸 경우는 그대로 둠
    try:
        await msg.delete()
    except (BadRequest, Forbidden) as e:
        log.warning("퇴장 메시지 삭제 실패 (삭제 권한 확인) chat=%s: %s", msg.chat_id, e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "👋 <b>안녕하세요! 하루 채팅 카운터예요</b>\n"
        "\n"
        "<blockquote>💬 이 방의 <b>오늘 채팅 개수</b>를 세고 있어요\n"
        "🌙 매일 <i>자정</i>에 0으로 초기화돼요</blockquote>\n"
        "\n"
        "👉 <b>/채팅</b> 내 오늘 채팅 개수 보기\n"
        "🏆 <b>/랭킹</b> 오늘 채팅 순위 보기\n"
        "📈 <b>/통계</b> 기간별 통계 미니앱\n"
        "📢 <b>/전체태그</b> 방 인원 전체 호출 <i>(관리자)</i>\n"
        "🔐 <b>/방탈출</b> 방탈출 하러 가기\n"
        "🚫 <i>들낙 방지: 스스로 나가면 자동 영구 차단</i>",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────── 실행 ───────────────────────────

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("chat", "내 오늘 채팅 개수 (/채팅)"),
        BotCommand("rank", "오늘 채팅 순위 (/랭킹)"),
        BotCommand("stats", "기간별 통계 미니앱 (/통계)"),
    ])
    if WEB_PORT:
        async def member_check(chat_id: int, user_id: int) -> bool:
            return is_in(await app.bot.get_chat_member(chat_id, user_id))

        server = StatsServer(STORE, TOKEN, TZ, member_check)
        try:
            app.bot_data["web_runner"] = await server.start(WEB_HOST, WEB_PORT)
        except OSError as e:
            # 포트가 이미 쓰이는 중이면 미니앱만 끄고 봇은 계속 동작
            log.error("❌ 미니앱 서버를 %s 포트에 띄우지 못했어요 (다른 프로그램이 사용 중?): %s "
                      "→ WEB_PORT 를 다른 번호로 바꿔주세요", WEB_PORT, e)


async def post_shutdown(app: Application) -> None:
    runner = app.bot_data.get("web_runner")
    if runner:
        await runner.cleanup()


def main() -> None:
    if not TOKEN:
        raise SystemExit("❌ BOT_TOKEN 환경변수를 설정해주세요.")

    if OLD_JSON.exists():
        moved = STORE.migrate_json(OLD_JSON, now())
        log.info("📦 예전 counts.json 에서 오늘 기록 %d명분을 옮겼어요", moved)

    app = (
        Application.builder().token(TOKEN)
        .post_init(post_init).post_shutdown(post_shutdown).build()
    )

    # /채팅 은 텔레그램 규격상 '명령어'로 인식되지 않으므로 정규식으로 받음
    chat_cmd = filters.Regex(r"^/채팅(@\w+)?(\s|$)")
    rank_cmd = filters.Regex(r"^/랭킹(@\w+)?(\s|$)")
    stats_cmd = filters.Regex(r"^/통계(@\w+)?(\s|$)")
    tag_cmd = filters.Regex(r"^/전체태그(@\w+)?(\s|$)")
    stop_cmd = filters.Regex(r"^/태그중지(@\w+)?(\s|$)")
    escape_cmd = filters.Regex(r"^/방탈출(@\w+)?(\s|$)")
    korean_cmd = chat_cmd | rank_cmd | stats_cmd | tag_cmd | stop_cmd | escape_cmd

    app.add_handler(CommandHandler(["chat", "count"], show_count))
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler(["rank", "ranking"], show_ranking))
    app.add_handler(MessageHandler(chat_cmd, show_count))
    app.add_handler(MessageHandler(rank_cmd, show_ranking))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(MessageHandler(stats_cmd, show_stats))
    app.add_handler(CommandHandler("escape", show_escape))
    app.add_handler(MessageHandler(escape_cmd, show_escape))
    app.add_handler(CommandHandler("all", tag_all))
    app.add_handler(MessageHandler(tag_cmd, tag_all))
    app.add_handler(CommandHandler("stopall", stop_tag))
    app.add_handler(MessageHandler(stop_cmd, stop_tag))
    app.add_handler(CallbackQueryHandler(ranking_page, pattern=r"^rank:\d+$"))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_leave_notice)
    )

    # 명령어를 제외한 모든 새 메시지(텍스트·사진·스티커·영상 등)를 카운트
    app.add_handler(
        MessageHandler(
            filters.UpdateType.MESSAGE & ~filters.COMMAND & ~korean_cmd
            & ~filters.StatusUpdate.ALL,
            count_message,
        ),
        group=1,
    )

    log.info("🤖 봇 시작! (시간대: %s, DB: %s)", TZ, DB_FILE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
