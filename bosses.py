# 솔 인챈트 보스 목록 (킬데스길드)
# manual 이 있으면 정시 젠 아님(처치 후 12/24시간 등) — 매 타임 항상 포함
# 표시 순서 = 이 리스트 순서

BOSSES = [
    {"name": "만드라고라",      "map": "8",       "loc": "포도밭",           "hours": [3, 9, 12, 21, 0], "prob": 100},
    {"name": "리치 마법사",     "map": "13",      "loc": "루테인 묘지",       "hours": [3, 9, 12, 21, 0], "prob": 100},
    {"name": "라그나",          "map": "15",      "loc": "메데나 숲",         "hours": [3, 9, 12, 21, 0], "prob": 100},
    {"name": "칼리타",          "map": "29",      "loc": "요정의 샘",         "hours": [3, 9, 12, 21, 0], "prob": 100},
    {"name": "발타로스",        "map": "40",      "loc": "칼테온 숲",         "hours": [3, 12, 21, 0],    "prob": 100},
    {"name": "가시 거북",       "map": "45",      "loc": "가시 은신처",       "hours": [3, 9, 12, 21, 0], "prob": 100},
    {"name": "사이클롭스",      "map": "25",      "loc": "채석장",           "hours": [12, 21, 0],       "prob": 50},
    {"name": "스펙터",          "map": "36",      "loc": "이교도 집결지",     "hours": [12, 21, 0],       "prob": 50},
    {"name": "환영의 아리엘",   "map": "41",      "loc": "생명 성지",         "hours": [9, 12, 21, 0],    "prob": 50},
    {"name": "라이칸",          "map": "38",      "loc": "저주받은 숲",       "hours": [12, 21, 0],       "prob": 50},
    {"name": "오우거 두목",     "map": "47",      "loc": "야수 고개",         "hours": [9, 12, 21, 0],    "prob": 100},
    {"name": "나가",            "map": "2",       "loc": "아이르 습지",       "hours": [21, 0],           "prob": 50},
    {"name": "모그라스",        "map": "18",      "loc": "오크 정착지",       "hours": [12, 21, 0],       "prob": 50},
    {"name": "오쿨루스",        "map": "42",      "loc": "아르타론 신전 2층", "hours": [12, 21, 0],       "prob": 100},
    {"name": "리퍼",            "map": "32",      "loc": "언데드 폐허",       "manual": "12시간 젠"},
    {"name": "스콜",            "map": "60",      "loc": "불의 둥지 1층",     "hours": [21, 0],           "prob": 100},
    {"name": "피닉스",          "map": "60",      "loc": "불의 둥지 1층",     "hours": [21, 0],           "prob": 100},
    {"name": "하피 여왕",       "map": "53",      "loc": "추락한 성전",       "hours": [21, 0],           "prob": 100},
    {"name": "에린",            "map": "55",      "loc": "그라나 성소 3층",   "hours": [21, 0],           "prob": 100},
    {"name": "수호자 라에쉬",   "map": "54",      "loc": "라에쉬 안식처",     "manual": "12시간 젠"},
    {"name": "드레이크",        "map": "59",      "loc": "레비아탄 계곡",     "manual": "12시간 젠"},
    {"name": "데몬",            "map": "52",      "loc": "라즈카 주술지 3층", "hours": [9, 12, 21, 0],    "prob": 100},
    {"name": "분노의 인페르노",  "map": "신의탑1층", "loc": "신의탑 1층",       "manual": "24시간 젠"},
    {"name": "검은 태양 라자엘", "map": "61",      "loc": "어둠의 성소 3층",   "manual": "12시간 젠"},
    {"name": "잠식된 아리엘",   "map": "61",      "loc": "어둠의 성소 2층",   "manual": "12시간 젠"},
    {"name": "그윈트",          "map": "34",      "loc": "그윈트 둥지",       "manual": "12시간 젠"},
    {"name": "나태의 데스웜",   "map": "신의탑2층", "loc": "신의탑 2층",       "manual": "확인요망"},
]

RESET_HOURS = [0, 3, 9, 12, 21]  # 정시 타임(젠 시각)

def boss_names():
    return [b["name"] for b in BOSSES]

def find_boss(name):
    for b in BOSSES:
        if b["name"] == name:
            return b
    return None

def tag_of(b):
    if b.get("manual"):
        return b["manual"]
    if b.get("prob") == 50:
        return "50%"
    return ""

def bosses_for_hour(h):
    """해당 정시 타임에 표시할 보스: 그 시각 정시 젠 + 확인요망(항상)."""
    out = []
    for b in BOSSES:
        if b.get("manual"):
            out.append(b)
        elif h in b.get("hours", []):
            out.append(b)
    # 리스트 원래 순서 유지
    order = {id(b): i for i, b in enumerate(BOSSES)}
    return sorted(out, key=lambda b: order[id(b)])
