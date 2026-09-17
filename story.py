"""
story.py — сюжетные главы «Магической Битвы: Токио».

Система похожа на quests.py, но работает с крупными линейными главами.
Игрок проходит их по одной, каждая открывает следующую.

Каждая глава имеет min_level — минимальный уровень игрока, чтобы начать.
Если уровень недостаточен — кнопка «Отправиться» в меню сюжета заблокирована.

HP мобов и боссов в temp-локациях ослаблены на 25% относительно базового баланса.
"""
import json
import database


# ============================================================
#  СЮЖЕТНЫЕ ГЛАВЫ
# ============================================================

CHAPTERS = [
    # ---------- Глава 1: Пролог ----------
    {
        "id": "prologue",
        "num": 1,
        "title": "Пролог: Первый выход",
        "min_level": 1,
        "intro": (
            "О, ты уже здесь. Слушай, для начала — просто разомнись. "
            "Пойди и разберись с парой слабых проклятий. "
            "Хочу посмотреть, на что ты способен."
        ),
        "steps": [
            {
                "type": "kill",
                "target": "4-й класс",
                "goal": 3,
                "hint": "Изгони 3 проклятия 4-го класса в любом районе",
            },
        ],
        "reward_gold": 200,
        "reward_exp": 150,
    },

    # ---------- Глава 2: Палец Сукуны ----------
    {
        "id": "finger_hunt",
        "num": 2,
        "title": "Палец Сукуны",
        "min_level": 3,
        "intro": (
            "Слышал? В заброшенной школе на окраине Синдзюку шевелятся проклятия. "
            "Чувствую там что-то посерьёзнее — возможно, один из пальцев Сукуны. "
            "Сходи, разберись, принеси мне. Только осторожно."
        ),
        "steps": [
            {
                "type": "kill",
                "target": "abandoned_school",
                "goal": 4,
                "hint": "Изгони 4 проклятия в Заброшенной школе",
            },
            {
                "type": "kill_boss",
                "target": "Хранитель Пальца (Особый класс)",
                "goal": 1,
                "hint": "Победи Хранителя Пальца в подвале Заброшенной школы",
            },
            {
                "type": "have_item",
                "target": "Палец Сукуны",
                "goal": 1,
                "hint": "Забери Палец Сукуны и вернись к Годжо",
            },
        ],
        "reward_gold": 500,
        "reward_exp": 400,
        "temp_district": {
            "id": "abandoned_school",
            "name": "Заброшенная школа",
            "emoji": "🏚️",
            "description": "Ржавые парты, разбитые окна, и что-то шепчет из подвала.",
            "curses": [
                ("Проклятый Ученик", "4-й класс", 68, 11, 15, "👤", "Старый Рюкзак", 40),
                ("Тень Учителя", "3-й класс", 90, 14, 19, "🎓", "Порванный Журнал", 30),
                ("Шёпот из Подвала", "2-й класс", 120, 18, 24, "🕯️", "Огарок Свечи", 25),
                ("Хранитель Пальца", "1-й класс", 188, 26, 34, "👁️", "Фрагмент Печати", 5),
            ],
            "boss": {
                "name": "Хранитель Пальца (Особый класс)",
                "hp": 675,
                "dmg_min": 24, "dmg_max": 34,
                "emoji": "👁️‍🗨️",
                "reward_gold": 400,
                "reward_exp": 300,
                "drop_item": ("Палец Сукуны", "легендарный", 1),
            },
        },
    },
]


# ============================================================
#  СОЗДАНИЕ ТАБЛИЦЫ
# ============================================================

_db_ready = False


def _ensure_table():
    global _db_ready
    if _db_ready:
        return
    conn = database.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_story (
            user_id       INTEGER PRIMARY KEY,
            chapter_idx   INTEGER NOT NULL DEFAULT 0,
            progress_json TEXT    NOT NULL DEFAULT '{}',
            in_temp       INTEGER NOT NULL DEFAULT 0,
            finished      INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    _db_ready = True


def _get_row(user_id: int):
    _ensure_table()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM player_story WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO player_story (user_id) VALUES (?)", (user_id,))
        conn.commit()
        cur.execute("SELECT * FROM player_story WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    return {
        "user_id": row["user_id"],
        "chapter_idx": row["chapter_idx"],
        "progress": json.loads(row["progress_json"] or "{}"),
        "in_temp": bool(row["in_temp"]),
        "finished": bool(row["finished"]),
    }


def _save(user_id: int, state: dict):
    conn = database.get_conn()
    conn.execute(
        "UPDATE player_story SET chapter_idx = ?, progress_json = ?, in_temp = ?, finished = ? "
        "WHERE user_id = ?",
        (
            state["chapter_idx"],
            json.dumps(state["progress"], ensure_ascii=False),
            int(state["in_temp"]),
            int(state["finished"]),
            user_id,
        ),
    )
    conn.commit()


# ============================================================
#  ПУБЛИЧНОЕ API
# ============================================================

def get_current_chapter(user_id: int) -> dict | None:
    state = _get_row(user_id)
    if state["finished"] or state["chapter_idx"] >= len(CHAPTERS):
        return None
    return CHAPTERS[state["chapter_idx"]]


def get_progress(user_id: int) -> dict:
    return _get_row(user_id)["progress"]


def is_in_temp(user_id: int) -> bool:
    return _get_row(user_id)["in_temp"]


def get_temp_district(user_id: int) -> dict | None:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return None
    return chapter.get("temp_district")


def get_chapter_min_level(user_id: int) -> int:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return 1
    return chapter.get("min_level", 1)


def can_start_chapter(user_id: int) -> bool:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return False
    player = database.get_or_create_player(user_id, "")
    return player["level"] >= chapter.get("min_level", 1)


def enter_temp(user_id: int):
    state = _get_row(user_id)
    state["in_temp"] = True
    _save(user_id, state)


def exit_temp(user_id: int):
    state = _get_row(user_id)
    state["in_temp"] = False
    _save(user_id, state)


def add_progress(user_id: int, kind: str, target: str | None = None,
                 amount: int = 1) -> list[dict]:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return []

    state = _get_row(user_id)
    progress = state["progress"]
    completed_steps = []

    for i, step in enumerate(chapter["steps"]):
        if step["type"] == "kill" and kind != "kill":
            continue
        if step["type"] == "kill_boss" and kind != "kill_boss":
            continue
        if step["type"] == "have_item":
            continue
        if step.get("target") is not None and step["target"] != target:
            continue

        key = str(i)
        old = progress.get(key, 0)
        new = min(step["goal"], old + amount)
        if new == old:
            continue
        progress[key] = new
        if new >= step["goal"] and old < step["goal"]:
            completed_steps.append({"idx": i, "hint": step["hint"]})

    _save(user_id, state)
    return completed_steps


def _check_have_item_steps(user_id: int, chapter: dict, progress: dict) -> dict:
    for i, step in enumerate(chapter["steps"]):
        if step["type"] != "have_item":
            continue
        key = str(i)
        have = database.count_item(user_id, step["target"])
        progress[key] = min(step["goal"], have)
    return progress


def check_and_finish(user_id: int) -> dict | None:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return None

    state = _get_row(user_id)
    progress = _check_have_item_steps(user_id, chapter, state["progress"])
    state["progress"] = progress
    _save(user_id, state)

    for i, step in enumerate(chapter["steps"]):
        if progress.get(str(i), 0) < step["goal"]:
            return None

    database.add_gold(user_id, chapter["reward_gold"])
    new_level, leveled = database.add_exp_and_level(user_id, chapter["reward_exp"])

    for step in chapter["steps"]:
        if step["type"] == "have_item":
            database.consume_item(user_id, step["target"], step["goal"])

    state["chapter_idx"] += 1
    state["progress"] = {}
    state["in_temp"] = False
    if state["chapter_idx"] >= len(CHAPTERS):
        state["finished"] = True
    _save(user_id, state)

    next_chapter = get_current_chapter(user_id)
    return {
        "completed_chapter": chapter,
        "next_chapter": next_chapter,
        "reward_gold": chapter["reward_gold"],
        "reward_exp": chapter["reward_exp"],
        "leveled": leveled,
        "new_level": new_level,
    }


# ============================================================
#  UI-ХЕЛПЕРЫ
# ============================================================

def _progress_bar(progress: int, goal: int, width: int = 10) -> str:
    filled = 0 if goal <= 0 else min(width, progress * width // goal)
    return "▰" * filled + "▱" * (width - filled)


def format_story_screen(user_id: int) -> str:
    state = _get_row(user_id)
    player = database.get_or_create_player(user_id, "")

    if state["finished"]:
        return (
            "📖 <b>Сюжет</b>\n\n"
            "🏁 <b>Все доступные главы пройдены.</b>\n\n"
            "<i>Годжо: «Пока всё. Отдохни, а я подготовлю что-нибудь повеселее.»</i>\n\n"
            "Продолжение следует..."
        )

    chapter = get_current_chapter(user_id)
    if not chapter:
        return "📖 <b>Сюжет</b>\n\n<i>Пока ничего нового.</i>"

    min_level = chapter.get("min_level", 1)
    level_ok = player["level"] >= min_level

    lines = [
        f"📖 <b>Глава {chapter['num']}: {chapter['title']}</b>",
        "",
    ]

    if not level_ok:
        lines.append(f"🔒 <b>Нужен уровень {min_level}</b> (у тебя {player['level']})")
        lines.append("")
        lines.append("<i>Годжо: «Ты пока не готов к этому. Прокачайся и возвращайся.»</i>")
        return "\n".join(lines)

    lines.append(f"💬 <b>Годжо:</b> <i>«{chapter['intro']}»</i>")
    lines.append("")
    lines.append("<b>Задачи:</b>")

    for i, step in enumerate(chapter["steps"]):
        prog = state["progress"].get(str(i), 0)
        goal = step["goal"]
        status = "✅" if prog >= goal else "⏳"
        bar = _progress_bar(prog, goal)
        lines.append(f"{status} {step['hint']}\n   {bar} {prog}/{goal}")

    lines.append("")
    lines.append(f"🎁 <b>Награда:</b> 💠 +{chapter['reward_gold']}, 🧬 +{chapter['reward_exp']}")
    return "\n".join(lines)


def format_intro(chapter: dict) -> str:
    return (
        f"📖 <b>Глава {chapter['num']}: {chapter['title']}</b>\n\n"
        f"💬 <b>Годжо:</b> <i>«{chapter['intro']}»</i>\n\n"
        f"📋 Открой вкладку «📖 Сюжет», чтобы посмотреть задачи."
    )


def format_completion(chapter: dict, reward_gold: int, reward_exp: int,
                      leveled: bool, new_level) -> str:
    lines = [
        f"🏁 <b>Глава {chapter['num']} завершена!</b>",
        f"<i>{chapter['title']}</i>",
        "",
        "💬 <b>Годжо:</b> «Неплохо. Держи, заслужил.»",
        "",
        f"💠 +{reward_gold} очков Ассоциации, 🧬 +{reward_exp} опыта",
    ]
    if leveled:
        lines.append(f"🎉 <b>Уровень повышен до {new_level}!</b>")
    return "\n".join(lines)


def get_school_message(user_id: int) -> str | None:
    chapter = get_current_chapter(user_id)
    if not chapter:
        return None
    state = _get_row(user_id)
    for i, step in enumerate(chapter["steps"]):
        prog = state["progress"].get(str(i), 0)
        if prog < step["goal"]:
            return (
                f"💬 <b>Годжо:</b> <i>«{chapter['intro']}»</i>\n\n"
                f"📋 <b>Текущая задача:</b> {step['hint']} ({prog}/{step['goal']})"
            )
    return None