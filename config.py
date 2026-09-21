"""
Конфигурация бота «Магическая Битва: Токио» (Jujutsu Kaisen RPG).

Токен BOT_TOKEN передаётся через переменные окружения хостинга
(Bothost задаёт его автоматически). Локально можно задать вручную:
    Windows (cmd):     set BOT_TOKEN=ваш_токен
    Linux/macOS:       export BOT_TOKEN=ваш_токен
"""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN не задан. На Bothost добавь переменную окружения "
        "BOT_TOKEN в панели управления. Локально задай её через "
        "set BOT_TOKEN=... (Windows) или export BOT_TOKEN=... (Linux/macOS)."
    )

DB_PATH = "data/game.db"

# --- Мир и перемещение ---
MAX_WORLD = 1000
WORLD_STEP_PER_LEVEL = 50
MOVE_STEP = 10


def get_world_bounds(level: int) -> tuple[int, int]:
    max_x = min(WORLD_STEP_PER_LEVEL * level, MAX_WORLD)
    return -max_x, max_x

# --- Патрулирование ---
SPAWN_INTERVAL_SECONDS = 90
SPAWN_CHANCE = 0.35
PATROL_CHANCE = 0.55
ENCOUNTER_TTL_SECONDS = 60 * 6

# --- Классы проклятий ---
CURSE_CLASSES = ["Особый класс", "1-й класс", "2-й класс", "3-й класс", "4-й класс"]

CLASS_EMOJI = {
    "Особый класс": "⛔",
    "1-й класс": "🟥",
    "2-й класс": "🟦",
    "3-й класс": "🔷",
    "4-й класс": "🔹",
}

CLASS_TO_DROP_RARITY = {
    "Особый класс": "легендарный",
    "1-й класс": "эпический",
    "2-й класс": "редкий",
    "3-й класс": "необычный",
    "4-й класс": "обычный",
}

RARITY_EMOJI = {
    "обычный": "⚪",
    "необычный": "🟢",
    "редкий": "🔵",
    "эпический": "🟣",
    "легендарный": "🟠",
}

# --- Прогрессия персонажа ---
HP_PER_LEVEL = 10
EXP_BASE = 50
CE_CONTROL_BASE = 10
CE_CONTROL_PER_LEVEL = 3
MAX_CE_BASE = 40
MAX_CE_PER_LEVEL = 6

# --- Боевые формулы ---
PLAYER_BASE_DMG_MIN = 3
PLAYER_BASE_DMG_MAX = 6
PHYS_CE_COEF = 0.6
# ВАЖНО: было 0.05 — из-за этого игрок на высоком уровне ваншотил боссов.
# Порезано до 0.035, чтобы кривая урона не улетала в космос.
TECH_CE_COEF = 0.035
DEFENSE_CE_COEF = 0.006
DEFENSE_CAP = 0.65
CE_REGEN_BASE = 2
CE_REGEN_CE_COEF = 0.15

# --- Криты ---
PLAYER_CRIT_CHANCE = 0.08
PLAYER_CRIT_MULT = 2.0
BLACK_FLASH_STUN_CHANCE = 0.25
PLAYER_MISS_CHANCE = 0.10
MONSTER_MISS_CHANCE = 0.15
FLEE_CHANCE = 0.55

# --- Награды (уменьшено на 10% для гринда) ---
GOLD_PER_HP = 0.225
EXP_PER_HP = 0.34
DROP_CHANCE = 0.55
DEATH_GOLD_LOSS = 0.25

# --- Масштаб проклятий по превышению уровня района ---
LEVEL_SCALE_PER_EXCESS = 0.03
LEVEL_SCALE_CAP = 2.0
LEVEL_SCALE_REWARD_COEF = 0.5

# --- Баланс боссов: процентная защита от превышения уровня ---
# Если игрок выше min_level главы на N уровней, броня босса растёт на
# N * BOSS_DEFENSE_LEVEL_SCALE, до BOSS_DEFENSE_CAP.
# Так максимально раскачанный игрок не ваншотит сюжетного босса,
# но и не страдает сверх меры.
BOSS_DEFENSE_LEVEL_SCALE = 0.004
BOSS_DEFENSE_CAP = 0.75

# --- Боевой клуб Хакари (босс-раш) ---
# Открывается после прохождения N-й главы сюжета.
BOSS_RUSH_UNLOCK_CHAPTER = 5
# Цена входа в бой (💠).
BOSS_RUSH_ENTRY_COST = 50
# Кулдаун между боями в клубе (секунды).
BOSS_RUSH_COOLDOWN = 120
# Множители боссов боевого клуба относительно сюжетных:
# HP ×2 (усилен), урон ×1.3, НО защита = 0 (можно ваншотнуть).
BOSS_RUSH_HP_MULT = 2.0
BOSS_RUSH_DMG_MULT = 1.3
# Награда — 25% от сюжетной, чтобы не ломать экономику.
BOSS_RUSH_REWARD_MULT = 0.25

# --- Гача врождённых техник ---
GACHA_ROLL_COST = 60
GACHA_ROLL_COST_X10 = 540

GACHA_RARITY_WEIGHTS = {
    "Обычная": 70.0,
    "Редкая": 22.0,
    "Эпическая": 7.0,
    "Мифическая": 0.8,
    "Легендарная (Особый класс)": 0.2,
}

GACHA_RARITY_EMOJI = {
    "Обычная": "⚪",
    "Редкая": "🔵",
    "Эпическая": "🟣",
    "Мифическая": "🟡",
    "Легендарная (Особый класс)": "🟠",
}

MAX_EQUIPPED_TECHNIQUES = 3

# --- Pity-система ---
GACHA_PITY_LIMIT = 50
GACHA_PITY_LEGEND_WEIGHT = 80
GACHA_PITY_MYTH_WEIGHT = 20

# --- VIP ---
VIP_PRICE_STARS = 100
VIP_DURATION_DAYS = 30
VIP_REWARD_MULT = 2.0
VIP_PAYLOAD = "vip_30_days"

# --- Расширения Территории ---
DOMAIN_UNLOCK_USES = 20

# --- Донат (звёзды → 💠) ---
DONATE_RATE = 3
DONATE_PAYLOAD_PREFIX = "donate_"

DONATE_PACKAGES = {
    "small": {
        "emoji": "🥉", "name": "Малый",
        "stars": 10, "currency": 30, "bonus_pct": 0,
    },
    "medium": {
        "emoji": "🥈", "name": "Средний",
        "stars": 50, "currency": 180, "bonus_pct": 20,
    },
    "large": {
        "emoji": "🥇", "name": "Большой",
        "stars": 150, "currency": 600, "bonus_pct": 33,
    },
    "huge": {
        "emoji": "💎", "name": "Гигантский",
        "stars": 500, "currency": 2250, "bonus_pct": 50,
    },
}
