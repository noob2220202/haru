"""
🌐 미니앱 웹서버 (aiohttp)
- web/ 폴더의 화면 파일과 통계 API 를 제공합니다.
- 텔레그램이 서명한 initData 로 사용자를 확인하고,
  그 사람이 실제로 그 방의 멤버인지 확인한 뒤에만 통계를 보여줍니다.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qsl

from aiohttp import web

from storage import Store

log = logging.getLogger("haru.web")

WEB_DIR = Path(__file__).parent / "web"
MAX_DAYS = 1100          # 한 번에 조회할 수 있는 최대 기간
INIT_DATA_MAX_AGE = 86400  # initData 유효시간(초)
MEMBER_CACHE_SEC = 300

# (chat_id, user_id) -> bool
MemberCheck = Callable[[int, int], Awaitable[bool]]


def verify_init_data(init_data: str, token: str) -> dict | None:
    """텔레그램 미니앱 initData 서명 검증. 성공하면 내용 dict, 실패하면 None."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = data.pop("hash", None)
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        if time.time() - int(data.get("auth_date", 0)) > INIT_DATA_MAX_AGE:
            return None
        data["user"] = json.loads(data["user"])
    except (KeyError, ValueError):
        return None
    return data


class StatsServer:
    def __init__(self, store: Store, token: str, tz, is_member: MemberCheck):
        self.store = store
        self.token = token
        self.tz = tz
        self._is_member = is_member
        self._member_cache: dict[tuple[int, int], tuple[bool, float]] = {}

    # ─────────────── 공통 ───────────────

    def today(self) -> date:
        return datetime.now(self.tz).date()

    async def is_member(self, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        hit = self._member_cache.get(key)
        if hit and time.time() - hit[1] < MEMBER_CACHE_SEC:
            return hit[0]
        try:
            ok = await self._is_member(chat_id, user_id)
        except Exception as e:  # 봇이 방에서 나갔거나 네트워크 오류
            log.warning("멤버 확인 실패 chat=%s user=%s: %s", chat_id, user_id, e)
            ok = False
        self._member_cache[key] = (ok, time.time())
        return ok

    async def _auth(self, request: web.Request) -> tuple[dict, dict]:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text="bad json")
        init = verify_init_data(str(body.get("initData", "")), self.token)
        if init is None:
            raise web.HTTPUnauthorized(text="텔레그램에서 다시 열어주세요")
        return body, init

    async def _chat(self, body: dict, init: dict) -> int:
        try:
            chat_id = int(body["chat"])
        except (KeyError, TypeError, ValueError):
            raise web.HTTPBadRequest(text="bad chat")
        if not await self.is_member(chat_id, init["user"]["id"]):
            raise web.HTTPForbidden(text="이 방의 멤버만 볼 수 있어요")
        return chat_id

    def _range(self, body: dict, chat_id: int) -> tuple[date, date]:
        today = self.today()
        try:
            end = date.fromisoformat(body["end"]) if body.get("end") else today
            start = date.fromisoformat(body["start"]) if body.get("start") else end - timedelta(6)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="bad date")
        if start > end:
            start, end = end, start
        end = min(end, today)
        start = min(start, end)
        if (end - start).days + 1 > MAX_DAYS:
            start = end - timedelta(MAX_DAYS - 1)
        return start, end

    # ─────────────── API ───────────────

    async def api_chats(self, request: web.Request) -> web.Response:
        _, init = await self._auth(request)
        uid = init["user"]["id"]
        chats = [c for c in self.store.user_chats(uid) if await self.is_member(c["id"], uid)]
        return web.json_response({"chats": chats})

    async def api_stats(self, request: web.Request) -> web.Response:
        body, init = await self._auth(request)
        chat_id = await self._chat(body, init)
        start, end = self._range(body, chat_id)
        data = self.store.range_stats(chat_id, start, end)
        data.update(
            chat={"id": chat_id, "title": self.store.chat_title(chat_id) or "채팅방"},
            today=self.today().isoformat(),
            first_day=self.store.first_day(chat_id),
            me=init["user"]["id"],
        )
        return web.json_response(data)

    async def api_user(self, request: web.Request) -> web.Response:
        body, init = await self._auth(request)
        chat_id = await self._chat(body, init)
        start, end = self._range(body, chat_id)
        try:
            uid = int(body["user"])
        except (KeyError, TypeError, ValueError):
            raise web.HTTPBadRequest(text="bad user")
        data = self.store.user_stats(chat_id, uid, start, end)
        if data is None:
            raise web.HTTPNotFound(text="기록이 없는 사람이에요")
        return web.json_response(data)

    # ─────────────── 서버 ───────────────

    def make_app(self) -> web.Application:
        @web.middleware
        async def no_cache(request, handler):
            resp = await handler(request)
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        async def index(_):
            return web.FileResponse(WEB_DIR / "index.html")

        app = web.Application(middlewares=[no_cache])
        app.router.add_get("/", index)
        app.router.add_static("/assets", WEB_DIR / "assets")
        app.router.add_post("/api/chats", self.api_chats)
        app.router.add_post("/api/stats", self.api_stats)
        app.router.add_post("/api/user", self.api_user)
        return app

    async def start(self, host: str, port: int) -> web.AppRunner:
        runner = web.AppRunner(self.make_app(), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        log.info("🌐 미니앱 서버 시작: http://%s:%s", host, port)
        return runner
