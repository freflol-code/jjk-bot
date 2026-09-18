"""
quests.py — ежедневные и еженедельные задания от Годжо Сатору.

Пул: 30 ежедневных (QUESTS_DAILY) + 30 еженедельных (QUESTS_WEEKLY).
Каждому игроку на текущий день/неделю случайно выдаётся
DAILY_COUNT / WEEKLY_COUNT заданий из пула (без повторов).
Выбор детерминирован по (user_id, period_key) — перезапуск бота
не «переиграет» уже выданный набор.

Прогресс копится через теги. Внешний код (combat.py, main.py, shop.py,
gacha.py, consumables.py, bosses.py) вызывает:

    quests.add_progress(user_id, tag, target=..., amount=...)

и получает список только что завершённых (ещё не забранных) заданий,
чтобы показать игроку уведомление.

Бонус: когда игрок забирает ВСЕ недельные задания — ему один раз за неделю
выдаётся «📜 Свиток опыта Годжо» (+500 опыта, см. consumables.py).

VIP: даёт ×2 к золоту и опыту за задания (ежедневные и еженедельные).

Используемые теги (target в скобках):
    patrol_start                       — старт боя через Патрулирование
    kill            (класс проклятия)  — победа над проклятием
    boss_kill                          — победа над боссом Особого класса
    summon                             — призыв босса ритуальной печатью
    tech_use                           — использование врождённой техники
    crit                               — критический удар
    bleed_apply                        — наложено кровотечение
    stun_apply                         — наложен стан
    consumable_use                     — использован расходник
    buy                                — покупка у Хакари
    sell                               — продажа трофея
    gacha_roll                         — крутка гачи техник
    gold_earn                          — заработано очков Ассоциации
    exp_earn                           — заработано опыта
    level_up                           — новый уровень
    move                               — шаг по карте
    district_change                    — переход между районами
    visit_district  (district_id)      — заход в конкретный район
    flee                               — успешный побег из боя
"""
import datetime
import random

import database


DAILY_COUNT = 3
WEEKLY_COUNT = 3


# ==================================================================
#  ЕЖЕДНЕВНЫЕ ЗАДАНИЯ (30 штук)
# ==================================================================

QUESTS_DAILY = {
    # --- патрулирование ---
    "d_patrol_3": {
        "emoji": "🩸", "name": "Первый выход",
        "desc": "Начни 3 боя через Патрулирование",
        "tag": "patrol_start", "goal": 3,
        "reward_gold": 40, "reward_exp": 30,
    },
    "d_patrol_5": {
        "emoji": "🚨", "name": "Ночная смена",
        "desc": "Начни 5 боёв через Патрулирование",
        "tag": "patrol_start", "goal": 5,
        "reward_gold": 70, "reward_exp": 55,
    },

    # --- массовые изгнания ---
    "d_kill_3": {
        "emoji": "🗡", "name": "Разминка",
        "desc": "Изгони 3 проклятия",
        "tag": "kill", "goal": 3,
        "reward_gold": 35, "reward_exp": 25,
    },
    "d_kill_5": {
        "emoji": "⚔️", "name": "Уборка района",
        "desc": "Изгони 5 проклятий",
        "tag": "kill", "goal": 5,
        "reward_gold": 60, "reward_exp": 45,
    },
    "d_kill_8": {
        "emoji": "💀", "name": "Полная зачистка",
        "desc": "Изгони 8 проклятий",
        "tag": "kill", "goal": 8,
        "reward_gold": 100, "reward_exp": 80,
    },

    # --- по классам ---
    "d_kill_c4_3": {
        "emoji": "🔹", "name": "Мелочь под ногами",
        "desc": "Изгони 3 проклятия 4-го класса",
        "tag": "kill", "target": "4-й класс", "goal": 3,
        "reward_gold": 30, "reward_exp": 20,
    },
    "d_kill_c3_2": {
        "emoji": "🔷", "name": "Уже интереснее",
        "desc": "Изгони 2 проклятия 3-го класса",
        "tag": "kill", "target": "3-й класс", "goal": 2,
        "reward_gold": 45, "reward_exp": 35,
    },
    "d_kill_c2_2": {
        "emoji": "🟦", "name": "Серьёзный противник",
        "desc": "Изгони 2 проклятия 2-го класса",
        "tag": "kill", "target": "2-й класс", "goal": 2,
        "reward_gold": 70, "reward_exp": 55,
    },
    "d_kill_c1_1": {
        "emoji": "🟥", "name": "Мини-босс дня",
        "desc": "Изгони мини-босса 1-го класса",
        "tag": "kill", "target": "1-й класс", "goal": 1,
        "reward_gold": 120, "reward_exp": 90,
    },

    # --- техники ---
    "d_tech_3": {
        "emoji": "🌀", "name": "Разомнись",
        "desc": "Используй врождённые техники 3 раза",
        "tag": "tech_use", "goal": 3,
        "reward_gold": 35, "reward_exp": 30,
    },
    "d_tech_6": {
        "emoji": "💠", "name": "Поток энергии",
        "desc": "Используй врождённые техники 6 раз",
        "tag": "tech_use", "goal": 6,
        "reward_gold": 70, "reward_exp": 60,
    },

    # --- криты ---
    "d_crit_2": {
        "emoji": "💥", "name": "Точный удар",
        "desc": "Нанеси 2 критических удара",
        "tag": "crit", "goal": 2,
        "reward_gold": 35, "reward_exp": 25,
    },
    "d_crit_4": {
        "emoji": "🎯", "name": "Снайпер",
        "desc": "Нанеси 4 критических удара",
        "tag": "crit", "goal": 4,
        "reward_gold": 65, "reward_exp": 50,
    },

    # --- эффекты ---
    "d_bleed_2": {
        "emoji": "🩸", "name": "Кровопуск",
        "desc": "Наложи кровотечение 2 раза",
        "tag": "bleed_apply", "goal": 2,
        "reward_gold": 40, "reward_exp": 30,
    },
    "d_stun_2": {
        "emoji": "😵", "name": "Оглуши и добей",
        "desc": "Оглуши проклятие 2 раза",
        "tag": "stun_apply", "goal": 2,
        "reward_gold": 45, "reward_exp": 35,
    },

    # --- расходники ---
    "d_consumable_1": {
        "emoji": "🧪", "name": "Перекус",
        "desc": "Используй расходник",
        "tag": "consumable_use", "goal": 1,
        "reward_gold": 20, "reward_exp": 15,
    },
    "d_consumable_3": {
        "emoji": "🍙", "name": "Плотный обед",
        "desc": "Используй 3 расходника",
        "tag": "consumable_use", "goal": 3,
        "reward_gold": 45, "reward_exp": 35,
    },

    # --- магазин ---
    "d_buy_1": {
        "emoji": "🛒", "name": "Закупка",
        "desc": "Купи что-нибудь у Хакари",
        "tag": "buy", "goal": 1,
        "reward_gold": 20, "reward_exp": 15,
    },
    "d_sell_1": {
        "emoji": "💰", "name": "Скупщик",
        "desc": "Продай трофей Хакари",
        "tag": "sell", "goal": 1,
        "reward_gold": 25, "reward_exp": 15,
    },

    # --- гача ---
    "d_gacha_1": {
        "emoji": "🎰", "name": "Проверь удачу",
        "desc": "Сделай 1 крутку гачи техник",
        "tag": "gacha_roll", "goal": 1,
        "reward_gold": 30, "reward_exp": 20,
    },
    "d_gacha_3": {
        "emoji": "🎲", "name": "Азартный день",
        "desc": "Сделай 3 крутки гачи техник",
        "tag": "gacha_roll", "goal": 3,
        "reward_gold": 70, "reward_exp": 50,
    },

    # --- экономика ---
    "d_gold_150": {
        "emoji": "💠", "name": "Рабочая смена",
        "desc": "Заработай 150 очков Ассоциации",
        "tag": "gold_earn", "goal": 150,
        "reward_gold": 40, "reward_exp": 30,
    },
    "d_gold_300": {
        "emoji": "💎", "name": "Хороший день",
        "desc": "Заработай 300 очков Ассоциации",
        "tag": "gold_earn", "goal": 300,
        "reward_gold": 80, "reward_exp": 60,
    },
    "d_exp_200": {
        "emoji": "🧬", "name": "Рост над собой",
        "desc": "Получи 200 опыта",
        "tag": "exp_earn", "goal": 200,
        "reward_gold": 60, "reward_exp": 40,
    },

    # --- боссы ---
    "d_summon_1": {
        "emoji": "⚡", "name": "Ритуал",
        "desc": "Призови босса Особого класса ритуальной печатью",
        "tag": "summon", "goal": 1,
        "reward_gold": 100, "reward_exp": 80,
    },

    # --- движение ---
    "d_move_5": {
        "emoji": "👣", "name": "Прогулка",
        "desc": "Пройди 5 шагов по Токио",
        "tag": "move", "goal": 5,
        "reward_gold": 20, "reward_exp": 15,
    },
    "d_move_10": {
        "emoji": "🚶", "name": "Дальний рейд",
        "desc": "Пройди 10 шагов по Токио",
        "tag": "move", "goal": 10,
        "reward_gold": 40, "reward_exp": 30,
    },
    "d_district_change_3": {
        "emoji": "🌆", "name": "Курьер",
        "desc": "Перейди между районами 3 раза",
        "tag": "district_change", "goal": 3,
        "reward_gold": 45, "reward_exp": 35,
    },

    # --- побег ---
    "d_flee_1": {
        "emoji": "🏃", "name": "Тактика отступления",
        "desc": "Сбеги из боя",
        "tag": "flee", "goal": 1,
        "reward_gold": 25, "reward_exp": 20,
    },

    # --- уровень ---
    "d_levelup_1": {
        "emoji": "🎉", "name": "Шаг вверх",
        "desc": "Повысь уровень 1 раз",
        "tag": "level_up", "goal": 1,
        "reward_gold": 80, "reward_exp": 60,
    },
}


# ==================================================================
#  ЕЖЕНЕДЕЛЬНЫЕ ЗАДАНИЯ (30 штук)
# ==================================================================

QUESTS_WEEKLY = {
    # --- патрулирование ---
    "w_patrol_20": {
        "emoji": "🩸", "name": "Плотный график",
        "desc": "Начни 20 боёв через Патрулирование",
        "tag": "patrol_start", "goal": 20,
        "reward_gold": 220, "reward_exp": 160,
    },
    "w_patrol_40": {
        "emoji": "🚨", "name": "Без выходных",
        "desc": "Начни 40 боёв через Патрулирование",
        "tag": "patrol_start", "goal": 40,
        "reward_gold": 400, "reward_exp": 300,
    },

    # --- массовые изгнания ---
    "w_kill_15": {
        "emoji": "🗡", "name": "Рабочая неделя",
        "desc": "Изгони 15 проклятий",
        "tag": "kill", "goal": 15,
        "reward_gold": 180, "reward_exp": 130,
    },
    "w_kill_30": {
        "emoji": "⚔️", "name": "Гроза района",
        "desc": "Изгони 30 проклятий",
        "tag": "kill", "goal": 30,
        "reward_gold": 320, "reward_exp": 240,
    },
    "w_kill_50": {
        "emoji": "💀", "name": "Легенда Ассоциации",
        "desc": "Изгони 50 проклятий",
        "tag": "kill", "goal": 50,
        "reward_gold": 500, "reward_exp": 380,
    },

    # --- по классам ---
    "w_kill_c4_15": {
        "emoji": "🔹", "name": "Мелкая работа",
        "desc": "Изгони 15 проклятий 4-го класса",
        "tag": "kill", "target": "4-й класс", "goal": 15,
        "reward_gold": 150, "reward_exp": 110,
    },
    "w_kill_c3_10": {
        "emoji": "🔷", "name": "Середняки",
        "desc": "Изгони 10 проклятий 3-го класса",
        "tag": "kill", "target": "3-й класс", "goal": 10,
        "reward_gold": 180, "reward_exp": 130,
    },
    "w_kill_c2_7": {
        "emoji": "🟦", "name": "Опасная работа",
        "desc": "Изгони 7 проклятий 2-го класса",
        "tag": "kill", "target": "2-й класс", "goal": 7,
        "reward_gold": 240, "reward_exp": 180,
    },
    "w_kill_c1_3": {
        "emoji": "🟥", "name": "Охотник на мини-боссов",
        "desc": "Изгони 3 проклятия 1-го класса",
        "tag": "kill", "target": "1-й класс", "goal": 3,
        "reward_gold": 380, "reward_exp": 280,
    },
    "w_kill_special_1": {
        "emoji": "⛔", "name": "Особое задание",
        "desc": "Изгони босса Особого класса",
        "tag": "kill", "target": "Особый класс", "goal": 1,
        "reward_gold": 500, "reward_exp": 400,
    },

    # --- боссы ---
    "w_boss_kill_1": {
        "emoji": "👑", "name": "Гроза боссов",
        "desc": "Изгони 1 босса Особого класса",
        "tag": "boss_kill", "goal": 1,
        "reward_gold": 450, "reward_exp": 360,
    },
    "w_boss_kill_2": {
        "emoji": "🏆", "name": "Двойной трофей",
        "desc": "Изгони 2 боссов Особого класса",
        "tag": "boss_kill", "goal": 2,
        "reward_gold": 750, "reward_exp": 560,
    },

    # --- техники ---
    "w_tech_25": {
        "emoji": "🌀", "name": "Мастер техник",
        "desc": "Используй врождённые техники 25 раз",
        "tag": "tech_use", "goal": 25,
        "reward_gold": 250, "reward_exp": 200,
    },
    "w_tech_50": {
        "emoji": "💠", "name": "Безграничная ПЭ",
        "desc": "Используй врождённые техники 50 раз",
        "tag": "tech_use", "goal": 50,
        "reward_gold": 450, "reward_exp": 350,
    },

    # --- криты ---
    "w_crit_15": {
        "emoji": "💥", "name": "Хирург",
        "desc": "Нанеси 15 критических ударов",
        "tag": "crit", "goal": 15,
        "reward_gold": 220, "reward_exp": 170,
    },

    # --- эффекты ---
    "w_bleed_10": {
        "emoji": "🩸", "name": "Кровавая неделя",
        "desc": "Наложи кровотечение 10 раз",
        "tag": "bleed_apply", "goal": 10,
        "reward_gold": 200, "reward_exp": 150,
    },
    "w_stun_10": {
        "emoji": "😵", "name": "Паралич воли",
        "desc": "Оглуши проклятие 10 раз",
        "tag": "stun_apply", "goal": 10,
        "reward_gold": 220, "reward_exp": 170,
    },

    # --- расходники ---
    "w_consumable_10": {
        "emoji": "🧪", "name": "Аптечка",
        "desc": "Используй 10 расходников",
        "tag": "consumable_use", "goal": 10,
        "reward_gold": 150, "reward_exp": 110,
    },

    # --- магазин ---
    "w_buy_5": {
        "emoji": "🛒", "name": "Постоянный клиент",
        "desc": "Купи 5 предметов у Хакари",
        "tag": "buy", "goal": 5,
        "reward_gold": 120, "reward_exp": 90,
    },
    "w_sell_5": {
        "emoji": "💰", "name": "Поставщик трофеев",
        "desc": "Продай 5 трофеев Хакари",
        "tag": "sell", "goal": 5,
        "reward_gold": 150, "reward_exp": 110,
    },

    # --- гача ---
    "w_gacha_5": {
        "emoji": "🎰", "name": "Игрок",
        "desc": "Сделай 5 круток гачи техник",
        "tag": "gacha_roll", "goal": 5,
        "reward_gold": 180, "reward_exp": 140,
    },
    "w_gacha_15": {
        "emoji": "🎲", "name": "Азартный до предела",
        "desc": "Сделай 15 круток гачи техник",
        "tag": "gacha_roll", "goal": 15,
        "reward_gold": 420, "reward_exp": 320,
    },

    # --- экономика ---
    "w_gold_1500": {
        "emoji": "💠", "name": "Казна района",
        "desc": "Заработай 1500 очков Ассоциации",
        "tag": "gold_earn", "goal": 1500,
        "reward_gold": 300, "reward_exp": 220,
    },
    "w_gold_3000": {
        "emoji": "💎", "name": "Спонсор Ассоциации",
        "desc": "Заработай 3000 очков Ассоциации",
        "tag": "gold_earn", "goal": 3000,
        "reward_gold": 600, "reward_exp": 440,
    },
    "w_exp_1500": {
        "emoji": "🧬", "name": "Путь мага",
        "desc": "Получи 1500 опыта",
        "tag": "exp_earn", "goal": 1500,
        "reward_gold": 350, "reward_exp": 260,
    },

    # --- боссы ---
    "w_summon_3": {
        "emoji": "⚡", "name": "Ритуалист",
        "desc": "Призови 3 боссов ритуальными печатями",
        "tag": "summon", "goal": 3,
        "reward_gold": 400, "reward_exp": 320,
    },
    "w_summon_5": {
        "emoji": "🔮", "name": "Повелитель печатей",
        "desc": "Призови 5 боссов ритуальными печатями",
        "tag": "summon", "goal": 5,
        "reward_gold": 650, "reward_exp": 500,
    },

    # --- движение ---
    "w_district_change_15": {
        "emoji": "🌆", "name": "Путешественник",
        "desc": "Перейди между районами 15 раз",
        "tag": "district_change", "goal": 15,
        "reward_gold": 200, "reward_exp": 160,
    },

    # --- уровень ---
    "w_levelup_2": {
        "emoji": "🎉", "name": "Двойной рост",
        "desc": "Повысь уровень 2 раза",
        "tag": "level_up", "goal": 2,
        "reward_gold": 350, "reward_exp": 260,
    },

    # --- побег ---
    "w_flee_3": {
        "emoji": "🏃", "name": "Мастер уклонения",
        "desc": "Сбеги из боя 3 раза",
        "tag": "flee", "goal": 3,
        "reward_gold": 150, "reward_exp": 120,
    },
}


# ==================================================================
#  НАСТРОЙКИ БОНУСА ЗА ВСЕ НЕДЕЛЬНЫЕ
# ==================================================================

WEEKLY_BONUS_ITEM = "📜 Свиток опыта Годжо"
WEEKLY_BONUS_RARITY = "расходник"


# ==================================================================
#  ВНУТРЕННЕЕ
# ==================================================================

_db_ready = False


def _ensure_tables():
    """Лениво создаёт таблицы заданий и бонусов."""
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_quests (
            user_id    INTEGER NOT NULL,
            period     TEXT    NOT NULL,
            period_key TEXT    NOT NULL,
            quest_id   TEXT    NOT NULL,
            progress   INTEGER NOT NULL DEFAULT 0,
            claimed    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, period, period_key, quest_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quest_bonuses (
            user_id    INTEGER NOT NULL,
            period     TEXT    NOT NULL,
            period_key TEXT    NOT NULL,
            bonus_id   TEXT    NOT NULL,
            PRIMARY KEY (user_id, period, period_key, bonus_id)
        )
    """)
    conn.commit()
    _db_ready = True


def _today_key() -> str:
    return datetime.date.today().isoformat()


def _week_key() -> str:
    iso = datetime.date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _period_key(period: str) -> str:
    return _today_key() if period == "daily" else _week_key()


def _pool(period: str) -> dict:
    return QUESTS_DAILY if period == "daily" else QUESTS_WEEKLY


def ensure_quests(user_id: int):
    """Выдаёт игроку набор заданий на текущий период, если ещё не выдан.
    Выбор детерминирован по (user_id, period, period_key) — реролла при
    перезапуске бота не будет."""
    _ensure_tables()
    conn = database.get_conn()
    cur = conn.cursor()
    for period, count in (("daily", DAILY_COUNT), ("weekly", WEEKLY_COUNT)):
        key = _period_key(period)
        cur.execute(
            "SELECT COUNT(*) AS c FROM player_quests "
            "WHERE user_id = ? AND period = ? AND period_key = ?",
            (user_id, period, key),
        )
        if cur.fetchone()["c"] > 0:
            continue
        pool = _pool(period)
        rng = random.Random(f"{user_id}:{period}:{key}")
        chosen = rng.sample(list(pool.keys()), count)
        for qid in chosen:
            cur.execute(
                "INSERT OR IGNORE INTO player_quests "
                "(user_id, period, period_key, quest_id, progress, claimed) "
                "VALUES (?, ?, ?, ?, 0, 0)",
                (user_id, period, key, qid),
            )
    conn.commit()


def _maybe_give_weekly_bonus(user_id: int) -> str | None:
    """Если все недельные задания текущей недели забраны — выдаёт
    «📜 Свиток опыта Годжо» ровно один раз за неделю.
    Возвращает название предмета, если выдали, иначе None."""
    _ensure_tables()
    key = _week_key()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM quest_bonuses "
        "WHERE user_id = ? AND period = 'weekly' AND period_key = ? AND bonus_id = 'all_weekly'",
        (user_id, key),
    )
    if cur.fetchone():
        return None  # уже выдавали на этой неделе

    weekly = get_quests(user_id, "weekly")
    if not weekly:
        return None
    if not all(q["claimed"] for q in weekly):
        return None  # ещё не все забраны

    database.add_item(user_id, WEEKLY_BONUS_ITEM, WEEKLY_BONUS_RARITY, 1)
    conn.execute(
        "INSERT OR IGNORE INTO quest_bonuses "
        "(user_id, period, period_key, bonus_id) VALUES (?, 'weekly', ?, 'all_weekly')",
        (user_id, key),
    )
    conn.commit()
    return WEEKLY_BONUS_ITEM


# ==================================================================
#  ПУБЛИЧНОЕ API
# ==================================================================

def get_quests(user_id: int, period: str) -> list[dict]:
    """Список активных заданий игрока на текущий период с прогрессом."""
    ensure_quests(user_id)
    conn = database.get_conn()
    cur = conn.cursor()
    key = _period_key(period)
    cur.execute(
        "SELECT quest_id, progress, claimed FROM player_quests "
        "WHERE user_id = ? AND period = ? AND period_key = ?",
        (user_id, period, key),
    )
    pool = _pool(period)
    result = []
    for row in cur.fetchall():
        q = pool.get(row["quest_id"])
        if not q:
            continue
        result.append({
            "id": row["quest_id"],
            "emoji": q["emoji"],
            "name": q["name"],
            "desc": q["desc"],
            "progress": row["progress"],
            "goal": q["goal"],
            "claimed": bool(row["claimed"]),
            "reward_gold": q["reward_gold"],
            "reward_exp": q["reward_exp"],
        })
    return result


def add_progress(user_id: int, tag: str, target: str | None = None,
                 amount: int = 1) -> list[dict]:
    """Двигает прогресс всех активных заданий с этим тегом.
    target — опциональное уточнение (класс проклятия, district_id и т.п.).
    Возвращает список ТОЛЬКО ЧТО завершённых (не забранных) заданий —
    чтобы вызывающий код мог показать игроку уведомление."""
    ensure_quests(user_id)
    conn = database.get_conn()
    cur = conn.cursor()
    completed = []
    for period in ("daily", "weekly"):
        key = _period_key(period)
        pool = _pool(period)
        cur.execute(
            "SELECT quest_id, progress, claimed FROM player_quests "
            "WHERE user_id = ? AND period = ? AND period_key = ?",
            (user_id, period, key),
        )
        for row in cur.fetchall():
            q = pool.get(row["quest_id"])
            if not q or q["tag"] != tag:
                continue
            if q.get("target") is not None and q["target"] != target:
                continue
            new_progress = min(q["goal"], row["progress"] + amount)
            if new_progress == row["progress"]:
                continue
            conn.execute(
                "UPDATE player_quests SET progress = ? "
                "WHERE user_id = ? AND period = ? AND period_key = ? AND quest_id = ?",
                (new_progress, user_id, period, key, row["quest_id"]),
            )
            if new_progress >= q["goal"] and not row["claimed"]:
                completed.append({
                    "period": period,
                    "id": row["quest_id"],
                    "emoji": q["emoji"],
                    "name": q["name"],
                    "reward_gold": q["reward_gold"],
                    "reward_exp": q["reward_exp"],
                })
    conn.commit()
    return completed


def claim(user_id: int, period: str, quest_id: str) -> dict:
    """Забрать награду за выполненное задание. VIP даёт ×2 к золоту и опыту."""
    ensure_quests(user_id)
    conn = database.get_conn()
    cur = conn.cursor()
    key = _period_key(period)
    cur.execute(
        "SELECT progress, claimed FROM player_quests "
        "WHERE user_id = ? AND period = ? AND period_key = ? AND quest_id = ?",
        (user_id, period, key, quest_id),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "msg": "Такого задания нет."}
    q = _pool(period).get(quest_id)
    if not q:
        return {"ok": False, "msg": "Задание не найдено."}
    if row["progress"] < q["goal"]:
        return {"ok": False, "msg": "Задание ещё не выполнено."}
    if row["claimed"]:
        return {"ok": False, "msg": "Награда уже получена."}

    vip = database.vip_mult(user_id)
    gold = int(q["reward_gold"] * vip)
    exp = int(q["reward_exp"] * vip)

    database.add_gold(user_id, gold)
    new_level, leveled = database.add_exp_and_level(user_id, exp)
    conn.execute(
        "UPDATE player_quests SET claimed = 1 "
        "WHERE user_id = ? AND period = ? AND period_key = ? AND quest_id = ?",
        (user_id, period, key, quest_id),
    )
    conn.commit()

    # проверяем бонус за все недельные задания
    bonus = _maybe_give_weekly_bonus(user_id) if period == "weekly" else None

    msg = f"✅ Награда получена: 💠 +{gold}, 🧬 +{exp}"
    if vip > 1.0:
        msg += " 💎 (VIP ×2)"
    if bonus:
        msg += f"\n\n🎁 <b>Все недельные задания закрыты!</b>\nТы получаешь {bonus} (+500 опыта)."
    if leveled:
        msg += f"\n🎉 <b>Уровень повышен до {new_level}!</b>"
    return {"ok": True, "msg": msg, "leveled": leveled, "new_level": new_level}


def claim_all_ready(user_id: int, period: str) -> dict:
    """Забрать все выполненные и незабранные награды периода разом. VIP ×2."""
    vip = database.vip_mult(user_id)
    total_gold = 0
    total_exp = 0
    count = 0
    leveled_to = None
    for q in get_quests(user_id, period):
        if q["claimed"] or q["progress"] < q["goal"]:
            continue
        res = claim(user_id, period, q["id"])
        if res["ok"]:
            total_gold += int(q["reward_gold"] * vip)
            total_exp += int(q["reward_exp"] * vip)
            count += 1
            if res.get("leveled"):
                leveled_to = res["new_level"]
    if count == 0:
        return {"ok": False, "msg": "Нечего забирать."}

    bonus = _maybe_give_weekly_bonus(user_id) if period == "weekly" else None

    msg = f"✅ Забрано заданий: {count}\n💠 +{total_gold}, 🧬 +{total_exp}"
    if vip > 1.0:
        msg += " 💎 (VIP ×2)"
    if bonus:
        msg += f"\n\n🎁 <b>Все недельные задания закрыты!</b>\nТы получаешь {bonus} (+500 опыта)."
    if leveled_to:
        msg += f"\n🎉 <b>Уровень повышен до {leveled_to}!</b>"
    return {"ok": True, "msg": msg}


def has_ready(user_id: int) -> bool:
    """True, если есть хоть одно завершённое и незабранное задание
    (для подсветки кнопки «Задания» в главном меню)."""
    for period in ("daily", "weekly"):
        for q in get_quests(user_id, period):
            if not q["claimed"] and q["progress"] >= q["goal"]:
                return True
    return False


# ==================================================================
#  UI-ХЕЛПЕРЫ
# ==================================================================

def _progress_bar(progress: int, goal: int, width: int = 10) -> str:
    filled = 0 if goal <= 0 else min(width, progress * width // goal)
    return "▰" * filled + "▱" * (width - filled)


def _line(q: dict) -> str:
    if q["claimed"]:
        status = "✅"
    elif q["progress"] >= q["goal"]:
        status = "🎁"
    else:
        status = "⏳"
    bar = _progress_bar(q["progress"], q["goal"])
    return (
        f"{status} {q['emoji']} <b>{q['name']}</b>\n"
        f"   <i>{q['desc']}</i>\n"
        f"   {bar} {q['progress']}/{q['goal']}  ·  💠{q['reward_gold']} 🧬{q['reward_exp']}"
    )


def format_quests_text(user_id: int, period: str) -> str:
    quests = get_quests(user_id, period)
    if period == "daily":
        title = "📋 <b>Задания Годжо на сегодня</b>"
        footer = "<i>Годжо: «Не расслабляйся. Каждый день на счету.»</i>"
    else:
        title = "📅 <b>Задания Годжо на неделю</b>"
        footer = "<i>Годжо: «Неделя — это ещё не повод расслабиться.»</i>"
    ready = sum(1 for q in quests if not q["claimed"] and q["progress"] >= q["goal"])
    body = "\n\n".join(_line(q) for q in quests)
    tail = f"\n\n🎁 Готово к получению: {ready}" if ready else ""
    return f"{title}\n\n{body}\n\n{footer}{tail}"
