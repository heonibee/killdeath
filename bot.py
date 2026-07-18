"""
솔 인챈트 보스 컷/멍 + 참석 체크 봇 (킬데스길드)
- 정시 타임(03·09·12·21·24시) 10분 전에 자동으로 그 타임 보스 표시
  (그 시각 정시 젠 보스 + 처치 후 12/24시간 보스는 매 타임 항상 포함)
- 참석: ✅ 이모지 → 명단·인원 실시간 갱신
- 컷/멍: 보스별 [🟢컷]/[🔴멍] 버튼(이름 표시), 누르면 시각+누른사람 기록
- 이전 타임 메시지는 남김 / 로그 계속 저장(data.json)
언어: 한국어 / discord.py 2.x
"""

import os
import json
import datetime as dt
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from bosses import (BOSSES, RESET_HOURS, boss_names, find_boss, tag_of,
                    bosses_for_hour)

KST = ZoneInfo("Asia/Seoul")
DATA_FILE = "data.json"
TOKEN = os.environ.get("DISCORD_TOKEN")
GROUP_SIZE = 5          # 버튼 메시지당 보스 수 (5마리=버튼10개=5줄)
CHECK_EMOJI = "✅"
PRE_MIN = 10            # 젠 몇 분 전에 자동 표시

# status: {보스명: {state,time,user}}  (현재 타임)
# posts:  {메시지ID(str): {"channel_id":int,"bosses":[이름...]}}   (컷/멍 버튼 메시지)
# attend: {메시지ID(str): {"channel_id":int,"hour":int,"users":{uid(str):이름}}}
# auto_channel: 자동 표시 채널 ID
data = {"status": {}, "slot": None, "log": [],
        "posts": {}, "attend": {}, "auto_channel": None, "last_auto": None}


def load_data():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    for k, v in {"status": {}, "slot": None, "log": [], "posts": {},
                 "attend": {}, "auto_channel": None, "last_auto": None}.items():
        data.setdefault(k, v)


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save error:", e)


def now_kst():
    return dt.datetime.now(KST)


def slot_start(now):
    hrs = sorted(RESET_HOURS)
    cands = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hrs]
    past = [c for c in cands if c <= now]
    if past:
        return max(past)
    y = now - dt.timedelta(days=1)
    return y.replace(hour=max(hrs), minute=0, second=0, microsecond=0)


def hour_label(h):
    return f"{24 if h == 0 else h}시"


# ---- 상태/임베드 ----
def status_line(b):
    st = data["status"].get(b["name"])
    tag = tag_of(b)
    tagtxt = f" `{tag}`" if tag else ""
    head = f"`{b['map']}` **{b['name']}**{tagtxt}"
    if not st:
        return f"⬜ {head} — 대기"
    t = dt.datetime.fromisoformat(st["time"]).astimezone(KST).strftime("%H:%M")
    emo = {"컷": "⚔️", "뜸": "🟢", "멍": "🔴"}.get(st["state"], "⬜")
    return f"{emo} {head} — {st['state']} ({t}, {st['user']})"


def button_embed(bosses, part=None, total=None):
    ttl = "🗡️ 보스 컷/멍"
    if part:
        ttl += f" ({part}/{total})"
    e = discord.Embed(
        title=ttl,
        description="\n".join(status_line(b) for b in bosses),
        color=0x2F5496,
    )
    e.set_footer(text="⚔️컷 🟢뜸 🔴멍 · 리셋은 타임 표시 때")
    return e


def attend_embed(hour, users):
    names = list(users.values())
    e = discord.Embed(
        title=f"📣 {hour_label(hour)} 보스레이드 · 참석 체크",
        description=f"참석하실 분은 이 메시지에 {CHECK_EMOJI} 를 눌러주세요.",
        color=0xE0A743,
    )
    lst = ", ".join(names) if names else "(아직 없음)"
    if len(lst) > 1000:
        lst = lst[:997] + "…"
    e.add_field(name=f"참석 {len(names)}명", value=lst, inline=False)
    return e


def record(boss_name, action, user):
    now = now_kst()
    data["status"][boss_name] = {"state": action, "time": now.isoformat(), "user": user}
    data["log"].append({"ts": now.isoformat(), "boss": boss_name,
                        "action": action, "user": user, "slot": data["slot"]})
    if len(data["log"]) > 5000:
        data["log"] = data["log"][-5000:]
    save_data()


# ---- 컷/뜸/멍 버튼 ----
# ⚔️ 컷(잡음) / 🟢 뜸(떠있음) / 🔴 멍(안뜸)
ACTIONS = [
    ("컷", "⚔️", discord.ButtonStyle.secondary),
    ("뜸", "🟢", discord.ButtonStyle.success),
    ("멍", "🔴", discord.ButtonStyle.danger),
]
ACODE = {"컷": "c", "뜸": "s", "멍": "m"}
ACODE_REV = {v: k for k, v in ACODE.items()}


class BossButton(discord.ui.Button):
    def __init__(self, boss_name, action, emoji, style, row, show_name):
        super().__init__(
            style=style,
            label=(f"{emoji} {boss_name}" if show_name else emoji),
            custom_id=f"{ACODE[action]}|{boss_name}",
            row=row,
        )
        self.boss_name = boss_name
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        record(self.boss_name, self.action, interaction.user.display_name)
        post = data["posts"].get(str(interaction.message.id))
        names = post["bosses"] if post else [self.boss_name]
        bosses = [find_boss(n) for n in names if find_boss(n)]
        await interaction.response.edit_message(
            embed=button_embed(bosses), view=make_button_view(names))


def _add_boss_row(view, name, row):
    for i, (action, emoji, style) in enumerate(ACTIONS):
        view.add_item(BossButton(name, action, emoji, style, row=row, show_name=(i == 0)))


def make_button_view(names):
    v = discord.ui.View(timeout=None)
    for i, n in enumerate(names[:GROUP_SIZE]):
        _add_boss_row(v, n, row=i)
    return v


def _all_boss_chunks():
    """영구 뷰 등록용: 전체 보스를 8마리(24버튼)씩 나눠 등록."""
    names = boss_names()
    return [names[i:i + 8] for i in range(0, len(names), 8)]


class RegistryView(discord.ui.View):
    """재시작 후 버튼 라우팅용 영구 뷰 (custom_id별 1회 등록). 자동 배치."""
    def __init__(self, names):
        super().__init__(timeout=None)
        for n in names:
            for i, (action, emoji, style) in enumerate(ACTIONS):
                self.add_item(BossButton(n, action, emoji, style, row=None, show_name=(i == 0)))


# ---- 현황 갱신 ----
async def refresh_post(client, message_id):
    post = data["posts"].get(str(message_id))
    if not post:
        return
    try:
        ch = client.get_channel(post["channel_id"]) or await client.fetch_channel(post["channel_id"])
        msg = await ch.fetch_message(int(message_id))
        bosses = [find_boss(n) for n in post["bosses"] if find_boss(n)]
        await msg.edit(embed=button_embed(bosses), view=make_button_view(post["bosses"]))
    except Exception as e:
        print("refresh_post error:", e)


async def refresh_posts_with_boss(client, boss_name):
    for mid, post in list(data["posts"].items()):
        if boss_name in post["bosses"]:
            await refresh_post(client, mid)


# ---- 타임 자동 표시 ----
def upcoming_slot_start(hour, now):
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=1)
    return t


async def post_timeslot(channel, hour):
    # 새 타임 표시 시 컷/멍 초기화 (이전 체크가 딸려오지 않게) — 로그는 보존
    data["status"] = {}
    data["slot"] = upcoming_slot_start(hour, now_kst()).isoformat()
    save_data()
    bosses = bosses_for_hour(hour)
    # 1) 참석 메시지
    am = await channel.send(embed=attend_embed(hour, {}))
    try:
        await am.add_reaction(CHECK_EMOJI)
    except Exception:
        pass
    data["attend"][str(am.id)] = {"channel_id": channel.id, "hour": hour, "users": {}}
    # 2) 컷/멍 버튼 메시지 (5마리씩)
    chunks = [bosses[i:i + GROUP_SIZE] for i in range(0, len(bosses), GROUP_SIZE)]
    for idx, ch in enumerate(chunks, 1):
        names = [b["name"] for b in ch]
        m = await channel.send(embed=button_embed(ch, idx, len(chunks)),
                               view=make_button_view(names))
        data["posts"][str(m.id)] = {"channel_id": channel.id, "bosses": names}
    save_data()


# ---- 봇 ----
class BossBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()  # 반응(이모지)·길드 포함, 특권 인텐트 불필요
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        for chunk in _all_boss_chunks():
            self.add_view(RegistryView(chunk))
        await self.tree.sync()
        self.scheduler.start()

    async def on_ready(self):
        if not data.get("slot"):
            data["slot"] = slot_start(now_kst()).isoformat()
            save_data()
        print(f"로그인: {self.user} | 현재 타임: {data['slot']}")

    @tasks.loop(seconds=20)
    async def scheduler(self):
        now = now_kst()
        # 젠 10분 전 자동 표시 (컷/멍 초기화는 post_timeslot 안에서 처리)
        if data.get("auto_channel"):
            for h in RESET_HOURS:
                pre = (now.replace(hour=h, minute=0, second=0, microsecond=0)
                       - dt.timedelta(minutes=PRE_MIN))
                if now.hour == pre.hour and now.minute == pre.minute:
                    key = f"{now.date()}-{h}"
                    if data.get("last_auto") != key:
                        data["last_auto"] = key
                        save_data()
                        try:
                            ch = self.get_channel(data["auto_channel"]) or \
                                 await self.fetch_channel(data["auto_channel"])
                            await post_timeslot(ch, h)
                            print("자동 표시:", key)
                        except Exception as e:
                            print("auto post error:", e)

    @scheduler.before_loop
    async def before(self):
        await self.wait_until_ready()

    # ---- 참석 이모지 ----
    async def on_raw_reaction_add(self, payload):
        if str(payload.emoji) != CHECK_EMOJI:
            return
        entry = data["attend"].get(str(payload.message_id))
        if not entry or payload.user_id == self.user.id:
            return
        name = payload.member.display_name if payload.member else str(payload.user_id)
        entry["users"][str(payload.user_id)] = name
        save_data()
        await self._update_attend(payload.channel_id, payload.message_id, entry)

    async def on_raw_reaction_remove(self, payload):
        if str(payload.emoji) != CHECK_EMOJI:
            return
        entry = data["attend"].get(str(payload.message_id))
        if not entry:
            return
        entry["users"].pop(str(payload.user_id), None)
        save_data()
        await self._update_attend(payload.channel_id, payload.message_id, entry)

    async def _update_attend(self, channel_id, message_id, entry):
        try:
            ch = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            msg = await ch.fetch_message(message_id)
            await msg.edit(embed=attend_embed(entry["hour"], entry["users"]))
        except Exception as e:
            print("attend update error:", e)


client = BossBot()


async def boss_autocomplete(interaction, current):
    cur = current.replace(" ", "")
    out = []
    for n in boss_names():
        if cur == "" or cur in n.replace(" ", ""):
            out.append(app_commands.Choice(name=n, value=n))
        if len(out) >= 25:
            break
    return out


@client.tree.command(name="채널설정", description="이 채널을 보스 자동 표시 채널로 등록합니다.")
async def cmd_setch(interaction: discord.Interaction):
    data["auto_channel"] = interaction.channel.id
    save_data()
    await interaction.response.send_message(
        "✅ 이 채널을 자동 표시 채널로 등록했어요. 정시 10분 전에 보스 목록이 올라옵니다.", ephemeral=True)


@client.tree.command(name="지금표시", description="현재(또는 다음) 타임 보스를 지금 바로 표시합니다.")
@app_commands.describe(시="표시할 타임(03/09/12/21/24). 비우면 현재 타임")
async def cmd_now(interaction: discord.Interaction, 시: int = None):
    if 시 is None:
        시 = slot_start(now_kst()).hour
    h = 0 if 시 == 24 else 시
    if h not in RESET_HOURS:
        await interaction.response.send_message("타임은 03/09/12/21/24 중 하나예요.", ephemeral=True)
        return
    await interaction.response.send_message(f"{hour_label(h)} 타임을 표시할게요.", ephemeral=True)
    await post_timeslot(interaction.channel, h)


async def _do_record(interaction, 보스, action, emoji):
    if not find_boss(보스):
        await interaction.response.send_message("그런 보스가 없어요.", ephemeral=True)
        return
    record(보스, action, interaction.user.display_name)
    await interaction.response.send_message(
        f"{emoji} **{보스}** {action} ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})",
        ephemeral=True)
    await refresh_posts_with_boss(interaction.client, 보스)


@client.tree.command(name="컷", description="보스 컷(잡음) 기록")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_cut(interaction: discord.Interaction, 보스: str):
    await _do_record(interaction, 보스, "컷", "⚔️")


@client.tree.command(name="뜸", description="보스 뜸(떠 있음, 아직 안 잡음) 기록")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_spawn(interaction: discord.Interaction, 보스: str):
    await _do_record(interaction, 보스, "뜸", "🟢")


@client.tree.command(name="멍", description="보스 멍(안 뜸) 기록")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_mung(interaction: discord.Interaction, 보스: str):
    await _do_record(interaction, 보스, "멍", "🔴")


@client.tree.command(name="로그", description="최근 컷/멍 기록")
@app_commands.describe(보스="(선택) 특정 보스만")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_log(interaction: discord.Interaction, 보스: str = None):
    logs = data["log"]
    if 보스:
        logs = [l for l in logs if l["boss"] == 보스]
    logs = logs[-15:][::-1]
    if not logs:
        await interaction.response.send_message("기록이 없어요.", ephemeral=True)
        return
    lines = []
    for l in logs:
        t = dt.datetime.fromisoformat(l["ts"]).astimezone(KST).strftime("%m/%d %H:%M")
        emo = {"컷": "⚔️", "뜸": "🟢", "멍": "🔴"}.get(l["action"], "⬜")
        lines.append(f"{emo} {t}  {l['boss']}  {l['action']} — {l['user']}")
    await interaction.response.send_message("```\n" + "\n".join(lines) + "\n```", ephemeral=True)


@client.tree.command(name="리셋", description="현재 타임 컷/멍 수동 초기화")
async def cmd_reset(interaction: discord.Interaction):
    data["status"] = {}
    save_data()
    await interaction.response.send_message("현재 타임 컷/멍을 초기화했어요. (로그 유지)", ephemeral=True)
    for mid in list(data["posts"].keys()):
        await refresh_post(interaction.client, mid)


def main():
    load_data()
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_TOKEN 이 필요합니다.")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
