"""
솔 인챈트 보스 컷/멍 체크 봇 (킬데스길드)
- 보스별 컷/멍 기록 (누른 시각 + 누른 사람)
- 실시간 현황판 (컷/멍 누르면 자동 갱신)
- 00·03·09·12·21시 자동 리셋 (새 타임 시작)
- 로그 계속 저장 (data.json)
언어: 한국어 / discord.py 2.x
"""

import os
import json
import datetime as dt
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from bosses import BOSSES, RESET_HOURS, boss_names, find_boss, tag_of

# ---- 설정 ----
KST = ZoneInfo("Asia/Seoul")
DATA_FILE = "data.json"
TOKEN = os.environ.get("DISCORD_TOKEN")  # 토큰은 환경변수로 (코드에 직접 X)

# ---- 저장 데이터 ----
# status: { 보스명: {"state": "컷"/"멍", "time": iso, "user": "닉네임"} }  (이번 타임)
# board:  {"channel_id": int, "message_id": int}
# slot:   현재 타임 시작 ISO 문자열
# log:    [ {"ts": iso, "boss":..., "action":..., "user":..., "slot":...}, ... ]
data = {"status": {}, "board": None, "slot": None, "log": []}


def load_data():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    for k, v in {"status": {}, "board": None, "slot": None, "log": []}.items():
        data.setdefault(k, v)


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save error:", e)


# ---- 타임(슬롯) 계산 ----
def slot_start(now: dt.datetime) -> dt.datetime:
    """now가 속한 현재 타임의 시작 시각을 반환 (00·03·09·12·21 기준)."""
    today_hours = sorted(RESET_HOURS)
    candidates = []
    for h in today_hours:
        candidates.append(now.replace(hour=h, minute=0, second=0, microsecond=0))
    # 오늘 것 중 now 이하인 가장 늦은 것
    past = [c for c in candidates if c <= now]
    if past:
        return max(past)
    # 오늘 리셋 전이면 어제 마지막(21시)
    y = now - dt.timedelta(days=1)
    return y.replace(hour=max(today_hours), minute=0, second=0, microsecond=0)


def slot_label(start: dt.datetime) -> str:
    return start.strftime("%m/%d %H시 타임")


def now_kst():
    return dt.datetime.now(KST)


# ---- 현황판 임베드 ----
def status_line(b):
    st = data["status"].get(b["name"])
    tag = tag_of(b)
    tagtxt = f" `{tag}`" if tag else ""
    head = f"`{b['map']}` **{b['name']}**{tagtxt}"
    if not st:
        return f"⬜ {head} — 대기"
    t = dt.datetime.fromisoformat(st["time"]).astimezone(KST).strftime("%H:%M")
    if st["state"] == "컷":
        return f"🟢 {head} — 컷 ({t}, {st['user']})"
    else:
        return f"🔴 {head} — 멍 ({t}, {st['user']})"


def build_embed():
    start = dt.datetime.fromisoformat(data["slot"]) if data["slot"] else now_kst()
    e = discord.Embed(
        title="🗡️ 킬데스길드 보스 현황판",
        description=f"**{slot_label(start.astimezone(KST))}**  ·  컷/멍은 아래 메뉴에서 보스를 선택해 누르세요.",
        color=0x2F5496,
    )
    # 두 그룹으로 나눠 표시
    timed = [b for b in BOSSES if not b.get("manual")]
    manual = [b for b in BOSSES if b.get("manual")]
    # 길이 제한(임베드 필드 1024자) 대비, 청크로 나눔
    def chunk_field(title, bosses):
        lines, buf = [], ""
        idx = 1
        for b in bosses:
            ln = status_line(b) + "\n"
            if len(buf) + len(ln) > 1000:
                e.add_field(name=f"{title} ({idx})", value=buf, inline=False)
                buf = ""
                idx += 1
            buf += ln
        if buf:
            nm = title if idx == 1 else f"{title} ({idx})"
            e.add_field(name=nm, value=buf, inline=False)
    chunk_field("정시 젠", timed)
    chunk_field("확인요망 (12/24시간 등)", manual)
    done = sum(1 for b in BOSSES if data["status"].get(b["name"]))
    e.set_footer(text=f"기록됨 {done}/{len(BOSSES)}  ·  리셋: 00·03·09·12·21시  ·  /로그 로 기록 확인")
    return e


# ---- 컷/멍 기록 ----
def record(boss_name, action, user):
    now = now_kst()
    data["status"][boss_name] = {"state": action, "time": now.isoformat(), "user": user}
    data["log"].append({
        "ts": now.isoformat(),
        "boss": boss_name,
        "action": action,
        "user": user,
        "slot": data["slot"],
    })
    # 로그 과다 방지 (최근 5000개 유지)
    if len(data["log"]) > 5000:
        data["log"] = data["log"][-5000:]
    save_data()


# ---- UI: 보스 선택 → 컷/멍 버튼 ----
class CutMungView(discord.ui.View):
    """보스 하나에 대한 컷/멍 버튼 (임시, ephemeral)"""
    def __init__(self, boss_name):
        super().__init__(timeout=60)
        self.boss_name = boss_name

    @discord.ui.button(label="🟢 컷 (잡음)", style=discord.ButtonStyle.success)
    async def cut(self, interaction: discord.Interaction, button: discord.ui.Button):
        record(self.boss_name, "컷", interaction.user.display_name)
        await refresh_board(interaction.client)
        await interaction.response.edit_message(
            content=f"✅ **{self.boss_name}** 컷 기록됨 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})",
            view=None,
        )

    @discord.ui.button(label="🔴 멍 (안 뜸)", style=discord.ButtonStyle.danger)
    async def mung(self, interaction: discord.Interaction, button: discord.ui.Button):
        record(self.boss_name, "멍", interaction.user.display_name)
        await refresh_board(interaction.client)
        await interaction.response.edit_message(
            content=f"✅ **{self.boss_name}** 멍 기록됨 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})",
            view=None,
        )

    @discord.ui.button(label="↩ 취소(대기로)", style=discord.ButtonStyle.secondary)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        data["status"].pop(self.boss_name, None)
        save_data()
        await refresh_board(interaction.client)
        await interaction.response.edit_message(
            content=f"↩ **{self.boss_name}** 대기 상태로 되돌림", view=None
        )


class BossSelect(discord.ui.Select):
    def __init__(self, bosses, placeholder, custom_id):
        options = [
            discord.SelectOption(
                label=b["name"],
                value=b["name"],
                description=f"{b['map']}. {b['loc']}" + (f" · {tag_of(b)}" if tag_of(b) else ""),
            )
            for b in bosses[:25]
        ]
        super().__init__(placeholder=placeholder, options=options, custom_id=custom_id, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        boss = self.values[0]
        await interaction.response.send_message(
            content=f"**{boss}** — 어떻게 기록할까요?",
            view=CutMungView(boss),
            ephemeral=True,
        )


class BoardView(discord.ui.View):
    """현황판에 붙는 영구 뷰 (보스 선택 메뉴)"""
    def __init__(self):
        super().__init__(timeout=None)
        timed = [b for b in BOSSES if not b.get("manual")]
        manual = [b for b in BOSSES if b.get("manual")]
        self.add_item(BossSelect(timed, "정시 젠 보스 선택…", "sel_timed"))
        if manual:
            self.add_item(BossSelect(manual, "확인요망 보스 선택…", "sel_manual"))


# ---- 현황판 갱신 ----
async def refresh_board(client):
    b = data.get("board")
    if not b:
        return
    try:
        ch = client.get_channel(b["channel_id"]) or await client.fetch_channel(b["channel_id"])
        msg = await ch.fetch_message(b["message_id"])
        await msg.edit(embed=build_embed(), view=BoardView())
    except Exception as e:
        print("board refresh error:", e)


# ---- 봇 본체 ----
class BossBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(BoardView())  # 영구 뷰 등록 (재시작 후에도 메뉴 작동)
        await self.tree.sync()
        self.reset_checker.start()

    async def on_ready(self):
        # 시작 시 현재 슬롯 확정
        cur = slot_start(now_kst()).isoformat()
        if data.get("slot") != cur:
            data["slot"] = cur
            data["status"] = {}
            save_data()
        print(f"로그인: {self.user} | 현재 타임: {data['slot']}")

    @tasks.loop(seconds=20)
    async def reset_checker(self):
        """타임 경계를 넘으면 현황판 리셋."""
        cur = slot_start(now_kst()).isoformat()
        if data.get("slot") != cur:
            data["slot"] = cur
            data["status"] = {}   # 새 타임 → 컷/멍 초기화 (로그는 유지)
            save_data()
            await refresh_board(self)
            print("타임 리셋:", cur)

    @reset_checker.before_loop
    async def before_reset(self):
        await self.wait_until_ready()


client = BossBot()


# ---- 슬래시 명령어 ----
async def boss_autocomplete(interaction: discord.Interaction, current: str):
    cur = current.replace(" ", "")
    out = []
    for n in boss_names():
        if cur == "" or cur in n.replace(" ", ""):
            out.append(app_commands.Choice(name=n, value=n))
        if len(out) >= 25:
            break
    return out


@client.tree.command(name="현황판", description="이 채널에 보스 현황판을 설치합니다.")
async def cmd_board(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_embed(), view=BoardView())
    msg = await interaction.original_response()
    data["board"] = {"channel_id": msg.channel.id, "message_id": msg.id}
    save_data()
    try:
        await msg.pin()
    except Exception:
        pass


@client.tree.command(name="컷", description="보스 컷(잡음)을 기록합니다.")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_cut(interaction: discord.Interaction, 보스: str):
    if not find_boss(보스):
        await interaction.response.send_message("그런 보스가 없어요.", ephemeral=True)
        return
    record(보스, "컷", interaction.user.display_name)
    await refresh_board(interaction.client)
    await interaction.response.send_message(
        f"🟢 **{보스}** 컷 기록 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})",
        ephemeral=True,
    )


@client.tree.command(name="멍", description="보스 멍(안 뜸)을 기록합니다.")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_mung(interaction: discord.Interaction, 보스: str):
    if not find_boss(보스):
        await interaction.response.send_message("그런 보스가 없어요.", ephemeral=True)
        return
    record(보스, "멍", interaction.user.display_name)
    await refresh_board(interaction.client)
    await interaction.response.send_message(
        f"🔴 **{보스}** 멍 기록 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})",
        ephemeral=True,
    )


@client.tree.command(name="로그", description="최근 컷/멍 기록을 봅니다.")
@app_commands.describe(보스="(선택) 특정 보스만 보기")
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
        emo = "🟢" if l["action"] == "컷" else "🔴"
        lines.append(f"{emo} {t}  {l['boss']}  {l['action']}  — {l['user']}")
    await interaction.response.send_message("```\n" + "\n".join(lines) + "\n```", ephemeral=True)


@client.tree.command(name="리셋", description="현재 타임의 컷/멍을 수동으로 초기화합니다.")
async def cmd_reset(interaction: discord.Interaction):
    data["status"] = {}
    save_data()
    await refresh_board(interaction.client)
    await interaction.response.send_message("현황판을 초기화했어요. (로그는 유지)", ephemeral=True)


def main():
    load_data()
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_TOKEN 이 필요합니다.")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
