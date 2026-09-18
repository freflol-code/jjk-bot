"""
raid.py — рейды на Сукуну для 1-5 игроков.

Ключевые механики:
- Пальцы Сукуны НЕ списываются. При старте боя все пальцы участника
  уходят в КД на 12 часов (FINGER_CD_SECONDS).
- Пальцы добываются только в сюжетке (см. story.py), поэтому их можно
  использовать многократно с задержкой.
- Уровень рейда (1/2/3 пальца) задаёт создатель. Чтобы присоединиться,
  у игрока должно быть НЕ МЕНЬШЕ пальцев, чем в рейде.
- Бой: пошаговый. Каждый живой игрок делает по одной атаке — обычной
  или врождённой техникой (если хватает ПЭ). Затем Сукуна отвечает.
- Сукуна может критовать.
- VIP даёт ×2 к золоту, опыту и дропу с рейда.
- Расширения Территории: на рейд может быть активен ТОЛЬКО ОДИН домен.
  Кто первый активировал — тот владелец. Массовые домены (aoe) бьют
  и союзников, кроме владельца.
- Победа/поражение заканчивают рейд, все возвращаются в школу (X=0).
"""
import json
import random
import time

import database
import gacha
from domains_data import DOMAINS
from combat import DOMAIN_EFFECTS, _find_domain_by_technique


FINGER_CD_SECONDS = 12 * 3600
MAX_PLAYERS = 5
SUKUNA_NAME = "Сукуна (Рейд-босс)"
SUKUNA_EMOJI = "👺"


# Домены, которые наносят массовый урон по области — бьют и союзников.
AOE_DOMAINS = {
    "malevolent_shrine",          # Злая Святыня — тысяча лезвий по области
    "coffin_of_the_iron_mountain",  # Гроб Железной Горы — магма по куполу
    "ashen_boundless_reach",      # Бескрайний Пепелящий Простор — пепел везде
}


SUKUNA_PHASES = {
    1: {
        "hp": 1500,
        "dmg_min": 25, "dmg_max": 35,
        "crit_chance": 0.10, "crit_mult": 1.8,
        "reward_gold": 1500, "reward_exp": 800,
        "drop": ("Осколок Плоти Сукуны", "эпический", 1),
    },
    2: {
        "hp": 2800,
        "dmg_min": 35, "dmg_max": 50,
        "crit_chance": 0.15, "crit_mult": 1.8,
        "reward_gold": 3000, "reward_exp": 1600,
        "drop": ("Метка Сукуны", "легендарный", 1),
    },
    3: {
        "hp": 5000,
        "dmg_min": 50, "dmg_max": 70,
        "crit_chance": 0.20, "crit_mult": 2.0,
        "reward_gold": 6000, "reward_exp": 3500,
        "drop": ("Сердце Сукуны", "легендарный", 1),
    },
}


_db_ready = False


def _ensure_tables():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raids (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id      INTEGER NOT NULL,
            fingers         INTEGER NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'lobby',
            boss_hp         INTEGER NOT NULL,
            boss_max_hp     INTEGER NOT NULL,
            turn_order_json TEXT    NOT NULL DEFAULT '[]',
            turn_idx        INTEGER NOT NULL DEFAULT 0,
            log_json        TEXT    NOT NULL DEFAULT '[]',
            created_at      INTEGER NOT NULL,
            finished_at     INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raid_participants (
            raid_id   INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            hp        INTEGER NOT NULL,
            max_hp    INTEGER NOT NULL,
            alive     INTEGER NOT NULL DEFAULT 1,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (raid_id, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finger_cooldowns (
            user_id    INTEGER NOT NULL PRIMARY KEY,
            expires_at INTEGER NOT NULL
        )
    """)

    # Миграция: домен хранится на уровне рейда
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(raids)")
    raid_cols = {r["name"] for r in cur.fetchall()}
    if "domain_key" not in raid_cols:
        conn.execute("ALTER TABLE raids ADD COLUMN domain_key TEXT")
    if "domain_turns" not in raid_cols:
        conn.execute("ALTER TABLE raids ADD COLUMN domain_turns INTEGER NOT NULL DEFAULT 0")
    if "domain_owner_id" not in raid_cols:
        conn.execute("ALTER TABLE raids ADD COLUMN domain_owner_id INTEGER")

    conn.commit()
    _db_ready = True


# ============================================================
#  ДОМЕН НА УРОВНЕ РЕЙДА (один на всех)
# ============================================================

def _get_raid_domain(raid_id: int) -> tuple[int | None, str | None, int]:
    """Возвращает (owner_id, domain_key, turns). Если домена нет — (None, None, 0)."""
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT domain_key, domain_turns, domain_owner_id FROM raids WHERE id = ?",
        (raid_id,),
    )
    row = cur.fetchone()
    if not row or not row["domain_key"] or (row["domain_turns"] or 0) <= 0:
        return (None, None, 0)
    return (row["domain_owner_id"], row["domain_key"], row["domain_turns"])


def _set_raid_domain(raid_id: int, owner_id: int, domain_key: str, turns: int):
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET domain_key = ?, domain_turns = ?, domain_owner_id = ? WHERE id = ?",
        (domain_key, turns, owner_id, raid_id),
    )
    conn.commit()


def _decrement_raid_domain(raid_id: int) -> tuple[int | None, str | None, int]:
    """Уменьшает счётчик ходов. При 0 — снимает домен."""
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT domain_key, domain_turns, domain_owner_id FROM raids WHERE id = ?",
        (raid_id,),
    )
    row = cur.fetchone()
    if not row or not row["domain_key"]:
        return (None, None, 0)
    new_turns = max(0, (row["domain_turns"] or 0) - 1)
    if new_turns == 0:
        conn.execute(
            "UPDATE raids SET domain_key = NULL, domain_turns = 0, domain_owner_id = NULL "
            "WHERE id = ?",
            (raid_id,),
        )
        conn.commit()
        return (None, None, 0)
    conn.execute(
        "UPDATE raids SET domain_turns = ? WHERE id = ?",
        (new_turns, raid_id),
    )
    conn.commit()
    return (row["domain_owner_id"], row["domain_key"], new_turns)


def _clear_raid_domain(raid_id: int):
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET domain_key = NULL, domain_turns = 0, domain_owner_id = NULL "
        "WHERE id = ?",
        (raid_id,),
    )
    conn.commit()


def _activate_raid_domain(raid: dict, user_id: int, technique_name: str):
    """Пытается активировать домен. Если на рейде уже есть активный домен —
    отказ, даже если чужой."""
    technique = gacha.get_technique(technique_name)
    if not technique or not technique.get("has_domain"):
        return
    domain_key = _find_domain_by_technique(technique_name)
    if not domain_key:
        return

    owner_id, cur_key, cur_turns = _get_raid_domain(raid["id"])
    if cur_key:
        cur_data = DOMAINS.get(cur_key)
        cur_name = cur_data["name"] if cur_data else cur_key
        owner_nick = "?"
        if owner_id:
            owner_nick = (
                database.get_or_create_player(owner_id, "")["username"]
                or f"Игрок {owner_id}"
            )
        nick = database.get_or_create_player(user_id, "")["username"] or f"Игрок {user_id}"
        raid["log"].append(
            f"   ⚠️ <b>{nick}</b> не может войти в Расширение: "
            f"на арене уже <b>{cur_name}</b> ({owner_nick}, {cur_turns} х.)"
        )
        return

    domain_data = DOMAINS[domain_key]
    effect = DOMAIN_EFFECTS.get(domain_key, {})
    nick = database.get_or_create_player(user_id, "")["username"] or f"Игрок {user_id}"

    if effect.get("gamble"):
        if random.random() < 0.5:
            _set_raid_domain(raid["id"], user_id, domain_key, 3)
            raid["log"].append(
                f"   🎰 <b>{nick}: УДАЧА!</b> {domain_data['emoji']} "
                f"<b>{domain_data['name']}</b> активирован на 3 хода!"
            )
        else:
            database.update_player_ce(user_id, 0)
            raid["log"].append(
                f"   💀 <b>{nick}: ПРОИГРЫШ!</b> {domain_data['emoji']} "
                f"<b>{domain_data['name']}</b> обнулил твою ПЭ!"
            )
        return

    _set_raid_domain(raid["id"], user_id, domain_key, 3)
    raid["log"].append(
        f"   {domain_data['emoji']} <b>{nick}: Расширение Территории</b> — "
        f"<b>{domain_data['name']}</b>!"
    )


def _process_raid_domain_tick(raid: dict) -> bool:
    """Тик домена после хода владельца.
    Возвращает True, если Сукуна умер от эффектов домена."""
    owner_id, domain_key, turns = _get_raid_domain(raid["id"])
    if not domain_key or turns <= 0:
        return False

    effect = DOMAIN_EFFECTS.get(domain_key, {})
    domain_data = DOMAINS.get(domain_key, {})
    domain_name = domain_data.get("name", domain_key)
    is_aoe = domain_key in AOE_DOMAINS

    parts = get_participants(raid["id"])

    # 1. Рика бьёт по Сукуне
    if effect.get("summon_rika"):
        rika_dmg = effect.get("rika_dmg", 50)
        if raid["boss_hp"] > 0:
            raid["boss_hp"] = max(0, raid["boss_hp"] - rika_dmg)
            raid["log"].append(f"   👻 <b>Рика Оримо</b> бьёт Сукуну: {rika_dmg} урона!")
            if raid["boss_hp"] <= 0:
                return True

    # 2. DoT от домена
    if effect.get("dot_dmg"):
        base = effect["dot_dmg"]
        growth = effect.get("dot_growth", 0)
        turns_elapsed = 3 - turns
        dot = base + growth * turns_elapsed
        dot_name = effect.get("dot_name", "Эффект домена")

        # Босс получает всегда
        if raid["boss_hp"] > 0:
            raid["boss_hp"] = max(0, raid["boss_hp"] - dot)
            raid["log"].append(f"   {dot_name} по Сукуне: {dot} урона!")
            if raid["boss_hp"] <= 0:
                return True

        # Если домен массовый — союзники (кроме владельца) тоже получают
        if is_aoe:
            for p in parts:
                if p["user_id"] == owner_id:
                    continue
                if not p["alive"]:
                    continue
                new_hp = max(0, p["hp"] - dot)
                alive = 1 if new_hp > 0 else 0
                nick = (
                    database.get_or_create_player(p["user_id"], "")["username"]
                    or f"Игрок {p['user_id']}"
                )
                conn = database.get_conn()
                conn.execute(
                    "UPDATE raid_participants SET hp = ?, alive = ? "
                    "WHERE raid_id = ? AND user_id = ?",
                    (new_hp, alive, raid["id"], p["user_id"]),
                )
                conn.commit()
                if alive:
                    raid["log"].append(f"   └ ☠️ {dot_name} бьёт {nick}: {dot} (HP: {new_hp})")
                else:
                    raid["log"].append(f"   └ 💀 {nick} падает от массового урона домена!")

    # 3. Лечение владельца
    if effect.get("heal_per_turn"):
        heal = effect["heal_per_turn"]
        t = next((p for p in parts if p["user_id"] == owner_id), None)
        if t and t["alive"]:
            new_hp = min(t["max_hp"], t["hp"] + heal)
            if new_hp > t["hp"]:
                conn = database.get_conn()
                conn.execute(
                    "UPDATE raid_participants SET hp = ? WHERE raid_id = ? AND user_id = ?",
                    (new_hp, raid["id"], owner_id),
                )
                conn.commit()
                raid["log"].append(f"   💚 Домен исцеляет владельца: +{new_hp - t['hp']} HP.")

    # 4. Уменьшаем счётчик
    new_owner, new_key, new_turns = _decrement_raid_domain(raid["id"])
    if new_key is None:
        raid["log"].append(f"   🌫️ <b>{domain_name}</b> рассеялось.")
    else:
        raid["log"].append(f"   ⏳ <b>{domain_name}</b>: осталось {new_turns} х.")

    # 5. Если владелец умер за время тика — снимаем домен
    fresh_parts = get_participants(raid["id"])
    owner_part = next((p for p in fresh_parts if p["user_id"] == owner_id), None)
    if owner_part and not owner_part["alive"]:
        _clear_raid_domain(raid["id"])
        raid["log"].append(f"   💀 Владелец домена пал — <b>{domain_name}</b> рассеялось.")

    return False


# ============================================================
#  КД НА ПАЛЬЦЫ
# ============================================================

def _get_finger_count(user_id: int) -> int:
    return database.count_item(user_id, "Палец Сукуны")


def get_cooldown_until(user_id: int) -> int:
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM finger_cooldowns WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return 0
    if row["expires_at"] <= int(time.time()):
        conn.execute("DELETE FROM finger_cooldowns WHERE user_id = ?", (user_id,))
        conn.commit()
        return 0
    return row["expires_at"]


def can_use_fingers(user_id: int) -> bool:
    return get_cooldown_until(user_id) == 0 and _get_finger_count(user_id) > 0


def get_available_fingers(user_id: int) -> int:
    if not can_use_fingers(user_id):
        return 0
    return min(3, _get_finger_count(user_id))


def start_finger_cooldown(user_id: int):
    _ensure_tables()
    expires = int(time.time()) + FINGER_CD_SECONDS
    conn = database.get_conn()
    conn.execute(
        "INSERT INTO finger_cooldowns (user_id, expires_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
        (user_id, expires),
    )
    conn.commit()


def format_cooldown(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m:02d}м"
    if m:
        return f"{m}м {s:02d}с"
    return f"{s}с"


# ============================================================
#  ЛОББИ
# ============================================================

def get_active_raid_for_user(user_id: int):
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.* FROM raids r
        JOIN raid_participants p ON p.raid_id = r.id
        WHERE p.user_id = ? AND r.status IN ('lobby', 'battle')
        ORDER BY r.created_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return _row_to_raid(row)


def _row_to_raid(row) -> dict:
    return {
        "id": row["id"],
        "creator_id": row["creator_id"],
        "fingers": row["fingers"],
        "status": row["status"],
        "boss_hp": row["boss_hp"],
        "boss_max_hp": row["boss_max_hp"],
        "turn_order": json.loads(row["turn_order_json"]),
        "turn_idx": row["turn_idx"],
        "log": json.loads(row["log_json"] or "[]"),
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "domain_key": row["domain_key"] if "domain_key" in row.keys() else None,
        "domain_turns": row["domain_turns"] if "domain_turns" in row.keys() else 0,
        "domain_owner_id": row["domain_owner_id"] if "domain_owner_id" in row.keys() else None,
    }


def _save_raid(raid: dict):
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET status = ?, boss_hp = ?, turn_idx = ?, "
        "log_json = ?, finished_at = ? WHERE id = ?",
        (
            raid["status"],
            raid["boss_hp"],
            raid["turn_idx"],
            json.dumps(raid["log"], ensure_ascii=False),
            raid["finished_at"],
            raid["id"],
        ),
    )
    conn.commit()


def get_participants(raid_id: int) -> list[dict]:
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM raid_participants WHERE raid_id = ? ORDER BY joined_at",
        (raid_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def create_raid(creator_id: int, fingers: int) -> dict:
    if fingers < 1 or fingers > 3:
        return {"ok": False, "msg": "Можно создать рейд на 1, 2 или 3 пальца."}
    if not can_use_fingers(creator_id):
        cd = get_cooldown_until(creator_id)
        if cd:
            left = cd - int(time.time())
            return {"ok": False, "msg": f"Твои пальцы в КД ещё {format_cooldown(left)}."}
        return {"ok": False, "msg": "У тебя нет пальцев Сукуны. Их дропают сюжетные боссы."}

    if get_active_raid_for_user(creator_id):
        return {"ok": False, "msg": "Ты уже в активном рейде."}

    available = get_available_fingers(creator_id)
    if fingers > available:
        return {"ok": False, "msg": f"У тебя только {available} пальцев."}

    player = database.get_or_create_player(creator_id, "")
    phase = SUKUNA_PHASES[fingers]
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO raids (creator_id, fingers, status, boss_hp, boss_max_hp,
                           turn_order_json, turn_idx, log_json, created_at)
        VALUES (?, ?, 'lobby', ?, ?, '[]', 0, '[]', ?)
    """, (creator_id, fingers, phase["hp"], phase["hp"], int(time.time())))
    raid_id = cur.lastrowid

    cur.execute("""
        INSERT INTO raid_participants (raid_id, user_id, hp, max_hp, alive, joined_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (raid_id, creator_id, player["hp"], player["max_hp"], int(time.time())))
    conn.commit()

    return {"ok": True, "raid_id": raid_id}


def join_raid(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Рейд уже начался."}

    parts = get_participants(raid_id)
    if any(p["user_id"] == user_id for p in parts):
        return {"ok": True, "msg": "Ты уже в рейде."}
    if len(parts) >= MAX_PLAYERS:
        return {"ok": False, "msg": "В рейде уже максимум игроков."}

    if not can_use_fingers(user_id):
        cd = get_cooldown_until(user_id)
        if cd:
            left = cd - int(time.time())
            return {"ok": False, "msg": f"Твои пальцы в КД ещё {format_cooldown(left)}."}
        return {"ok": False, "msg": "У тебя нет пальцев Сукуны."}

    required = raid["fingers"]
    have = _get_finger_count(user_id)
    if have < required:
        return {"ok": False, "msg": (
            f"Этот рейд на <b>{required}</b> 🩸 — Сукуна будет "
            f"{required}-пальцевым.\n"
            f"У тебя только <b>{have}</b> 🩸. Чтобы войти, нужно "
            f"минимум {required} пальцев."
        )}

    if get_active_raid_for_user(user_id):
        return {"ok": False, "msg": "Ты уже в другом рейде."}

    player = database.get_or_create_player(user_id, "")
    conn = database.get_conn()
    conn.execute("""
        INSERT INTO raid_participants (raid_id, user_id, hp, max_hp, alive, joined_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (raid_id, user_id, player["hp"], player["max_hp"], int(time.time())))
    conn.commit()
    return {"ok": True, "msg": f"Ты присоединился к рейду на {required} 🩸."}


def leave_raid(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Нельзя выйти из начавшегося боя."}

    conn = database.get_conn()
    conn.execute("DELETE FROM raid_participants WHERE raid_id = ? AND user_id = ?",
                 (raid_id, user_id))
    conn.commit()

    parts = get_participants(raid_id)
    if not parts:
        conn.execute("UPDATE raids SET status = 'finished', finished_at = ? WHERE id = ?",
                     (int(time.time()), raid_id))
        conn.commit()
        return {"ok": True, "msg": "Ты вышел. Рейд распущен.", "disband": True}
    return {"ok": True, "msg": "Ты вышел из лобби."}


def _get_raid_row(raid_id: int):
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM raids WHERE id = ?", (raid_id,))
    return cur.fetchone()


def get_raid(raid_id: int) -> dict | None:
    row = _get_raid_row(raid_id)
    return _row_to_raid(row) if row else None


# ============================================================
#  БОЙ
# ============================================================

def start_battle(raid_id: int, user_id: int) -> dict:
    raid_row = _get_raid_row(raid_id)
    if not raid_row:
        return {"ok": False, "msg": "Рейд не найден."}
    raid = _row_to_raid(raid_row)
    if raid["creator_id"] != user_id:
        return {"ok": False, "msg": "Только создатель может начать бой."}
    if raid["status"] != "lobby":
        return {"ok": False, "msg": "Бой уже начат."}

    parts = get_participants(raid_id)
    if not parts:
        return {"ok": False, "msg": "В рейде нет игроков."}

    for p in parts:
        start_finger_cooldown(p["user_id"])

    order = [p["user_id"] for p in parts]
    conn = database.get_conn()
    conn.execute(
        "UPDATE raids SET status = 'battle', turn_order_json = ?, turn_idx = 0, "
        "log_json = ?, created_at = ? WHERE id = ?",
        (json.dumps(order),
         json.dumps([f"👹 <b>{SUKUNA_NAME}</b> пробудился! Бой начался."], ensure_ascii=False),
         int(time.time()), raid_id),
    )
    conn.commit()

    return {"ok": True, "msg": "Бой начался!"}


def _current_player(raid: dict) -> int | None:
    order = raid["turn_order"]
    parts = {p["user_id"]: p for p in get_participants(raid["id"])}
    idx = raid["turn_idx"]
    while idx < len(order):
        uid = order[idx]
        if parts.get(uid, {}).get("alive"):
            return uid
        idx += 1
    return None


def is_player_turn(raid_id: int, user_id: int) -> bool:
    raid = get_raid(raid_id)
    if not raid or raid["status"] != "battle":
        return False
    return _current_player(raid) == user_id


def player_attack(raid_id: int, user_id: int, technique_name: str | None = None) -> dict:
    """Атака игрока. Если technique_name задано — используется врождённая
    техника. Мастер-техника пытается активировать домен.
    Урон умножается на dmg_mult АКТИВНОГО домена (если он есть)."""
    raid = get_raid(raid_id)
    if not raid or raid["status"] != "battle":
        return {"ok": False, "msg": "Бой не идёт."}
    if not is_player_turn(raid_id, user_id):
        return {"ok": False, "msg": "Сейчас не твой ход."}

    player = database.get_or_create_player(user_id, "")
    from combat import _physical_damage, _technique_damage, _black_flash_chance
    from config import PLAYER_CRIT_MULT

    technique = None
    if technique_name:
        technique = gacha.get_technique(technique_name)
        if not technique or technique_name not in gacha.get_equipped(user_id):
            return {"ok": False, "msg": "Эта техника недоступна в бою."}
        if player["ce"] < technique["ce_cost"]:
            return {"ok": False, "msg": (
                f"Не хватает ПЭ: нужно {technique['ce_cost']}🔵, "
                f"у тебя {player['ce']}🔵."
            )}

    if technique:
        dmg = _technique_damage(user_id, player, technique)
        verb = f"использовал «{technique_name}»"
    else:
        dmg = _physical_damage(user_id, player)
        verb = "атаковал"

    # Множитель активного домена — работает для ВСЕХ игроков, не только владельца.
    # Владелец — тот, кто поставил домен, получает свой dmg_mult. Союзники — тоже,
    # но по задумке это бафф владельца. В рейде эффект общий, что логично.
    _owner, dk, dt = _get_raid_domain(raid_id)
    if dk and dt > 0:
        deff = DOMAIN_EFFECTS.get(dk, {})
        dmg = int(dmg * deff.get("dmg_mult", 1.0))

    black_flash = random.random() < _black_flash_chance(user_id)
    if black_flash:
        dmg = int(dmg * PLAYER_CRIT_MULT)

    if technique:
        database.update_player_ce(user_id, player["ce"] - technique["ce_cost"])

    raid["boss_hp"] = max(0, raid["boss_hp"] - dmg)
    nick = player["username"] or f"Игрок {user_id}"
    line = (f"{technique['emoji'] + ' ' if technique else '🗡 '}<b>{nick}</b> "
            + (f"использовал «{technique_name}» " if technique else "атаковал ")
            + ("⚫⚡ <b>ЧЁРНАЯ ВСПЫШКА!</b> " if black_flash else "")
            + f"и нанёс <b>{dmg}</b> урона Сукуне.")
    raid["log"].append(line)
    raid["log"] = raid["log"][-40:]

    if raid["boss_hp"] <= 0:
        return _finish_victory(raid)

    # Активация домена при использовании мастер-техники
    if technique and technique.get("has_domain"):
        _activate_raid_domain(raid, user_id, technique_name)

    # Тик активного домена — только в ход владельца
    _owner, dk, dt = _get_raid_domain(raid_id)
    if dk and dt > 0 and _owner == user_id:
        if _process_raid_domain_tick(raid):
            return _finish_victory(raid)

    # После возможной смерти союзников от AoE — проверим, жив ли кто-то
    alive_parts = [p for p in get_participants(raid["id"]) if p["alive"]]
    if not alive_parts:
        return _finish_defeat(raid)

    raid["turn_idx"] += 1
    _save_raid(raid)

    if _current_player(raid) is None:
        return _sukuna_turn(raid)

    next_id = _current_player(raid)
    return {"ok": True, "msg": line, "notify": [next_id] if next_id else []}


def _sukuna_turn(raid: dict) -> dict:
    phase = SUKUNA_PHASES[raid["fingers"]]
    parts = [p for p in get_participants(raid["id"]) if p["alive"]]
    if not parts:
        return _finish_defeat(raid)

    _owner_id, dk, dt = _get_raid_domain(raid["id"])
    deff = DOMAIN_EFFECTS.get(dk, {}) if dk and dt > 0 else {}

    attack_type = random.choice(["strike", "dismantle"])
    if attack_type == "strike":
        targets = [random.choice(parts)]
        header = "👊 <b>Обычный удар</b>"
    else:
        if len(parts) >= 2:
            targets = random.sample(parts, 2)
        else:
            targets = parts[:]
        header = "🩸 <b>Рассечение</b>"

    raid["log"].append(f"👹 <b>{SUKUNA_NAME}</b> применяет: {header}")

    for t in targets:
        nick = database.get_or_create_player(t["user_id"], "")["username"] or f"Игрок {t['user_id']}"

        # Защита от домена действует только на владельца
        is_owner = (_owner_id is not None and t["user_id"] == _owner_id)
        dodge_bonus = 0.0
        def_mult = 1.0
        enemy_dmg_mult = 1.0
        if is_owner and deff:
            dodge_bonus = deff.get("dodge_bonus", 0.0) + deff.get("enemy_miss_bonus", 0.0)
            def_mult = deff.get("defense_mult", 1.0)
            enemy_dmg_mult = deff.get("enemy_dmg_mult", 1.0)

        if dodge_bonus > 0 and random.random() < dodge_bonus:
            raid["log"].append(f"   └ 🌀 {nick} уклонился благодаря домену!")
            continue

        raw = random.randint(phase["dmg_min"], phase["dmg_max"])
        crit = random.random() < phase["crit_chance"]
        if crit:
            raw = int(raw * phase["crit_mult"])

        raw = int(raw * def_mult * enemy_dmg_mult)
        raw = max(1, raw)

        new_hp = t["hp"] - raw
        alive = 1
        domain_note = (
            f" (домен x{def_mult:.2f})"
            if is_owner and (def_mult < 1.0 or enemy_dmg_mult < 1.0)
            else ""
        )
        if new_hp <= 0:
            new_hp = 0
            alive = 0

        conn = database.get_conn()
        conn.execute(
            "UPDATE raid_participants SET hp = ?, alive = ? WHERE raid_id = ? AND user_id = ?",
            (new_hp, alive, raid["id"], t["user_id"]),
        )
        conn.commit()

        crit_txt = " 💥<b>КРИТ!</b>" if crit else ""
        if alive:
            raid["log"].append(
                f"   └ {nick} получает <b>{raw}</b> урона{domain_note} (HP: {new_hp}).{crit_txt}"
            )
        else:
            raid["log"].append(f"   └ 💀 {nick} падает! (было {raw} урона).{crit_txt}")

    raid["log"] = raid["log"][-40:]

    # Если владелец домена умер — снимаем домен
    fresh_owner, fresh_key, fresh_turns = _get_raid_domain(raid["id"])
    if fresh_key and fresh_owner:
        owner_part = next(
            (p for p in get_participants(raid["id"]) if p["user_id"] == fresh_owner),
            None,
        )
        if owner_part and not owner_part["alive"]:
            dd = DOMAINS.get(fresh_key, {})
            dname = dd.get("name", fresh_key)
            _clear_raid_domain(raid["id"])
            raid["log"].append(f"   💀 Владелец домена пал — <b>{dname}</b> рассеялось.")

    raid["turn_idx"] = 0
    _save_raid(raid)

    alive_parts = [p for p in get_participants(raid["id"]) if p["alive"]]
    if not alive_parts:
        return _finish_defeat(raid)

    next_id = _current_player(raid)
    return {"ok": True, "msg": "Ход Сукуны", "notify": [next_id] if next_id else []}


def _send_all_to_school(raid_id: int):
    for p in get_participants(raid_id):
        database.update_player_x(p["user_id"], 0)
        database.clear_encounter(p["user_id"])
    _clear_raid_domain(raid_id)


def _finish_victory(raid: dict) -> dict:
    """Награда каждому выжившему. VIP даёт ×2 к золоту, опыту и дропу.
    Пальцев Сукуны в дропе рейда нет — их выдают только сюжетные боссы."""
    phase = SUKUNA_PHASES[raid["fingers"]]
    parts = get_participants(raid["id"])
    survivors = [p for p in parts if p["alive"]]

    for p in survivors:
        vip = database.vip_mult(p["user_id"])
        gold = int(phase["reward_gold"] * vip)
        exp = int(phase["reward_exp"] * vip)
        database.add_gold(p["user_id"], gold)
        database.add_exp_and_level(p["user_id"], exp)
        dn, dr, dq = phase["drop"]
        if vip > 1.0:
            dq *= 2
        database.add_item(p["user_id"], dn, dr, dq)

    raid["log"].append("🏆 <b>Сукуна изгнан! Победа!</b>")
    raid["status"] = "finished"
    raid["finished_at"] = int(time.time())
    _save_raid(raid)

    _send_all_to_school(raid["id"])

    return {
        "ok": True,
        "msg": "Победа!",
        "finished": True,
        "notify": [p["user_id"] for p in parts],
    }


def _finish_defeat(raid: dict) -> dict:
    raid["log"].append("☠️ <b>Все игроки пали. Сукуна победил.</b>")
    raid["status"] = "finished"
    raid["finished_at"] = int(time.time())
    _save_raid(raid)

    _send_all_to_school(raid["id"])

    return {
        "ok": True,
        "msg": "Поражение",
        "finished": True,
        "notify": [p["user_id"] for p in get_participants(raid["id"])],
    }


# ============================================================
#  UI-ТЕКСТЫ
# ============================================================

def format_lobby(raid_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."
    parts = get_participants(raid_id)
    lines = [
        "👺 <b>Рейд на Сукуну</b>",
        f"🔴 Пальцев: <b>{raid['fingers']}</b>",
        f"👥 Игроков: <b>{len(parts)}/{MAX_PLAYERS}</b>",
        "",
        f"<i>Чтобы присоединиться, у каждого должно быть минимум "
        f"{raid['fingers']} 🩸 (уровень рейда задаёт сложность Сукуны).</i>",
        "",
        "<b>Участники:</b>",
    ]
    for p in parts:
        nick = database.get_or_create_player(p["user_id"], "")["username"] or f"Игрок {p['user_id']}"
        creator_mark = " 👑" if p["user_id"] == raid["creator_id"] else ""
        vip_mark = " 💎" if database.has_vip(p["user_id"]) else ""
        lines.append(f"• {nick}{creator_mark}{vip_mark} — ❤️ {p['hp']}/{p['max_hp']}")
    lines.append("")
    lines.append("<i>Создатель жмёт «▶️ Начать бой». Все пальцы участников уйдут в КД на 12 часов.</i>")
    lines.append("<i>Скинь друзьям ссылку-приглашение кнопкой ниже 👇</i>")
    return "\n".join(lines)


def format_battle(raid_id: int, viewer_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."

    parts = get_participants(raid_id)
    cur_id = _current_player(raid)
    viewer = next((p for p in parts if p["user_id"] == viewer_id), None)

    owner_id, dk, dt = _get_raid_domain(raid_id)
    domain_line = ""
    if dk and dt > 0:
        dd = DOMAINS.get(dk, {})
        owner_nick = "?"
        if owner_id:
            owner_nick = (
                database.get_or_create_player(owner_id, "")["username"]
                or f"Игрок {owner_id}"
            )
        marker = " (твой)" if owner_id == viewer_id else ""
        aoe_mark = " · AoE" if dk in AOE_DOMAINS else ""
        domain_line = (
            f"{dd.get('emoji','')} <b>Домен:</b> {dd.get('name', dk)} — "
            f"<i>{owner_nick}</i>, {dt} х.{marker}{aoe_mark}"
        )

    lines = [
        "👺 <b>Рейд на Сукуну</b>",
        f"🔴 Пальцев: {raid['fingers']}",
        f"❤️ HP Сукуны: <b>{raid['boss_hp']}/{raid['boss_max_hp']}</b>",
    ]
    if domain_line:
        lines.append(domain_line)
    lines.append("")

    if viewer:
        vp = database.get_or_create_player(viewer_id, "")
        from equipment import get_equipped
        w = get_equipped(viewer_id)
        weapon_txt = f"{w['emoji']} {w['name']}" if w else "нет"
        alive_txt = "жив" if viewer["alive"] else "💀 выбыл"
        vip_txt = " 💎" if database.has_vip(viewer_id) else ""
        lines.append(f"👤 <b>Ты</b>{vip_txt}")
        lines.append(f"   ❤️ HP: {viewer['hp']}/{viewer['max_hp']} | "
                     f"🔵 ПЭ: {vp['ce']}/{vp['max_ce']} | 🧬 Ур. {vp['level']} | {alive_txt}")
        lines.append(f"   ⚔️ Оружие: {weapon_txt}")
        lines.append("")

    lines.append("<b>Отряд:</b>")
    for p in parts:
        nick = database.get_or_create_player(p["user_id"], "")["username"] or f"Игрок {p['user_id']}"
        vip_mark = " 💎" if database.has_vip(p["user_id"]) else ""
        if not p["alive"]:
            marker = "💀"
        elif p["user_id"] == cur_id:
            marker = "🎯"
        elif p["user_id"] == viewer_id:
            marker = "👤"
        else:
            marker = "❤️"
        owner_mark = " 👑домен" if (owner_id is not None and p["user_id"] == owner_id and dt > 0) else ""
        lines.append(f"{marker} {nick}{vip_mark}{owner_mark}: {p['hp']}/{p['max_hp']}")

    lines.append("")
    if cur_id:
        cur_nick = database.get_or_create_player(cur_id, "")["username"] or f"Игрок {cur_id}"
        if cur_id == viewer_id:
            lines.append("⏳ <b>Сейчас твой ход!</b>")
        else:
            lines.append(f"⏳ Ход: <b>{cur_nick}</b>")
    else:
        lines.append("⏳ Ход Сукуны...")

    lines.append("")
    lines.append("<b>Лог:</b>")
    for l in raid["log"][-8:]:
        lines.append(l)

    return "\n".join(lines)


def format_finished(raid_id: int) -> str:
    raid = get_raid(raid_id)
    if not raid:
        return "Рейд не найден."
    phase = SUKUNA_PHASES[raid["fingers"]]
    lines = ["🏁 <b>Рейд завершён</b>", ""]
    lines.extend(raid["log"][-10:])
    lines.append("")
    lines.append(f"💠 Базовая награда выжившему: {phase['reward_gold']}")
    lines.append(f"🧬 Опыт: {phase['reward_exp']}")
    lines.append(f"🎁 Дроп: {phase['drop'][0]}")
    lines.append("")
    lines.append("💎 <b>VIP-игроки получают ×2</b> к золоту, опыту и дропу.")
    lines.append("")
    lines.append("<i>Все участники возвращаются в Токийскую школу магии.</i>")
    return "\n".join(lines)
