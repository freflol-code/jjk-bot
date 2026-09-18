"""
Работа с базой данных (SQLite).
Простая синхронная обёртка — для хобби-бота этого достаточно.

Схема бережно мигрируется: init_db() добавляет недостающие колонки
и таблицы, ничего не удаляя. Существующие игроки, их золото/уровень/HP
и инвентарь сохраняются при обновлении.

Дополнительные модули могут лениво создавать свои таблицы
(например, quests.py, rest.py, equipment.py, баффы), не задевая этот файл.
"""
import sqlite3
import time
from config import DB_PATH, CE_CONTROL_BASE, MAX_CE_BASE

_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _ensure_column(conn, table: str, column: str, ddl: str):
    """Добавляет колонку, если её ещё нет (безопасная миграция)."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            x INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1,
            exp INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 10,
            hp INTEGER NOT NULL DEFAULT 50,
            max_hp INTEGER NOT NULL DEFAULT 50,
            created_at INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS encounters (
            user_id INTEGER PRIMARY KEY,
            biome_id TEXT,
            monster_name TEXT,
            hp INTEGER,
            max_hp INTEGER,
            dmg_min INTEGER,
            dmg_max INTEGER,
            emoji TEXT,
            rarity TEXT,
            spawned_at INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_techniques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            technique_name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            UNIQUE(user_id, technique_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipped_techniques (
            user_id INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            technique_name TEXT NOT NULL,
            PRIMARY KEY (user_id, slot)
        )
    """)

    # --- Миграция players: новые статы Проклятой Энергии ---
    _ensure_column(conn, "players", "ce", f"ce INTEGER NOT NULL DEFAULT {MAX_CE_BASE}")
    _ensure_column(conn, "players", "max_ce", f"max_ce INTEGER NOT NULL DEFAULT {MAX_CE_BASE}")
    _ensure_column(conn, "players", "ce_control", f"ce_control INTEGER NOT NULL DEFAULT {CE_CONTROL_BASE}")
    _ensure_column(conn, "players", "dmg_buff_turns", "dmg_buff_turns INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "players", "dmg_buff_mult", "dmg_buff_mult REAL NOT NULL DEFAULT 1.0")

    # --- Миграция encounters: класс проклятия, дроп, эффекты, домен ---
    _ensure_column(conn, "encounters", "curse_class", "curse_class TEXT")
    _ensure_column(conn, "encounters", "drop_item", "drop_item TEXT")
    _ensure_column(conn, "encounters", "drop_rarity", "drop_rarity TEXT")
    _ensure_column(conn, "encounters", "stun_turns", "stun_turns INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "encounters", "bleed_turns", "bleed_turns INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "encounters", "bleed_dmg", "bleed_dmg INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "encounters", "domain_key", "domain_key TEXT")
    _ensure_column(conn, "encounters", "domain_turns", "domain_turns INTEGER NOT NULL DEFAULT 0")

    # --- Оружие ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_weapons (
            user_id     INTEGER NOT NULL,
            weapon_name TEXT NOT NULL,
            acquired_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, weapon_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipped_weapon (
            user_id     INTEGER PRIMARY KEY,
            weapon_name TEXT NOT NULL
        )
    """)

    # --- Баффы (реальное время) ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_buffs (
            user_id    INTEGER NOT NULL,
            stat       TEXT NOT NULL,
            value      REAL NOT NULL,
            expires_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, stat)
        )
    """)

    # --- Pity-система гачи и VIP ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_pity (
            user_id    INTEGER PRIMARY KEY,
            pity_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_vip (
            user_id    INTEGER PRIMARY KEY,
            expires_at INTEGER NOT NULL DEFAULT 0
        )
    """)

    # --- Типы ПЭ, кланы, Проклятия Небес ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_ce_types (
            user_id INTEGER NOT NULL,
            ce_key  TEXT NOT NULL,
            rarity  TEXT NOT NULL,
            PRIMARY KEY (user_id, ce_key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS active_ce_type (
            user_id INTEGER PRIMARY KEY,
            ce_key  TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_clans (
            user_id  INTEGER NOT NULL,
            clan_key TEXT NOT NULL,
            PRIMARY KEY (user_id, clan_key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS active_clan (
            user_id  INTEGER PRIMARY KEY,
            clan_key TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_heavenly (
            user_id      INTEGER NOT NULL,
            heavenly_key TEXT NOT NULL,
            PRIMARY KEY (user_id, heavenly_key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS active_heavenly (
            user_id      INTEGER PRIMARY KEY,
            heavenly_key TEXT NOT NULL
        )
    """)

    conn.commit()


# ---------------- Игроки ----------------

def get_or_create_player(user_id: int, username: str) -> sqlite3.Row:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO players (user_id, username, x, created_at, ce, max_ce, ce_control) "
            "VALUES (?, ?, 0, ?, ?, ?, ?)",
            (user_id, username, int(time.time()), MAX_CE_BASE, MAX_CE_BASE, CE_CONTROL_BASE),
        )
        conn.commit()
        cur.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    return row


def update_player_x(user_id: int, new_x: int):
    conn = get_conn()
    conn.execute("UPDATE players SET x = ? WHERE user_id = ?", (new_x, user_id))
    conn.commit()


def get_all_player_ids():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM players")
    return [row["user_id"] for row in cur.fetchall()]


def add_gold(user_id: int, amount: int):
    conn = get_conn()
    conn.execute("UPDATE players SET gold = gold + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()


def update_player_hp(user_id: int, hp: int):
    conn = get_conn()
    conn.execute("UPDATE players SET hp = ? WHERE user_id = ?", (hp, user_id))
    conn.commit()


def update_player_ce(user_id: int, ce: int):
    conn = get_conn()
    conn.execute("UPDATE players SET ce = ? WHERE user_id = ?", (ce, user_id))
    conn.commit()


def set_player_dmg_buff(user_id: int, turns: int, mult: float):
    conn = get_conn()
    conn.execute(
        "UPDATE players SET dmg_buff_turns = ?, dmg_buff_mult = ? WHERE user_id = ?",
        (turns, mult, user_id),
    )
    conn.commit()


def consume_player_dmg_buff(user_id: int) -> float:
    """Возвращает текущий множитель баффа урона и уменьшает его длительность на 1."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT dmg_buff_turns, dmg_buff_mult FROM players WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or row["dmg_buff_turns"] <= 0:
        return 1.0
    mult = row["dmg_buff_mult"]
    new_turns = row["dmg_buff_turns"] - 1
    if new_turns <= 0:
        conn.execute(
            "UPDATE players SET dmg_buff_turns = 0, dmg_buff_mult = 1.0 WHERE user_id = ?",
            (user_id,),
        )
    else:
        conn.execute("UPDATE players SET dmg_buff_turns = ? WHERE user_id = ?", (new_turns, user_id))
    conn.commit()
    return mult


def add_exp_and_level(user_id: int, amount: int):
    """
    Начисляет опыт, при необходимости повышает уровень.
    Растут HP, макс. ПЭ и Контроль ПЭ.
    Уровень не может превысить потолок по сюжету: 20 + 20 * (глав пройдено).
    Возвращает (новый_уровень, сколько_уровней_поднято).
    """
    from config import EXP_BASE, HP_PER_LEVEL, MAX_CE_PER_LEVEL, CE_CONTROL_PER_LEVEL
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT level, exp, max_hp, max_ce, ce_control FROM players WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    # Потолок уровня по сюжету (без импорта story.py, чтобы избежать цикличности).
    max_level = 20
    try:
        cur.execute("SELECT chapter_idx, finished FROM player_story WHERE user_id = ?", (user_id,))
        sr = cur.fetchone()
        if sr:
            completed = 6 if sr["finished"] else sr["chapter_idx"]
            max_level = 20 + 20 * completed
    except sqlite3.OperationalError:
        # Таблица player_story ещё не создана — считаем, что глав не пройдено.
        pass

    level, exp = row["level"], row["exp"] + amount
    max_hp, max_ce, ce_control = row["max_hp"], row["max_ce"], row["ce_control"]

    leveled = 0
    while exp >= level * EXP_BASE and level < max_level:
        exp -= level * EXP_BASE
        level += 1
        max_hp += HP_PER_LEVEL
        max_ce += MAX_CE_PER_LEVEL
        ce_control += CE_CONTROL_PER_LEVEL
        leveled += 1

    # Достигли капа — не позволяем опыту переполняться сверх порога.
    if level >= max_level:
        exp = min(exp, level * EXP_BASE - 1)

    if leveled:
        cur.execute(
            "UPDATE players SET level = ?, exp = ?, max_hp = ?, hp = ?, "
            "max_ce = ?, ce = ?, ce_control = ? WHERE user_id = ?",
            (level, exp, max_hp, max_hp, max_ce, max_ce, ce_control, user_id),
        )
    else:
        cur.execute("UPDATE players SET exp = ? WHERE user_id = ?", (exp, user_id))
    conn.commit()
    return level, leveled


# ---------------- Инвентарь ----------------

def add_item(user_id: int, item_name: str, rarity: str, quantity: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ? AND rarity = ?",
        (user_id, item_name, rarity),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
            (quantity, row["id"]),
        )
    else:
        cur.execute(
            "INSERT INTO inventory (user_id, item_name, rarity, quantity) VALUES (?, ?, ?, ?)",
            (user_id, item_name, rarity, quantity),
        )
    conn.commit()


def get_inventory(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT item_name, rarity, quantity FROM inventory WHERE user_id = ? ORDER BY rarity DESC",
        (user_id,),
    )
    return cur.fetchall()


# ---------------- Встречи с проклятиями ----------------

def set_encounter(user_id: int, district_id: str, monster: dict):
    conn = get_conn()
    conn.execute("DELETE FROM encounters WHERE user_id = ?", (user_id,))
    conn.execute(
        """INSERT INTO encounters
           (user_id, biome_id, monster_name, hp, max_hp, dmg_min, dmg_max, emoji, rarity,
            spawned_at, curse_class, drop_item, drop_rarity, stun_turns, bleed_turns, bleed_dmg,
            domain_key, domain_turns)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, 0)""",
        (
            user_id, district_id, monster["name"], monster["hp"], monster["hp"],
            monster["dmg_min"], monster["dmg_max"], monster["emoji"], monster["rarity"],
            int(time.time()), monster.get("curse_class", monster["rarity"]),
            monster.get("drop_item"), monster.get("drop_rarity"),
        ),
    )
    conn.commit()


def get_encounter(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM encounters WHERE user_id = ?", (user_id,))
    return cur.fetchone()


def clear_encounter(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM encounters WHERE user_id = ?", (user_id,))
    conn.commit()


def update_encounter_hp(user_id: int, hp: int):
    conn = get_conn()
    conn.execute("UPDATE encounters SET hp = ? WHERE user_id = ?", (hp, user_id))
    conn.commit()


def set_encounter_status(user_id: int, stun_turns: int = None, bleed_turns: int = None, bleed_dmg: int = None):
    """Частичное обновление статус-эффектов на проклятии (None = не менять)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT stun_turns, bleed_turns, bleed_dmg FROM encounters WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return
    new_stun = row["stun_turns"] if stun_turns is None else stun_turns
    new_bleed_turns = row["bleed_turns"] if bleed_turns is None else bleed_turns
    new_bleed_dmg = row["bleed_dmg"] if bleed_dmg is None else bleed_dmg
    conn.execute(
        "UPDATE encounters SET stun_turns = ?, bleed_turns = ?, bleed_dmg = ? WHERE user_id = ?",
        (new_stun, new_bleed_turns, new_bleed_dmg, user_id),
    )
    conn.commit()


# ---------------- Расширения Территории (домены) ----------------

def set_domain(user_id: int, domain_key: str, turns: int):
    """Активирует домен на N ходов у текущего encounter-а."""
    conn = get_conn()
    conn.execute(
        "UPDATE encounters SET domain_key = ?, domain_turns = ? WHERE user_id = ?",
        (domain_key, turns, user_id),
    )
    conn.commit()


def get_domain(user_id: int) -> tuple[str | None, int]:
    """Возвращает (domain_key, turns). Если домен не активен — (None, 0)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT domain_key, domain_turns FROM encounters WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return (None, 0)
    return (row["domain_key"], row["domain_turns"] or 0)


def decrement_domain(user_id: int) -> tuple[str | None, int]:
    """Уменьшает счётчик ходов домена на 1. Возвращает новое состояние."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT domain_key, domain_turns FROM encounters WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row["domain_key"]:
        return (None, 0)
    new_turns = max(0, (row["domain_turns"] or 0) - 1)
    if new_turns == 0:
        conn.execute(
            "UPDATE encounters SET domain_key = NULL, domain_turns = 0 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
        return (None, 0)
    conn.execute(
        "UPDATE encounters SET domain_turns = ? WHERE user_id = ?",
        (new_turns, user_id),
    )
    conn.commit()
    return (row["domain_key"], new_turns)


def clear_domain(user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE encounters SET domain_key = NULL, domain_turns = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()


# ---------------- Врождённые техники ----------------

def add_player_technique(user_id: int, technique_name: str, rarity: str) -> bool:
    """Добавляет технику в коллекцию. Возвращает False, если уже была изучена."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO player_techniques (user_id, technique_name, rarity) VALUES (?, ?, ?)",
            (user_id, technique_name, rarity),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_player_techniques(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT technique_name, rarity FROM player_techniques WHERE user_id = ? ORDER BY rarity DESC",
        (user_id,),
    )
    return cur.fetchall()


def has_technique(user_id: int, technique_name: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_techniques WHERE user_id = ? AND technique_name = ?",
        (user_id, technique_name),
    )
    return cur.fetchone() is not None


def get_equipped_techniques(user_id: int):
    """Список [(slot, technique_name), ...] отсортированный по слоту."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT slot, technique_name FROM equipped_techniques WHERE user_id = ? ORDER BY slot",
        (user_id,),
    )
    return cur.fetchall()


def equip_technique(user_id: int, slot: int, technique_name: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO equipped_techniques (user_id, slot, technique_name) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, slot) DO UPDATE SET technique_name = excluded.technique_name",
        (user_id, slot, technique_name),
    )
    conn.commit()


def unequip_technique(user_id: int, slot: int):
    conn = get_conn()
    conn.execute("DELETE FROM equipped_techniques WHERE user_id = ? AND slot = ?", (user_id, slot))
    conn.commit()


# ---------------- Инвентарь: подсчёт и списание ----------------

def count_item(user_id: int, item_name: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory WHERE user_id = ? AND item_name = ?",
        (user_id, item_name),
    )
    return cur.fetchone()["total"]


def consume_item(user_id: int, item_name: str, quantity: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ? ORDER BY quantity DESC",
        (user_id, item_name),
    )
    remaining = quantity
    for row in cur.fetchall():
        if remaining <= 0:
            break
        if row["quantity"] <= remaining:
            remaining -= row["quantity"]
            conn.execute("DELETE FROM inventory WHERE id = ?", (row["id"],))
        else:
            conn.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE id = ?",
                (remaining, row["id"]),
            )
            remaining = 0
    conn.commit()


# ============================================================
#  ОРУЖИЕ
# ============================================================

def add_player_weapon(user_id: int, weapon_name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO player_weapons (user_id, weapon_name, acquired_at) "
        "VALUES (?, ?, ?)",
        (user_id, weapon_name, int(time.time())),
    )
    conn.commit()


def has_weapon(user_id: int, weapon_name: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_weapons WHERE user_id = ? AND weapon_name = ?",
        (user_id, weapon_name),
    )
    return cur.fetchone() is not None


def get_player_weapons(user_id: int) -> list[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT weapon_name FROM player_weapons WHERE user_id = ? ORDER BY acquired_at",
        (user_id,),
    )
    return [row["weapon_name"] for row in cur.fetchall()]


def set_equipped_weapon(user_id: int, weapon_name: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO equipped_weapon (user_id, weapon_name) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET weapon_name = excluded.weapon_name",
        (user_id, weapon_name),
    )
    conn.commit()


def clear_equipped_weapon(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM equipped_weapon WHERE user_id = ?", (user_id,))
    conn.commit()


def get_equipped_weapon_name(user_id: int) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT weapon_name FROM equipped_weapon WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["weapon_name"] if row else None


# ============================================================
#  БАФФЫ
# ============================================================

def add_player_buff(user_id: int, stat: str, value: float, duration_seconds: int):
    """Перезаписывает бафф того же стата (обновляет значение и время)."""
    conn = get_conn()
    expires_at = int(time.time()) + duration_seconds
    conn.execute(
        "INSERT INTO player_buffs (user_id, stat, value, expires_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, stat) DO UPDATE SET "
        "value = excluded.value, expires_at = excluded.expires_at",
        (user_id, stat, value, expires_at),
    )
    conn.commit()


def get_active_buffs(user_id: int) -> list[dict]:
    """Возвращает активные баффы, заодно удаляя истёкшие."""
    conn = get_conn()
    now = int(time.time())
    conn.execute(
        "DELETE FROM player_buffs WHERE user_id = ? AND expires_at <= ?",
        (user_id, now),
    )
    conn.commit()
    cur = conn.cursor()
    cur.execute(
        "SELECT stat, value, expires_at FROM player_buffs WHERE user_id = ? AND expires_at > ?",
        (user_id, now),
    )
    return [
        {"stat": r["stat"], "value": r["value"], "expires_at": r["expires_at"],
         "seconds_left": r["expires_at"] - now}
        for r in cur.fetchall()
    ]


def get_buff_value(user_id: int, stat: str) -> float:
    """0.0, если баффа нет."""
    for b in get_active_buffs(user_id):
        if b["stat"] == stat:
            return b["value"]
    return 0.0


def clear_expired_buffs() -> int:
    """Удаляет все истёкшие баффы у всех игроков. Возвращает число удалённых."""
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("DELETE FROM player_buffs WHERE expires_at <= ?", (now,))
    conn.commit()
    return cur.rowcount


# ============================================================
#  PITY-СИСТЕМА ГАЧИ
# ============================================================

def get_pity(user_id: int) -> int:
    """Сколько круток подряд прошло без легендарки/мифика."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pity_count FROM player_pity WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["pity_count"] if row else 0


def inc_pity(user_id: int) -> int:
    """Увеличивает счётчик pity на 1. Возвращает новое значение."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO player_pity (user_id, pity_count) VALUES (?, 1) "
        "ON CONFLICT(user_id) DO UPDATE SET pity_count = pity_count + 1",
        (user_id,),
    )
    conn.commit()
    return get_pity(user_id)


def reset_pity(user_id: int):
    """Сбрасывает pity после выпадения легендарки/мифика."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO player_pity (user_id, pity_count) VALUES (?, 0) "
        "ON CONFLICT(user_id) DO UPDATE SET pity_count = 0",
        (user_id,),
    )
    conn.commit()


# ============================================================
#  VIP
# ============================================================

def get_vip_until(user_id: int) -> int:
    """unix-time окончания VIP или 0, если VIP нет."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM player_vip WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return 0
    if row["expires_at"] <= int(time.time()):
        return 0
    return row["expires_at"]


def has_vip(user_id: int) -> bool:
    return get_vip_until(user_id) > 0


def vip_mult(user_id: int) -> float:
    """Множитель наград: 2.0 для VIP, иначе 1.0.
    Используется в combat, raid, quests, story."""
    return 2.0 if has_vip(user_id) else 1.0


def add_vip_days(user_id: int, days: int):
    """Добавляет дни VIP. Если VIP активен — продлевает от текущей даты окончания."""
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT expires_at FROM player_vip WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    base = max(now, row["expires_at"] if row else 0)
    new_expires = base + days * 86400
    conn.execute(
        "INSERT INTO player_vip (user_id, expires_at) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
        (user_id, new_expires),
    )
    conn.commit()


# ============================================================
#  ТИПЫ ПЭ
# ============================================================

def add_ce_type(user_id: int, ce_key: str, rarity: str) -> bool:
    """True — если новый. False — если уже был."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO player_ce_types (user_id, ce_key, rarity) VALUES (?, ?, ?)",
            (user_id, ce_key, rarity),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_ce_types(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT ce_key, rarity FROM player_ce_types WHERE user_id = ? ORDER BY rarity DESC",
        (user_id,),
    )
    return cur.fetchall()


def has_ce_type(user_id: int, ce_key: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_ce_types WHERE user_id = ? AND ce_key = ?",
        (user_id, ce_key),
    )
    return cur.fetchone() is not None


def set_active_ce_type(user_id: int, ce_key: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO active_ce_type (user_id, ce_key) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET ce_key = excluded.ce_key",
        (user_id, ce_key),
    )
    conn.commit()


def clear_active_ce_type(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM active_ce_type WHERE user_id = ?", (user_id,))
    conn.commit()


def get_active_ce_type(user_id: int) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ce_key FROM active_ce_type WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["ce_key"] if row else None


# ============================================================
#  КЛАНЫ
# ============================================================

def add_clan(user_id: int, clan_key: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO player_clans (user_id, clan_key) VALUES (?, ?)",
            (user_id, clan_key),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_clans(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT clan_key FROM player_clans WHERE user_id = ? ORDER BY clan_key",
        (user_id,),
    )
    return cur.fetchall()


def has_clan(user_id: int, clan_key: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_clans WHERE user_id = ? AND clan_key = ?",
        (user_id, clan_key),
    )
    return cur.fetchone() is not None


def set_active_clan(user_id: int, clan_key: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO active_clan (user_id, clan_key) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET clan_key = excluded.clan_key",
        (user_id, clan_key),
    )
    conn.commit()


def clear_active_clan(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM active_clan WHERE user_id = ?", (user_id,))
    conn.commit()


def get_active_clan(user_id: int) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT clan_key FROM active_clan WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["clan_key"] if row else None


# ============================================================
#  ПРОКЛЯТИЯ НЕБЕС
# ============================================================

def add_heavenly_restriction(user_id: int, heavenly_key: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO player_heavenly (user_id, heavenly_key) VALUES (?, ?)",
            (user_id, heavenly_key),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_heavenly_restrictions(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT heavenly_key FROM player_heavenly WHERE user_id = ? ORDER BY heavenly_key",
        (user_id,),
    )
    return cur.fetchall()


def has_heavenly_restriction(user_id: int, heavenly_key: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM player_heavenly WHERE user_id = ? AND heavenly_key = ?",
        (user_id, heavenly_key),
    )
    return cur.fetchone() is not None


def set_active_heavenly(user_id: int, heavenly_key: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO active_heavenly (user_id, heavenly_key) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET heavenly_key = excluded.heavenly_key",
        (user_id, heavenly_key),
    )
    conn.commit()


def clear_active_heavenly(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM active_heavenly WHERE user_id = ?", (user_id,))
    conn.commit()


def get_active_heavenly(user_id: int) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT heavenly_key FROM active_heavenly WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row["heavenly_key"] if row else None
