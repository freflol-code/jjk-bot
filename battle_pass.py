"""
battle_pass.py — сезонный боевой пропуск «Магической Битвы: Токио».

Два трека:
- 🆓 Бесплатный: доступен всем, но награды скромнее.
- 💎 Премиум: покупается за 150 ⭐ на сезон, награды ×3 + эксклюзивы.

50 уровней. Стоимость первого уровня = BATTLE_PASS_BASE_XP.
Каждый следующий дороже на 5% от базы:
    xp(level) = BASE_XP × (1 + 0.05 × (level - 1))
Полный трек: ~1670 BP при BASE_XP = 15.

BP-очки начисляются за ЗАБРАННЫЕ ежедневные и недельные квесты
(см. quests.claim → battle_pass.on_quest_claimed).

Сезон: 60 дней. При старте нового сезона прогресс сбрасывается.

🎲 РАНДОМ НАГРАД:
Награды на якорных уровнях (5/10/15/…/50) генерируются детерминированно
из `season_id`. Один и тот же сезон всегда даёт одни и те же награды,
но разные сезоны — разные. Сезон S1 может дать технику «Огненный шар»,
а сезон S2 — «Ледяную стрелу». Эксклюзивные статусы тоже per-season:
`battle_pass_s1`, `battle_pass_s2`, и т.д.
"""
import json
import random
import time

import database


BATTLE_PASS_LEVELS = 50
BATTLE_PASS_BASE_XP = 15
BATTLE_PASS_STEP = 0.05
BATTLE_PASS_PREMIUM_STARS = 150
BATTLE_PASS_SEASON_DAYS = 60

BP_XP_DAILY = 20
BP_XP_WEEKLY = 50

BP_PREMIUM_PAYLOAD_PREFIX = "bp_premium_season_"


# ============================================================
#  УРОВНИ И XP
# ============================================================

def level_xp(level):
    if level < 1:
        level = 1
    if level > BATTLE_PASS_LEVELS:
        level = BATTLE_PASS_LEVELS
    return int(BATTLE_PASS_BASE_XP * (1 + BATTLE_PASS_STEP * (level - 1)))


def xp_for_level(level):
    if level <= 1:
        return 0
    return sum(level_xp(i) for i in range(1, level))


def total_xp_full_track():
    return xp_for_level(BATTLE_PASS_LEVELS + 1)


def level_from_xp(xp):
    level = 1
    while level < BATTLE_PASS_LEVELS:
        if xp >= xp_for_level(level + 1):
            level += 1
        else:
            break
    return level


# ============================================================
#  БД: СЕЗОНЫ И ПРОГРЕСС
# ============================================================

_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_pass_seasons (
            id         TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            ends_at    INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_battle_pass (
            user_id        INTEGER NOT NULL,
            season_id      TEXT NOT NULL,
            xp             INTEGER NOT NULL DEFAULT 0,
            premium        INTEGER NOT NULL DEFAULT 0,
            claimed_free   TEXT NOT NULL DEFAULT '[]',
            claimed_prem   TEXT NOT NULL DEFAULT '[]',
            purchased_at   INTEGER,
            PRIMARY KEY (user_id, season_id)
        )
    """)
    conn.commit()
    _db_ready = True


def get_active_season():
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "SELECT id FROM battle_pass_seasons WHERE ends_at > ? "
        "ORDER BY started_at DESC LIMIT 1",
        (now,),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("SELECT COUNT(*) AS c FROM battle_pass_seasons")
    total = cur.fetchone()["c"]
    new_id = f"S{total + 1}"
    ends = now + BATTLE_PASS_SEASON_DAYS * 86400
    conn.execute(
        "INSERT INTO battle_pass_seasons (id, started_at, ends_at) VALUES (?, ?, ?)",
        (new_id, now, ends),
    )
    conn.commit()
    return new_id


def get_season_info():
    _ensure_tables()
    season_id = get_active_season()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, started_at, ends_at FROM battle_pass_seasons WHERE id = ?", (season_id,))
    row = cur.fetchone()
    if not row:
        return {"id": season_id, "started_at": 0, "ends_at": 0}
    return dict(row)


def _get_row(user_id):
    _ensure_tables()
    season_id = get_active_season()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM player_battle_pass WHERE user_id = ? AND season_id = ?",
        (user_id, season_id),
    )
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO player_battle_pass (user_id, season_id, xp, premium, "
            "claimed_free, claimed_prem) VALUES (?, ?, 0, 0, '[]', '[]')",
            (user_id, season_id),
        )
        conn.commit()
        cur.execute(
            "SELECT * FROM player_battle_pass WHERE user_id = ? AND season_id = ?",
            (user_id, season_id),
        )
        row = cur.fetchone()
    return row


def _save(user_id, season_id, xp, premium, claimed_free, claimed_prem, purchased_at):
    conn = database.get_conn()
    conn.execute(
        "UPDATE player_battle_pass SET xp = ?, premium = ?, claimed_free = ?, "
        "claimed_prem = ?, purchased_at = ? WHERE user_id = ? AND season_id = ?",
        (
            int(xp), int(premium),
            json.dumps(claimed_free), json.dumps(claimed_prem),
            purchased_at, user_id, season_id,
        ),
    )
    conn.commit()


# ============================================================
#  НАЧИСЛЕНИЕ BP
# ============================================================

def add_xp(user_id, amount):
    if amount <= 0:
        return (0, 0)
    row = _get_row(user_id)
    old_xp = row["xp"] or 0
    old_level = level_from_xp(old_xp)
    new_xp = min(old_xp + amount, xp_for_level(BATTLE_PASS_LEVELS + 1))
    new_level = level_from_xp(new_xp)
    _save(
        user_id, row["season_id"], new_xp, row["premium"],
        json.loads(row["claimed_free"] or "[]"),
        json.loads(row["claimed_prem"] or "[]"),
        row["purchased_at"],
    )
    return (old_level, new_level)


def on_quest_claimed(user_id, period):
    if period == "daily":
        return add_xp(user_id, BP_XP_DAILY)
    if period == "weekly":
        return add_xp(user_id, BP_XP_WEEKLY)
    return (0, 0)


def get_progress(user_id):
    row = _get_row(user_id)
    xp = row["xp"] or 0
    return {
        "season_id": row["season_id"],
        "xp": xp,
        "level": level_from_xp(xp),
        "premium": bool(row["premium"]),
        "claimed_free": json.loads(row["claimed_free"] or "[]"),
        "claimed_prem": json.loads(row["claimed_prem"] or "[]"),
    }


def grant_premium(user_id):
    row = _get_row(user_id)
    if row["premium"]:
        return False
    _save(
        user_id, row["season_id"], row["xp"], 1,
        json.loads(row["claimed_free"] or "[]"),
        json.loads(row["claimed_prem"] or "[]"),
        int(time.time()),
    )
    return True


# ============================================================
#  🎲 РАНДОМНЫЕ НАГРАДЫ ПО СЕЗОНАМ
# ============================================================

# Пул возможных наград на якорных уровнях.
# Конкретные цифры (qty / amount) роллятся из шаблона при генерации сезона.

FREE_ITEM_POOL = [
    {"type": "item", "name": "🍜 Рамен додзё", "rarity": "расходник", "qty_range": (3, 8)},
    {"type": "item", "name": "🧧 Талисман силы", "rarity": "расходник", "qty_range": (1, 3)},
    {"type": "item", "name": "🧪 Проклятая микстура", "rarity": "расходник", "qty_range": (1, 2)},
    {"type": "item", "name": "🛡 Талисман стойкости", "rarity": "расходник", "qty_range": (1, 3)},
    {"type": "item", "name": "💠 Талисман потока", "rarity": "расходник", "qty_range": (1, 2)},
    {"type": "item", "name": "⚫ Талисман Вспышки", "rarity": "расходник", "qty_range": (1, 2)},
    {"type": "item", "name": "📜 Свиток опыта Годжо", "rarity": "расходник", "qty_range": (1, 2)},
    {"type": "exp", "amount_range": (800, 2000)},
    {"type": "exp", "amount_range": (2000, 5000)},
]

FREE_TECH_RARITIES = ["Обычная", "Редкая", "Редкая", "Эпическая"]

PREM_ITEM_POOL = [
    {"type": "item", "name": "🧧 Талисман силы", "rarity": "расходник", "qty_range": (3, 8)},
    {"type": "item", "name": "🛡 Талисман стойкости", "rarity": "расходник", "qty_range": (3, 8)},
    {"type": "item", "name": "💠 Талисман потока", "rarity": "расходник", "qty_range": (2, 5)},
    {"type": "item", "name": "⚫ Талисман Вспышки", "rarity": "расходник", "qty_range": (2, 5)},
    {"type": "item", "name": "🧬 Эликсир роста", "rarity": "расходник", "qty_range": (1, 3)},
    {"type": "item", "name": "💰 Эликсир охотника", "rarity": "расходник", "qty_range": (1, 3)},
    {"type": "item", "name": "🎯 Метка Годжо", "rarity": "расходник", "qty_range": (2, 5)},
    {"type": "item", "name": "🧭 Компас Скверны", "rarity": "расходник", "qty_range": (2, 5)},
    {"type": "item", "name": "📜 Свиток опыта Годжо", "rarity": "расходник", "qty_range": (2, 5)},
    {"type": "exp", "amount_range": (5000, 15000)},
    {"type": "gold", "amount_range": (20000, 80000)},
]

PREM_TECH_RARITIES = ["Редкая", "Эпическая", "Эпическая", "Мифическая", "Легендарная (Особый класс)"]

_ANCHOR_LEVELS = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)

_season_cache = {}


def _materialize_reward(rng, template):
    """Превращает шаблон в конкретную награду, ролля количество/сумму."""
    out = {k: v for k, v in template.items() if not k.endswith("_range")}
    if "qty_range" in template:
        lo, hi = template["qty_range"]
        out["qty"] = rng.randint(lo, hi)
    if "amount_range" in template:
        lo, hi = template["amount_range"]
        out["amount"] = rng.randint(lo, hi)
    return out


def _generate_season_rewards(season_id):
    """Генерирует таблицу наград на сезон детерминированно.
    Возвращает (free_special, prem_special) — dict {level: [rewards]}."""
    rng = random.Random(f"bp:{season_id}")

    free_special = {}
    prem_special = {}

    # --- Бесплатный трек: 10 якорей, из них 3 — техники ---
    free_levels = list(_ANCHOR_LEVELS)
    rng.shuffle(free_levels)
    tech_levels = set(free_levels[:3])

    for lvl in _ANCHOR_LEVELS:
        rewards = []
        if lvl in tech_levels:
            rarity = rng.choice(FREE_TECH_RARITIES)
            rewards.append({"type": "technique_random", "rarity": rarity, "count": 1})
        else:
            picks = rng.sample(FREE_ITEM_POOL, k=rng.randint(1, 2))
            for p in picks:
                rewards.append(_materialize_reward(rng, p))
        free_special[lvl] = rewards

    # --- Премиум трек: 10 якорей, 25 и 50 — эксклюзивные статусы ---
    status_key_25 = f"battle_pass_{season_id.lower()}"
    status_key_50 = f"battle_pass_{season_id.lower()}_elite"

    for lvl in _ANCHOR_LEVELS:
        rewards = []
        if lvl == 25:
            rewards.append({"type": "status", "key": status_key_25})
            picks = rng.sample(PREM_ITEM_POOL, k=1)
            rewards.append(_materialize_reward(rng, picks[0]))
        elif lvl == 50:
            rewards.append({"type": "status", "key": status_key_50})
            rewards.append({
                "type": "technique_random",
                "rarity": "Легендарная (Особый класс)",
                "count": 1,
            })
        elif lvl % 10 == 0:
            rarity = rng.choice(PREM_TECH_RARITIES)
            rewards.append({"type": "technique_random", "rarity": rarity, "count": 1})
        else:
            picks = rng.sample(PREM_ITEM_POOL, k=rng.randint(2, 3))
            for p in picks:
                rewards.append(_materialize_reward(rng, p))
        prem_special[lvl] = rewards

    return free_special, prem_special


def get_season_rewards(season_id):
    """Возвращает (free_special, prem_special) для сезона, с кэшем."""
    if season_id not in _season_cache:
        _season_cache[season_id] = _generate_season_rewards(season_id)
    return _season_cache[season_id]


def _ensure_season_statuses(season_id):
    """Регистрирует в statuses.STATUSES эксклюзивные статусы сезона,
    если их там ещё нет. Так каждый сезон получает свои 2 статуса."""
    try:
        import statuses
    except ImportError:
        return
    key_25 = f"battle_pass_{season_id.lower()}"
    key_50 = f"battle_pass_{season_id.lower()}_elite"
    if key_25 not in statuses.STATUSES:
        statuses.STATUSES[key_25] = {
            "emoji": "🎫",
            "styled": f"❰ ʙᴘ {season_id} ❱",
            "star_price": 0,
            "gold_price": 0,
            "desc": f"Эксклюзив премиум-трека Сезона {season_id} (уровень 25).",
            "exclusive": True,
        }
        if key_25 not in statuses.STATUS_ORDER:
            statuses.STATUS_ORDER.append(key_25)
    if key_50 not in statuses.STATUSES:
        statuses.STATUSES[key_50] = {
            "emoji": "🏆",
            "styled": f"◆ {season_id} 𝕰𝖑𝖎𝖙𝖊 ◆",
            "star_price": 0,
            "gold_price": 0,
            "desc": f"Эксклюзив премиум-трека Сезона {season_id} (уровень 50).",
            "exclusive": True,
        }
        if key_50 not in statuses.STATUS_ORDER:
            statuses.STATUS_ORDER.append(key_50)


# ============================================================
#  НАГРАДЫ: ПОЛУЧЕНИЕ
# ============================================================

def get_reward(level, tier, season_id=None):
    """Список наград для уровня и трека. tier: 'free' | 'prem'."""
    if level < 1 or level > BATTLE_PASS_LEVELS:
        return []
    if season_id is None:
        season_id = get_active_season()
    free_special, prem_special = get_season_rewards(season_id)

    if tier == "free":
        gold = 500 + 100 * level
        exp = 300 + 80 * level
        base = [{"type": "gold", "amount": gold}, {"type": "exp", "amount": exp}]
        return base + free_special.get(level, [])
    elif tier == "prem":
        gold = 1500 + 300 * level
        exp = 900 + 240 * level
        base = [{"type": "gold", "amount": gold}, {"type": "exp", "amount": exp}]
        return base + prem_special.get(level, [])
    return []


def _apply_reward(user_id, reward):
    t = reward.get("type")
    if t == "gold":
        database.add_gold(user_id, reward["amount"])
        return f"💠 +{reward['amount']}"
    if t == "exp":
        database.add_exp_and_level(user_id, reward["amount"])
        return f"🧬 +{reward['amount']}"
    if t == "item":
        database.add_item(user_id, reward["name"], reward["rarity"], reward["qty"])
        return f"{reward['name']} ×{reward['qty']}"
    if t == "technique_random":
        from techniques_data import TECHNIQUES
        pool = [n for n, tech in TECHNIQUES.items() if tech["rarity"] == reward["rarity"]]
        if not pool:
            return None
        count = min(reward.get("count", 1), len(pool))
        picked = random.sample(pool, count)
        parts = []
        for name in picked:
            tech = TECHNIQUES[name]
            is_new = database.add_player_technique(user_id, name, tech["rarity"])
            tag = "" if is_new else " <i>(дубликат)</i>"
            parts.append(f"{tech['emoji']} {name}{tag}")
        return "\n     ".join(parts)
    if t == "status":
        import statuses
        key = reward.get("key")
        if key and key in statuses.STATUSES:
            database.add_player_status(user_id, key)
            st = statuses.STATUSES[key]
            return f"🎭 {st['styled']}"
        return None
    return None


def claim_level(user_id, level, tier):
    if level < 1 or level > BATTLE_PASS_LEVELS:
        return {"ok": False, "msg": "Некорректный уровень."}

    row = _get_row(user_id)
    season_id = row["season_id"]
    current_level = level_from_xp(row["xp"] or 0)
    if current_level < level:
        return {"ok": False, "msg": f"🔒 Сначала достигни уровня {level}."}

    premium = bool(row["premium"])
    if tier == "prem" and not premium:
        return {"ok": False, "msg": "💎 Нужен премиум-пропуск."}

    claimed_free = json.loads(row["claimed_free"] or "[]")
    claimed_prem = json.loads(row["claimed_prem"] or "[]")

    if tier == "free" and level in claimed_free:
        return {"ok": False, "msg": "Награда уже получена."}
    if tier == "prem" and level in claimed_prem:
        return {"ok": False, "msg": "Награда уже получена."}

    _ensure_season_statuses(season_id)

    rewards = get_reward(level, tier, season_id)
    lines = [f"🎫 <b>Уровень {level} · {'💎 Премиум' if tier == 'prem' else '🆓 Бесплатно'}</b>"]
    for r in rewards:
        applied = _apply_reward(user_id, r)
        if applied:
            lines.append(f"  • {applied}")

    if tier == "free":
        claimed_free.append(level)
    else:
        claimed_prem.append(level)

    _save(
        user_id, season_id, row["xp"], row["premium"],
        claimed_free, claimed_prem, row["purchased_at"],
    )

    return {"ok": True, "msg": "\n".join(lines)}


def claim_all(user_id):
    row = _get_row(user_id)
    season_id = row["season_id"]
    current_level = level_from_xp(row["xp"] or 0)
    premium = bool(row["premium"])
    claimed_free = set(json.loads(row["claimed_free"] or "[]"))
    claimed_prem = set(json.loads(row["claimed_prem"] or "[]"))

    _ensure_season_statuses(season_id)

    count_free = 0
    count_prem = 0

    for level in range(1, current_level + 1):
        if level not in claimed_free:
            for r in get_reward(level, "free", season_id):
                _apply_reward(user_id, r)
            claimed_free.add(level)
            count_free += 1
        if premium and level not in claimed_prem:
            for r in get_reward(level, "prem", season_id):
                _apply_reward(user_id, r)
            claimed_prem.add(level)
            count_prem += 1

    _save(
        user_id, season_id, row["xp"], row["premium"],
        sorted(claimed_free), sorted(claimed_prem), row["purchased_at"],
    )

    if count_free == 0 and count_prem == 0:
        return {"ok": False, "msg": "Нечего забирать."}

    lines = [f"✅ Забрано бесплатных уровней: <b>{count_free}</b>"]
    if premium:
        lines.append(f"✅ Забрано премиум уровней: <b>{count_prem}</b>")
    return {"ok": True, "msg": "\n".join(lines)}


# ============================================================
#  UI
# ============================================================

def _format_reward(r):
    t = r.get("type")
    if t == "gold":
        return f"💠 +{r['amount']}"
    if t == "exp":
        return f"🧬 +{r['amount']}"
    if t == "item":
        return f"{r['name']} ×{r['qty']}"
    if t == "technique_random":
        return f"🎁 Случайная техника ({r['rarity']})"
    if t == "status":
        return "🎭 Эксклюзивный статус сезона"
    return "?"


def format_battle_pass(user_id):
    info = get_progress(user_id)
    season = get_season_info()
    season_id = season["id"]
    level = info["level"]
    xp = info["xp"]
    premium = info["premium"]

    now = int(time.time())
    ends_in = max(0, season["ends_at"] - now)
    days = ends_in // 86400
    hours = (ends_in % 86400) // 3600

    if level >= BATTLE_PASS_LEVELS:
        xp_line = "🎯 <b>Все 50 уровней взяты!</b>"
    else:
        cur_start = xp_for_level(level)
        next_start = xp_for_level(level + 1)
        need = next_start - cur_start
        have = xp - cur_start
        xp_line = f"🎯 До уровня {level + 1}: <b>{have}/{need}</b>"

    lines = [
        f"🎫 <b>Боевой пропуск — Сезон {season_id}</b>",
        "",
        f"📅 До конца сезона: <b>{days} д. {hours} ч.</b>",
        f"🧬 BP-очков: <b>{xp}</b> (из {total_xp_full_track()})",
        f"🏆 Уровень: <b>{level}/{BATTLE_PASS_LEVELS}</b>",
        xp_line,
        "",
    ]
    if premium:
        lines.append("💎 <b>Премиум активен</b>")
    else:
        lines.append(f"🔒 Премиум: <b>{BATTLE_PASS_PREMIUM_STARS}⭐</b>")
    lines.append("")
    lines.append(
        f"<i>Очки БП начисляются за забранные квесты: "
        f"+{BP_XP_DAILY} за ежедневный, +{BP_XP_WEEKLY} за недельный.</i>"
    )
    lines.append("")
    lines.append(
        "<i>🎲 На уровнях 5/10/15/…/50 в каждом сезоне — "
        "уникальные награды: техники, предметы и эксклюзивные статусы.</i>"
    )
    return "\n".join(lines)


def format_levels_overview(user_id):
    info = get_progress(user_id)
    level = info["level"]
    premium = info["premium"]
    claimed_free = len(info["claimed_free"])
    claimed_prem = len(info["claimed_prem"])
    lines = [
        "📜 <b>Уровни Боевого пропуска</b>",
        "",
        f"🏆 Текущий уровень: <b>{level}/{BATTLE_PASS_LEVELS}</b>",
        f"🆓 Забрано бесплатных: <b>{claimed_free}/{level}</b>",
    ]
    if premium:
        lines.append(f"💎 Забрано премиум: <b>{claimed_prem}/{level}</b>")
    else:
        lines.append("💎 Премиум не куплен")
    lines.append("")
    lines.append("<i>Нажми на уровень, чтобы посмотреть награды и забрать их.</i>")
    lines.append("🎁 = есть что забрать · ✅ = всё забрано · 🔒 = не достигнут")
    return "\n".join(lines)


def format_level_detail(user_id, level):
    info = get_progress(user_id)
    season_id = info["season_id"]
    current_level = info["level"]
    premium = info["premium"]
    claimed_free = set(info["claimed_free"])
    claimed_prem = set(info["claimed_prem"])

    free_rewards = get_reward(level, "free", season_id)
    prem_rewards = get_reward(level, "prem", season_id)

    lines = [f"🎫 <b>Уровень {level}/{BATTLE_PASS_LEVELS}</b>", ""]

    lines.append("🆓 <b>Бесплатный трек:</b>")
    for r in free_rewards:
        lines.append(f"  • {_format_reward(r)}")
    if level in claimed_free:
        lines.append("  <i>✅ Забрано</i>")
    elif current_level >= level:
        lines.append("  <i>🎁 Готово к получению</i>")
    else:
        lines.append("  <i>🔒 Ещё не достигнут</i>")

    lines.append("")
    lines.append("💎 <b>Премиум трек:</b>")
    for r in prem_rewards:
        lines.append(f"  • {_format_reward(r)}")
    if not premium:
        lines.append("  <i>🔒 Нужен премиум-пропуск</i>")
    elif level in claimed_prem:
        lines.append("  <i>✅ Забрано</i>")
    elif current_level >= level:
        lines.append("  <i>🎁 Готово к получению</i>")
    else:
        lines.append("  <i>🔒 Ещё не достигнут</i>")

    return "\n".join(lines)


def bp_menu_keyboard(user_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    info = get_progress(user_id)
    level = info["level"]
    premium = info["premium"]

    rows = []
    if not premium:
        rows.append([InlineKeyboardButton(
            f"💎 Купить премиум ({BATTLE_PASS_PREMIUM_STARS}⭐)",
            callback_data="bp_buy_premium",
        )])
    rows.append([InlineKeyboardButton("📜 Список уровней", callback_data="bp_levels")])
    if level >= 1:
        rows.append([InlineKeyboardButton("🎁 Забрать всё доступное", callback_data="bp_claim_all")])
    rows.append([InlineKeyboardButton("⬅️ К заданиям", callback_data="quests_menu")])
    return InlineKeyboardMarkup(rows)


def bp_levels_keyboard(user_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    info = get_progress(user_id)
    level = info["level"]
    claimed_free = set(info["claimed_free"])
    claimed_prem = set(info["claimed_prem"])
    premium = info["premium"]

    rows = []
    for start in range(1, BATTLE_PASS_LEVELS + 1, 5):
        row = []
        for lvl in range(start, min(start + 5, BATTLE_PASS_LEVELS + 1)):
            if lvl <= level:
                free_ready = lvl not in claimed_free
                prem_ready = premium and lvl not in claimed_prem
                mark = "🎁" if (free_ready or prem_ready) else "✅"
            else:
                mark = "🔒"
            row.append(InlineKeyboardButton(
                f"{mark} {lvl}",
                callback_data=f"bp_level:{lvl}",
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ К обзору", callback_data="bp_menu")])
    return InlineKeyboardMarkup(rows)


def bp_level_detail_keyboard(user_id, level):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    info = get_progress(user_id)
    current_level = info["level"]
    premium = info["premium"]
    claimed_free = set(info["claimed_free"])
    claimed_prem = set(info["claimed_prem"])

    rows = []
    if level <= current_level and level not in claimed_free:
        rows.append([InlineKeyboardButton(
            "🎁 Забрать бесплатное",
            callback_data=f"bp_claim:{level}:free",
        )])
    if premium and level <= current_level and level not in claimed_prem:
        rows.append([InlineKeyboardButton(
            "💎 Забрать премиум",
            callback_data=f"bp_claim:{level}:prem",
        )])
    rows.append([InlineKeyboardButton("⬅️ К уровням", callback_data="bp_levels")])
    return InlineKeyboardMarkup(rows)
