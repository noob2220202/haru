/* 📊 하루 채팅 통계 미니앱 */
(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  const $ = (s) => document.querySelector(s);
  const PAGE = 10;
  const WD = ["일", "월", "화", "수", "목", "금", "토"];
  const WD_MON = ["월", "화", "수", "목", "금", "토", "일"];
  const MEDAL = { 1: "🥇", 2: "🥈", 3: "🥉" };
  const KIND = {
    text: ["💬", "텍스트", "#3390ec"],
    photo: ["📷", "사진", "#f5a524"],
    video: ["🎬", "영상", "#e5484d"],
    sticker: ["🧸", "스티커", "#2fb36b"],
    gif: ["🎞️", "GIF", "#9b6ef3"],
    voice: ["🎤", "음성", "#14b3c7"],
    file: ["📎", "파일", "#ef6fa8"],
    etc: ["✨", "기타", "#8a9099"],
  };
  const PEER = [
    ["#ff885e", "#ff516a"], ["#ffcd6a", "#ffa85c"], ["#82b1ff", "#665fff"],
    ["#a0de7e", "#54cb68"], ["#53edd6", "#28c9b7"], ["#72d5fd", "#2a9ef1"], ["#e0a2f3", "#d669ed"],
  ];

  const S = {
    initData: (tg && tg.initData) || "",
    chat: null, today: null, firstDay: null, start: null, end: null,
    preset: "7d", data: null, page: 0, view: "main", user: null,
    charts: {}, cal: { month: null, s: null, e: null },
  };

  /* ─────────── 유틸 ─────────── */
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");
  const fmt1 = (n) => Number(n || 0).toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  const parse = (d) => { const [y, m, dd] = d.split("-").map(Number); return new Date(Date.UTC(y, m - 1, dd)); };
  const iso = (dt) => dt.toISOString().slice(0, 10);
  const add = (d, n) => { const t = parse(d); t.setUTCDate(t.getUTCDate() + n); return iso(t); };
  const diff = (a, b) => Math.round((parse(b) - parse(a)) / 864e5);
  const wd = (d) => WD[parse(d).getUTCDay()];
  const md = (d) => { const t = parse(d); return `${t.getUTCMonth() + 1}월 ${t.getUTCDate()}일`; };
  const dayLabel = (d) => {
    const t = parse(d);
    const y = S.today && t.getUTCFullYear() !== parse(S.today).getUTCFullYear() ? `${t.getUTCFullYear()}년 ` : "";
    return `${y}${md(d)} (${wd(d)})`;
  };
  const short = (d) => { const t = parse(d); return `${t.getUTCMonth() + 1}/${t.getUTCDate()}`; };
  const haptic = (k = "select") => { try { k === "select" ? tg.HapticFeedback.selectionChanged() : tg.HapticFeedback.impactOccurred(k); } catch (_) {} };

  const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();
  const _cv = document.createElement("canvas").getContext("2d");
  const alpha = (color, a) => {
    _cv.fillStyle = "#000"; _cv.fillStyle = color;
    const c = _cv.fillStyle;
    if (c.startsWith("#")) {
      const n = parseInt(c.slice(1), 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }
    return c.replace(/rgba?\(([^)]+)\)/, (_, p) => `rgba(${p.split(",").slice(0, 3).join(",")},${a})`);
  };

  const avatar = (el, id, name) => {
    const [a, b] = PEER[Math.abs(Number(id)) % 7];
    el.style.background = `linear-gradient(160deg, ${a}, ${b})`;
    el.textContent = [...String(name || "?").trim()][0] || "?";
  };
  const avatarHTML = (id, name, cls = "") => {
    const [a, b] = PEER[Math.abs(Number(id)) % 7];
    return `<div class="avatar ${cls}" style="background:linear-gradient(160deg,${a},${b})">${esc([...String(name || "?").trim()][0] || "?")}</div>`;
  };

  function ranks(list) {
    let prev = null, prevRank = 0;
    return list.map((u, i) => {
      const r = u.count === prev ? prevRank : i + 1;
      prev = u.count; prevRank = r;
      return { ...u, rank: r };
    });
  }

  /* ─────────── API ─────────── */
  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initData: S.initData, ...body }),
    });
    if (!res.ok) {
      const e = new Error(await res.text());
      e.status = res.status;
      throw e;
    }
    return res.json();
  }

  /* ─────────── 화면 전환 ─────────── */
  function showState(emoji, title, text) {
    $("#state").innerHTML = emoji
      ? `<div class="big">${emoji}</div><b>${esc(title)}</b><p>${esc(text || "")}</p>`
      : `<div class="spinner"></div><p>통계를 불러오는 중…</p>`;
    $("#state").classList.remove("hidden");
    ["#view-main", "#view-user", "#view-chats", "#period-bar"].forEach((s) => $(s).classList.add("hidden"));
  }
  function showView(v) {
    S.view = v;
    $("#state").classList.add("hidden");
    $("#view-main").classList.toggle("hidden", v !== "main");
    $("#view-user").classList.toggle("hidden", v !== "user");
    $("#view-chats").classList.toggle("hidden", v !== "chats");
    $("#period-bar").classList.toggle("hidden", v === "chats");
    try {
      if (v === "user" || (v === "main" && S.fromList)) tg.BackButton.show();
      else tg.BackButton.hide();
    } catch (_) {}
  }
  function fail(e) {
    if (e.status === 401) showState("🔐", "인증이 만료됐어요", "미니앱을 닫고 다시 열어주세요");
    else if (e.status === 403) showState("🙅", "이 방의 멤버만 볼 수 있어요", "방에 들어가 있는 계정으로 열어주세요");
    else showState("😵", "불러오지 못했어요", "잠시 후 다시 시도해주세요");
  }

  /* ─────────── 방 목록 ─────────── */
  async function loadChats() {
    try {
      const { chats } = await api("api/chats", {});
      const box = $("#chat-list");
      if (!chats.length) {
        box.innerHTML = `<div class="empty"><div>🔍</div>아직 볼 수 있는 방이 없어요<br><small>그룹에서 <b>/통계</b> 를 입력해 열어보세요</small></div>`;
      } else {
        box.innerHTML = chats.map((c) => `
          <button class="row" data-chat="${c.id}">
            ${avatarHTML(c.id, c.title)}
            <div class="row-main"><div class="row-name">${esc(c.title)}</div></div>
            <span class="chev">›</span>
          </button>`).join("");
        box.querySelectorAll("[data-chat]").forEach((b) => b.addEventListener("click", () => {
          haptic(); S.chat = Number(b.dataset.chat); S.fromList = true; S.data = null; load();
        }));
      }
      showView("chats");
    } catch (e) { fail(e); }
  }

  /* ─────────── 기간 ─────────── */
  function presetRange(p) {
    const T = S.today;
    if (p === "today") return [T, T];
    if (p === "yesterday") return [add(T, -1), add(T, -1)];
    if (p === "7d") return [add(T, -6), T];
    if (p === "30d") return [add(T, -29), T];
    if (p === "all") return [S.firstDay && S.firstDay < T ? S.firstDay : T, T];
    return [S.start, S.end];
  }
  function setPreset(p) {
    if (p === "custom") return openCal();
    haptic();
    S.preset = p;
    [S.start, S.end] = presetRange(p);
    S.page = 0;
    S.view === "user" ? loadUser(S.user) : load();
  }
  function prevLabel() {
    const days = diff(S.start, S.end) + 1;
    if (S.preset === "today") return "어제 대비";
    if (S.preset === "yesterday") return "그저께 대비";
    return days === 1 ? "전날 대비" : `이전 ${days}일 대비`;
  }
  function paintPeriod() {
    document.querySelectorAll("#chips button").forEach((b) => b.classList.toggle("on", b.dataset.p === S.preset));
    const days = diff(S.start, S.end) + 1;
    $("#range-label").innerHTML = S.start === S.end
      ? `<b>${dayLabel(S.start)}</b>`
      : `<b>${dayLabel(S.start)}</b> – <b>${dayLabel(S.end)}</b> · ${fmt(days)}일`;
  }

  /* ─────────── 차트 ─────────── */
  function baseOpts(extra = {}) {
    const hint = css("--hint"), sep = css("--sep");
    return {
      responsive: true, maintainAspectRatio: false, animation: { duration: 450 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(20,22,26,.92)", padding: 10, cornerRadius: 10,
          titleFont: { weight: "700" }, displayColors: false, ...extra.tooltip,
        },
      },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: hint, font: { size: 10.5 }, maxRotation: 0, autoSkipPadding: 8 } },
        y: { beginAtZero: true, grid: { color: sep }, border: { display: false }, ticks: { color: hint, font: { size: 10.5 }, precision: 0, maxTicksLimit: 5 } },
        ...extra.scales,
      },
    };
  }
  function chart(id, cfg) {
    if (S.charts[id]) S.charts[id].destroy();
    S.charts[id] = new Chart($("#" + id), cfg);
  }
  function dailyChart(id, daily, withUsers) {
    const acc = css("--accent"), hint = css("--hint");
    const ds = [{
      type: "bar", label: "메시지", data: daily.map((d) => d.count), yAxisID: "y",
      backgroundColor: alpha(acc, .85), hoverBackgroundColor: acc,
      borderRadius: daily.length > 40 ? 2 : 6, borderSkipped: false, maxBarThickness: 26, order: 2,
    }];
    if (withUsers) ds.push({
      type: "line", label: "참여 인원", data: daily.map((d) => d.users), yAxisID: "y1",
      borderColor: alpha(hint, .9), backgroundColor: hint, borderWidth: 2, tension: .35,
      pointRadius: daily.length > 31 ? 0 : 2.5, pointHoverRadius: 4, order: 1,
    });
    chart(id, {
      data: { labels: daily.map((d) => short(d.day)), datasets: ds },
      options: baseOpts({
        tooltip: {
          callbacks: {
            title: (it) => dayLabel(daily[it[0].dataIndex].day),
            label: (c) => c.dataset.yAxisID === "y" ? `💬 메시지 ${fmt(c.raw)}개` : `👥 참여 ${fmt(c.raw)}명`,
          },
        },
        scales: withUsers ? { y1: { display: false, beginAtZero: true, grid: { display: false } } } : {},
      }),
    });
  }
  function hourlyChart(id, hourly, peakEl) {
    const acc = css("--accent");
    const max = Math.max(...hourly);
    chart(id, {
      type: "bar",
      data: {
        labels: hourly.map((_, h) => h),
        datasets: [{
          data: hourly, borderRadius: 4, borderSkipped: false,
          backgroundColor: hourly.map((v) => (v === max && v > 0 ? acc : alpha(acc, .4))),
        }],
      },
      options: baseOpts({
        tooltip: { callbacks: { title: (it) => `🕐 ${it[0].dataIndex}시 ~ ${it[0].dataIndex + 1}시`, label: (c) => `💬 ${fmt(c.raw)}개` } },
        scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: css("--hint"), font: { size: 10 }, callback: (v) => (v % 3 === 0 ? `${v}시` : "") , autoSkip: false, maxRotation: 0 } } },
      }),
    });
    const peak = hourly.indexOf(max);
    $(peakEl).textContent = max > 0 ? `가장 활발 ${peak}시` : "";
  }
  function kindsBlock(chartId, listId, kinds) {
    const keys = Object.keys(KIND).filter((k) => kinds[k] > 0);
    const total = keys.reduce((a, k) => a + kinds[k], 0);
    const card = $("#" + listId);
    $("#" + chartId).parentElement.classList.toggle("hidden", !total);
    if (!total) {
      if (S.charts[chartId]) { S.charts[chartId].destroy(); delete S.charts[chartId]; }
      card.innerHTML = `<div class="muted small">아직 기록이 없어요</div>`;
      return;
    }
    keys.sort((a, b) => kinds[b] - kinds[a]);
    chart(chartId, {
      type: "doughnut",
      data: { labels: keys.map((k) => KIND[k][1]), datasets: [{ data: keys.map((k) => kinds[k]), backgroundColor: keys.map((k) => KIND[k][2]), borderWidth: 0, hoverOffset: 4 }] },
      options: {
        cutout: "68%", maintainAspectRatio: false, animation: { duration: 450 },
        plugins: { legend: { display: false }, tooltip: { backgroundColor: "rgba(20,22,26,.92)", cornerRadius: 10, callbacks: { label: (c) => ` ${fmt(c.raw)}개 (${fmt1((c.raw / total) * 100)}%)` } } },
      },
    });
    card.innerHTML = keys.map((k) => `
      <div class="kind"><span class="sw" style="background:${KIND[k][2]}"></span>
        <span class="nm">${KIND[k][0]} ${KIND[k][1]}</span><b>${fmt(kinds[k])}</b><small>${fmt1((kinds[k] / total) * 100)}%</small></div>`).join("");
  }

  /* ─────────── 방 전체 통계 ─────────── */
  async function load() {
    const first = !S.data;
    if (first) showState();
    else $("#view-main").classList.add("loading");
    try {
      const d = await api("api/stats", { chat: S.chat, start: S.start, end: S.end });
      S.data = d; S.today = d.today; S.firstDay = d.first_day;
      S.start = d.range.start; S.end = d.range.end;
      showView("main");
      renderMain();
      if (first) window.scrollTo(0, 0);
    } catch (e) { fail(e); }
    $("#view-main").classList.remove("loading");
  }

  function stat(label, val, sub, unit = "") {
    return `<div class="stat"><span class="lbl">${label}</span><span class="val">${val}${unit ? `<small>${unit}</small>` : ""}</span><span class="sub">${sub}</span></div>`;
  }
  function delta(cur, prev) {
    if (!prev) return cur ? `<span class="muted">이전 기록 없음</span>` : "-";
    const p = ((cur - prev) / prev) * 100;
    const cls = p > 0 ? "up" : p < 0 ? "down" : "";
    const arrow = p > 0 ? "▲" : p < 0 ? "▼" : "–";
    return `<span class="${cls}">${arrow} ${fmt1(Math.abs(p))}%</span> ${prevLabel()}`;
  }

  function renderMain() {
    const d = S.data, s = d.summary, days = d.range.days;
    paintPeriod();
    $("#chat-title").textContent = d.chat.title;
    avatar($("#chat-avatar"), d.chat.id, d.chat.title);

    const rk = ranks(d.ranking);
    const top = rk[0];
    const cards = [
      stat("💬 메시지", fmt(s.total), delta(s.total, s.prev_total), "개"),
      stat("👥 참여 인원", fmt(s.users), s.users ? `1인당 평균 ${fmt1(s.total / s.users)}개` : "아직 없음", "명"),
    ];
    if (days === 1) {
      cards.push(stat("⏰ 피크 시간", s.peak_hour ? `${s.peak_hour.hour}시` : "-", s.peak_hour ? `${fmt(s.peak_hour.count)}개` : "기록 없음"));
      cards.push(stat("👑 1등", top ? esc(top.name) : "-", top ? `${fmt(top.count)}개` : "기록 없음"));
    } else {
      cards.push(stat("📈 하루 평균", fmt1(s.avg), `${fmt(days)}일 기준`, "개"));
      cards.push(stat("🔥 최고의 날", s.peak_day ? `${short(s.peak_day.day)} <small>(${wd(s.peak_day.day)})</small>` : "-", s.peak_day ? `${fmt(s.peak_day.count)}개` : "기록 없음"));
    }
    $("#summary").innerHTML = cards.join("");

    $("#card-daily").classList.toggle("hidden", days === 1);
    if (days > 1) dailyChart("chart-daily", d.daily, true);
    hourlyChart("chart-hourly", d.hourly, "#peak-hour");

    $("#card-heat").classList.toggle("hidden", days === 1);
    if (days > 1) renderHeat(d.heatmap);

    renderRanking(rk, s.total);
    kindsBlock("chart-kinds", "kinds", d.kinds);

    const ev = d.events;
    $("#events").innerHTML = [
      ["🙋", "입장", ev.join], ["🚪", "퇴장·차단", ev.leave], ["👢", "강퇴", ev.kick],
    ].map(([e, l, n]) => `<div class="ev"><div class="e">${e}</div><b>${fmt(n)}</b><small>${l}</small></div>`).join("");

    const t = new Date();
    $("#foot").textContent = `⏱ ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")} 기준 · 기간 버튼을 다시 누르면 새로고침`;
  }

  function renderHeat(heat) {
    const acc = css("--accent");
    const max = Math.max(1, ...heat.flat());
    let h = `<span></span>`;
    for (let x = 0; x < 24; x++) h += `<span class="hl">${x % 6 === 0 ? x : ""}</span>`;
    heat.forEach((row, w) => {
      h += `<span class="dl">${WD_MON[w]}</span>`;
      row.forEach((v, x) => {
        const bg = v ? alpha(acc, 0.12 + 0.88 * (v / max)) : "";
        h += `<span class="c" data-w="${w}" data-h="${x}" data-v="${v}" ${bg ? `style="background:${bg}"` : ""}></span>`;
      });
    });
    const box = $("#heatmap");
    box.innerHTML = h;
    $("#heat-info").textContent = "칸을 눌러보세요";
    box.onclick = (e) => {
      const c = e.target.closest(".c");
      if (!c) return;
      haptic();
      box.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel"));
      c.classList.add("sel");
      $("#heat-info").textContent = `${WD_MON[c.dataset.w]}요일 ${c.dataset.h}시 · ${fmt(c.dataset.v)}개`;
    };
  }

  function rankRow(u, total, max, isMe) {
    const pct = total ? (u.count / total) * 100 : 0;
    const pos = MEDAL[u.rank] ? `<span class="pos medal">${MEDAL[u.rank]}</span>` : `<span class="pos">${u.rank}</span>`;
    return `
      <button class="row${isMe ? " me" : ""}" data-user="${u.id}">
        ${pos}${avatarHTML(u.id, u.name)}
        <div class="row-main">
          <div class="row-name">${esc(u.name)}${u.username ? `<span class="un">@${esc(u.username)}</span>` : ""}</div>
          <div class="bar"><i style="width:${max ? (u.count / max) * 100 : 0}%"></i></div>
        </div>
        <div class="num"><b>${fmt(u.count)}</b><small>${fmt1(pct)}%</small></div>
      </button>`;
  }

  function renderRanking(rk, total) {
    const pages = Math.max(1, Math.ceil(rk.length / PAGE));
    S.page = Math.min(S.page, pages - 1);
    const max = rk.length ? rk[0].count : 0;
    const me = rk.find((u) => u.id === S.data.me);
    $("#rank-count").textContent = rk.length ? `${fmt(rk.length)}명` : "";

    const pill = $("#me-pill");
    if (me) {
      pill.innerHTML = `<span>🙋 내 순위 <b>${me.rank}등</b> · ${fmt(me.count)}개</span><span>${fmt1(total ? (me.count / total) * 100 : 0)}% ›</span>`;
      pill.onclick = () => { haptic(); openUser(me.id); };
      pill.classList.remove("hidden");
    } else pill.classList.add("hidden");

    const list = $("#ranking");
    if (!rk.length) {
      list.innerHTML = `<div class="empty"><div>🦗</div>이 기간에는 채팅이 없어요</div>`;
      $("#pager").innerHTML = "";
      return;
    }
    list.innerHTML = rk.slice(S.page * PAGE, S.page * PAGE + PAGE).map((u) => rankRow(u, total, max, me && u.id === me.id)).join("");
    list.querySelectorAll("[data-user]").forEach((b) => b.addEventListener("click", () => { haptic(); openUser(Number(b.dataset.user)); }));

    if (pages > 1) {
      $("#pager").innerHTML = `<button id="pg-prev" ${S.page === 0 ? "disabled" : ""}>‹</button><span>${S.page + 1} / ${pages}</span><button id="pg-next" ${S.page >= pages - 1 ? "disabled" : ""}>›</button>`;
      const go = (n) => { haptic(); S.page += n; renderRanking(rk, total); };
      $("#pg-prev").onclick = () => go(-1);
      $("#pg-next").onclick = () => go(1);
    } else $("#pager").innerHTML = "";
  }

  /* ─────────── 개인 통계 ─────────── */
  function openUser(id) {
    S.user = id;
    S.mainScroll = window.scrollY;
    loadUser(id);
  }
  async function loadUser(id) {
    const v = $("#view-user");
    v.classList.add("loading");
    try {
      const d = await api("api/user", { chat: S.chat, user: id, start: S.start, end: S.end });
      if (S.view !== "user") { showView("user"); window.scrollTo(0, 0); }
      renderUser(d);
      paintPeriod();
    } catch (e) {
      if (e.status === 404) { try { tg.showAlert("이 사람의 기록이 없어요"); } catch (_) { alert("이 사람의 기록이 없어요"); } }
      else fail(e);
    }
    v.classList.remove("loading");
  }
  function renderUser(d) {
    const u = d.user, days = d.range.days;
    avatar($("#u-avatar"), u.id, u.name);
    $("#u-name").textContent = u.name;
    $("#u-username").textContent = u.username ? `@${u.username}` : "";
    $("#u-badge").textContent = d.rank ? `${MEDAL[d.rank] || "🏅"} ${d.rank}등 / ${fmt(d.of)}명` : "이 기간엔 채팅 없음";
    const cards = [
      stat("💬 메시지", fmt(d.count), `점유율 ${fmt1(d.share)}%`, "개"),
      stat("🏅 순위", d.rank ? fmt(d.rank) : "-", `${fmt(d.of)}명 중`, d.rank ? "등" : ""),
    ];
    if (days === 1) {
      cards.push(stat("⏰ 피크 시간", d.peak_hour ? `${d.peak_hour.hour}시` : "-", d.peak_hour ? `${fmt(d.peak_hour.count)}개` : "기록 없음"));
      cards.push(stat("📊 점유율", fmt1(d.share), "방 전체 메시지 중", "%"));
    } else {
      cards.push(stat("📅 활동일", fmt(d.active_days), `${fmt(days)}일 중 · 하루 평균 ${fmt1(d.avg)}개`, "일"));
      cards.push(stat("🔥 최고의 날", d.peak_day ? `${short(d.peak_day.day)} <small>(${wd(d.peak_day.day)})</small>` : "-", d.peak_day ? `${fmt(d.peak_day.count)}개` : "기록 없음"));
    }
    $("#u-summary").innerHTML = cards.join("");
    $("#u-card-daily").classList.toggle("hidden", days === 1);
    if (days > 1) dailyChart("u-chart-daily", d.daily, false);
    hourlyChart("u-chart-hourly", d.hourly, "#u-peak-hour");
    kindsBlock("u-chart-kinds", "u-kinds", d.kinds);
  }
  function back() {
    haptic();
    if (S.view === "user") {
      showView("main");
      // 개인 화면에서 기간을 바꿨다면 전체 통계도 그 기간으로 다시 불러옴
      if (S.data && (S.data.range.start !== S.start || S.data.range.end !== S.end)) load();
      window.scrollTo(0, S.mainScroll || 0);
    } else if (S.view === "main" && S.fromList) {
      showView("chats");
    }
  }

  /* ─────────── 달력 ─────────── */
  function openCal() {
    haptic();
    S.cal.s = S.start; S.cal.e = S.end;
    const t = parse(S.end || S.today);
    S.cal.month = `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}-01`;
    renderCal();
    $("#sheet").classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }
  function closeCal() {
    $("#sheet").classList.add("hidden");
    document.body.style.overflow = "";
  }
  function monthShift(m, n) { const t = parse(m); t.setUTCMonth(t.getUTCMonth() + n); return iso(t); }
  function renderCal() {
    const m = S.cal.month, t = parse(m);
    const y = t.getUTCFullYear(), mo = t.getUTCMonth();
    $("#cal-title").textContent = `${y}년 ${mo + 1}월`;
    $("#cal-next").disabled = monthShift(m, 1) > S.today;
    const startW = t.getUTCDay();
    const n = new Date(Date.UTC(y, mo + 1, 0)).getUTCDate();
    const { s, e } = S.cal;
    let h = "";
    for (let i = 0; i < startW; i++) h += `<span></span>`;
    for (let dd = 1; dd <= n; dd++) {
      const d = `${y}-${String(mo + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
      const cls = ["d"];
      if (d > S.today) cls.push("off");
      if (S.firstDay && d < S.firstDay) cls.push("nodata");
      if (d === S.today) cls.push("today");
      if (d === s) cls.push("s");
      if (d === e) cls.push("e");
      if (s && e && s !== e) { if (d === s) cls.push("has-e"); if (d > s && d < e) cls.push("in"); }
      const w = (startW + dd - 1) % 7;
      const color = w === 0 ? ' style="color:var(--down)"' : "";
      h += `<div class="${cls.join(" ")}" data-d="${d}"><span${cls.includes("s") || cls.includes("e") ? "" : color}>${dd}</span></div>`;
    }
    $("#cal-grid").innerHTML = h;
    $("#cal-s").textContent = s ? dayLabel(s) : "선택";
    $("#cal-e").textContent = e ? dayLabel(e) : "선택";
    $("#cal-box-s").classList.toggle("focus", !s || !!e);
    $("#cal-box-e").classList.toggle("focus", !!s && !e);
    const btn = $("#cal-apply");
    btn.disabled = !s;
    btn.textContent = !s ? "시작일을 눌러주세요" : `이 기간 보기 · ${fmt(diff(s, e || s) + 1)}일`;
  }
  function pickDay(d) {
    haptic();
    const c = S.cal;
    if (!c.s || c.e) { c.s = d; c.e = null; }
    else if (d < c.s) { c.e = c.s; c.s = d; }
    else c.e = d;
    renderCal();
  }
  function quick(q) {
    haptic();
    const T = S.today, t = parse(T);
    const y = t.getUTCFullYear(), mo = t.getUTCMonth();
    const monday = add(T, -((t.getUTCDay() + 6) % 7));
    let s, e;
    if (q === "this-month") { s = iso(new Date(Date.UTC(y, mo, 1))); e = T; }
    if (q === "last-month") { s = iso(new Date(Date.UTC(y, mo - 1, 1))); e = iso(new Date(Date.UTC(y, mo, 0))); }
    if (q === "this-week") { s = monday; e = T; }
    if (q === "last-week") { s = add(monday, -7); e = add(monday, -1); }
    S.cal.s = s; S.cal.e = e;
    S.cal.month = s.slice(0, 8) + "01";
    renderCal();
  }
  function applyCal() {
    haptic("light");
    S.start = S.cal.s; S.end = S.cal.e || S.cal.s;
    // 고른 기간이 프리셋과 같으면 그 칩을 켜줌
    S.preset = "custom";
    for (const p of ["today", "yesterday", "7d", "30d"]) {
      const [a, b] = presetRange(p);
      if (a === S.start && b === S.end) S.preset = p;
    }
    S.page = 0;
    closeCal();
    S.view === "user" ? loadUser(S.user) : load();
  }

  /* ─────────── 시작 ─────────── */
  function bind() {
    $("#chips").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) setPreset(b.dataset.p);
    });
    $("#back").onclick = back;
    $("#sheet-backdrop").onclick = closeCal;
    $("#cal-prev").onclick = () => { haptic(); S.cal.month = monthShift(S.cal.month, -1); renderCal(); };
    $("#cal-next").onclick = () => { haptic(); S.cal.month = monthShift(S.cal.month, 1); renderCal(); };
    $("#cal-grid").addEventListener("click", (e) => { const d = e.target.closest(".d"); if (d) pickDay(d.dataset.d); });
    document.querySelector(".cal-quick").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) quick(b.dataset.q); });
    $("#cal-apply").onclick = applyCal;
    const bar = $("#period-bar");
    addEventListener("scroll", () => bar.classList.toggle("stuck", scrollY > 60), { passive: true });
    try { tg.BackButton.onClick(back); } catch (_) {}
  }

  function init() {
    if (tg) {
      tg.ready();
      tg.expand();
      try { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); } catch (_) {}
      try { tg.disableVerticalSwipes(); } catch (_) {}
    }
    if (window.Chart) {
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
      Chart.defaults.color = css("--hint");
    }
    bind();
    if (!S.initData) return showState("📱", "텔레그램에서 열어주세요", "그룹에서 /통계 를 입력하면 열 수 있어요");

    const param = (tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";
    const m = /^c(\d+)$/.exec(param);
    if (m) { S.chat = -Number(m[1]); load(); }
    else loadChats();
  }

  init();
})();
