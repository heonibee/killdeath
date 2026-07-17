"""
솔 인챈트 보스 컷/멍 체크 봇 (킬데스길드)
- 현황판을 여러 메시지로 나눠 설치, 각 메시지에 보스별 [🟢컷]/[🔴멍] 버튼(이름 표시)
- 버튼 누르면 시각+누른 사람 기록, 해당 현황판 메시지 즉시 갱신
- 00·03·09·12·21시 자동 리셋 (컷/멍 초기화, 로그는 보존)
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

KST = ZoneInfo("Asia/Seoul")
DATA_FILE = "data.json"
TOKEN = os.environ.get("DISCORD_TOKEN")
GROUP_SIZE = 5  # 한 메시지당 보스 수 (5마리=버튼10개=5줄, 디스코드 한도)

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


def groups():
    return [BOSSES[i:i + GROUP_SIZE] for i in range(0, len(BOSSES), GROUP_SIZE)]


def group_index_of(name):
    for gi, g in enumerate(groups()):
        if any(b["name"] == name for b in g):
            return gi
    return None


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


def slot_label(start):
    return start.strftime("%m/%d %H시 타임")


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
    return f"🔴 {head} — 멍 ({t}, {st['user']})"


def group_embed(gi):
    g = groups()[gi]
    start = dt.datetime.fromisoformat(data["slot"]) if data["slot"] else now_kst()
    total = len(groups())
    e = discord.Embed(
        title=f"🗡️ 킬데스길드 보스 현황판 ({gi + 1}/{total})",
        description="\n".join(status_line(b) for b in g),
        color=0x2F5496,
    )
    if gi == 0:
        e.set_author(name=slot_label(start.astimezone(KST)))
    done = sum(1 for b in BOSSES if data["status"].get(b["name"]))
    e.set_footer(text=f"기록 {done}/{len(BOSSES)} · 리셋 00·03·09·12·21시 · 아래 버튼으로 컷/멍")
    return e


def record(boss_name, action, user):
    now = now_kst()
    data["status"][boss_name] = {"state": action, "time": now.isoformat(), "user": user}
    data["log"].append({
        "ts": now.isoformat(), "boss": boss_name,
        "action": action, "user": user, "slot": data["slot"],
    })
    if len(data["log"]) > 5000:
        data["log"] = data["log"][-5000:]
    save_data()


class BossButton(discord.ui.Button):
    def __init__(self, boss_name, action, row):
        is_cut = (action == "컷")
        super().__init__(
            style=discord.ButtonStyle.success if is_cut else discord.ButtonStyle.danger,
            label=("🟢 " if is_cut else "🔴 ") + boss_name,
            custom_id=("c|" if is_cut else "m|") + boss_name,
            row=row,
        )
        self.boss_name = boss_name
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        record(self.boss_name, self.action, interaction.user.display_name)
        gi = group_index_of(self.boss_name)
        await interaction.response.edit_message(embed=group_embed(gi), view=GroupView(gi))


class GroupView(discord.ui.View):
    def __init__(self, gi):
        super().__init__(timeout=None)
        for i, b in enumerate(groups()[gi]):
            self.add_item(BossButton(b["name"], "컷", row=i))
            self.add_item(BossButton(b["name"], "멍", row=i))


async def refresh_group(client, gi):
    b = data.get("board")
    if not b or gi is None or gi >= len(b.get("messages", [])):
        return
    mid = b["messages"][gi]
    try:
        ch = client.get_channel(b["channel_id"]) or await client.fetch_channel(b["channel_id"])
        msg = await ch.fetch_message(mid)
        await msg.edit(embed=group_embed(gi), view=GroupView(gi))
    except Exception as e:
        print(f"group {gi} refresh error:", e)


async def refresh_all(client):
    if not data.get("board"):
        return
    for gi in range(len(groups())):
        await refresh_group(client, gi)


class BossBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        for gi in range(len(groups())):
            self.add_view(GroupView(gi))
        await self.tree.sync()
        self.reset_checker.start()

    async def on_ready(self):
        cur = slot_start(now_kst()).isoformat()
        if data.get("slot") != cur:
            data["slot"] = cur
            data["status"] = {}
            save_data()
        print(f"로그인: {self.user} | 현재 타임: {data['slot']}")

    @tasks.loop(seconds=20)
    async def reset_checker(self):
        cur = slot_start(now_kst()).isoformat()
        if data.get("slot") != cur:
            data["slot"] = cur
            data["status"] = {}
            save_data()
            await refresh_all(self)
            print("타임 리셋:", cur)

    @reset_checker.before_loop
    async def before_reset(self):
        await self.wait_until_ready()


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


@client.tree.command(name="현황판", description="이 채널에 보스 현황판(버튼)을 설치합니다.")
async def cmd_board(interaction: discord.Interaction):
    await interaction.response.send_message("현황판을 설치하는 중…", ephemeral=True)
    ch = interaction.channel
    msg_ids = []
    for gi in range(len(groups())):
        m = await ch.send(embed=group_embed(gi), view=GroupView(gi))
        msg_ids.append(m.id)
    data["board"] = {"channel_id": ch.id, "messages": msg_ids}
    save_data()
    try:
        first = await ch.fetch_message(msg_ids[0])
        await first.pin()
    except Exception:
        pass
    await interaction.edit_original_response(
        content=f"✅ 현황판 설치 완료 ({len(msg_ids)}개 메시지). 버튼으로 컷/멍을 체크하세요.")


@client.tree.command(name="컷", description="보스 컷(잡음)을 기록합니다.")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_cut(interaction: discord.Interaction, 보스: str):
    if not find_boss(보스):
        await interaction.response.send_message("그런 보스가 없어요.", ephemeral=True)
        return
    record(보스, "컷", interaction.user.display_name)
    await interaction.response.send_message(
        f"🟢 **{보스}** 컷 기록 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})", ephemeral=True)
    await refresh_group(interaction.client, group_index_of(보스))


@client.tree.command(name="멍", description="보스 멍(안 뜸)을 기록합니다.")
@app_commands.describe(보스="보스 이름")
@app_commands.autocomplete(보스=boss_autocomplete)
async def cmd_mung(interaction: discord.Interaction, 보스: str):
    if not find_boss(보스):
        await interaction.response.send_message("그런 보스가 없어요.", ephemeral=True)
        return
    record(보스, "멍", interaction.user.display_name)
    await interaction.response.send_message(
        f"🔴 **{보스}** 멍 기록 ({now_kst().strftime('%H:%M')}, {interaction.user.display_name})", ephemeral=True)
    await refresh_group(interaction.client, group_index_of(보스))


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


@client.tree.command(name="리셋", description="현재 타임의 컷/멍을 수동 초기화합니다.")
async def cmd_reset(interaction: discord.Interaction):
    data["status"] = {}
    save_data()
    await interaction.response.send_message("현황판을 초기화했어요. (로그 유지)", ephemeral=True)
    await refresh_all(interaction.client)


def main():
    load_data()
    if not TOKEN:
        raise SystemExit("환경변수 DISCORD_TOKEN 이 필요합니다.")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
