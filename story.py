"""
story.py — сюжетные главы «Магической Битвы: Токио».

Боссы глав усилены:
- HP +20% (кроме Хранителя Пальца — оставлен лёгким для новичков)
- Урон повышен, минимальный урон подтянут почти до максимума (стабильный урон)
- Броня (defense) 20–35%, режет получаемый урон
- Уникальные пассивки и скиллы (см. BOSS_SKILLS)
- Execute-скилл: добивает игрока при низком HP
"""
import json
import random
import time
import database


LEVEL_CAP_BASE = 20
LEVEL_CAP_PER_CHAPTER = 20


# ============================================================
#  БОССОВЫЕ СКИЛЛЫ И ПАССИВКИ
# ============================================================
# passive:  срабатывает каждый ход босса с указанным шансом (если ход не пропущен).
# skills:   список активных скиллов, каждый роллится отдельно.
# execute:  срабатывает, если HP игрока ниже hp_threshold (гарантированно).
# ============================================================

BOSS_SKILLS = {
    "Хранитель Пальца (Особый класс)": {
        "passive": {
            "type": "extra_dmg", "chance": 0.25,
            "name": "👁 Взгляд из тьмы", "dmg": 12,
        },
        "skills": [
            {"name": "🕯️ Ритуал Тьмы", "chance": 0.20, "dmg_mult": 1.5},
        ],
        "execute": {
            "name": "💀 Поглощение", "hp_threshold": 0.20, "dmg_mult": 2.5,
        },
    },
    "Медсестра-Смерть (Особый класс)": {
        "passive": {
            "type": "drain_ce", "chance": 0.35,
            "name": "💉 Забор ПЭ", "amount": 8,
        },
        "skills": [
            {"name": "🔪 Скальпель Смерти", "chance": 0.25, "dmg_mult": 1.6},
            {"name": "⚰️ Погребальный Хор", "chance": 0.15, "dmg_mult": 1.8, "stun_player": True},
        ],
        "execute": {
            "name": "💀 Остановка сердца", "hp_threshold": 0.25, "dmg_mult": 3.0,
        },
    },
    "Пожиратель Тоннелей (Особый класс)": {
        "passive": {
            "type": "double_attack", "chance": 0.25,
        },
        "skills": [
            {"name": "🌊 Прилив Тоннеля", "chance": 0.25, "dmg_mult": 1.5},
            {"name": "🕳️ Затягивание", "chance": 0.15, "dmg_mult": 2.0, "stun_player": True},
        ],
        "execute": {
            "name": "💀 Утопление", "hp_threshold": 0.28, "dmg_mult": 2.8,
        },
    },
    "Сукуна (3 пальца) (Особый класс)": {
        "passive": {
            "type": "rage", "chance": 0.30,
        },
        "skills": [
            {"name": "⚔️ Рассечение", "chance": 0.25, "dmg_mult": 1.6},
            {"name": "🏮 Злая Святыня", "chance": 0.15, "dmg_mult": 2.2},
        ],
        "execute": {
            "name": "💀 Демон Внутри", "hp_threshold": 0.30, "dmg_mult": 3.2,
        },
    },
    "Махито (Особый класс)": {
        "passive": {
            "type": "bleed", "chance": 0.35,
            "name": "🩸 Искажение плоти", "dmg": 20, "turns": 2,
        },
        "skills": [
            {"name": "🎭 Трансформация душ", "chance": 0.25, "dmg_mult": 1.7},
            {"name": "👐 Коснуться сердцу", "chance": 0.15, "dmg_mult": 2.4},
        ],
        "execute": {
            "name": "💀 Идеальная форма", "hp_threshold": 0.32, "dmg_mult": 3.5,
        },
    },
}


CHAPTERS = [
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
            {"type": "kill", "target": "abandoned_school", "goal": 4,
             "hint": "Изгони 4 проклятия в Заброшенной школе"},
            {"type": "puzzle", "target": "gojo_cipher", "goal": 1,
             "hint": "🧩 Разгадай шифр в блокноте и узнай пароль от подвала"},
            {"type": "kill_boss", "target": "Хранитель Пальца (Особый класс)", "goal": 1,
             "hint": "Победи Хранителя Пальца в подвале Заброшенной школы"},
            {"type": "have_item", "target": "Палец Сукуны", "goal": 1,
             "hint": "Забери Палец Сукуны и вернись к Годжо"},
        ],
        "reward_gold": 500,
        "reward_exp": 400,
        "temp_district": {
            "id": "abandoned_school",
            "name": "Заброшенная школа",
            "emoji": "🏚️",
            "description": "Ржавые парты, разбитые окна, и что-то шепчет из подвала.",
            "curses": [
                ("Проклятый Ученик", "4-й класс", 78, 13, 17, "👤", "Старый Рюкзак", 40),
                ("Тень Учителя", "3-й класс", 104, 16, 22, "🎓", "Порванный Журнал", 30),
                ("Шёпот из Подвала", "2-й класс", 138, 21, 28, "🕯️", "Огарок Свечи", 25),
                ("Хранитель Пальца", "1-й класс", 216, 30, 39, "👁️", "Фрагмент Печати", 5),
            ],
            "boss": {
                "name": "Хранитель Пальца (Особый класс)",
                "hp": 675,
                "dmg_min": 24, "dmg_max": 34,
                "defense": 0.20,
                "emoji": "👁️‍🗨️",
                "reward_gold": 400,
                "reward_exp": 300,
                "drop_item": ("Палец Сукуны", "легендарный", 1),
            },
        },
    },
    {
        "id": "hospital_finger",
        "num": 3,
        "title": "Второй палец",
        "min_level": 5,
        "intro": (
            "Есть зацепка. Старая больница у залива закрыта уже десять лет — "
            "официально из-за пожара. На деле там до сих пор что-то дышит. "
            "Ещё один палец Сукуны, я почти уверен. Иди и проверь, но не задерживайся там до темноты."
        ),
        "steps": [
            {"type": "kill", "target": "abandoned_hospital", "goal": 4,
             "hint": "Изгони 4 проклятия в Заброшенной больнице"},
            {"type": "puzzle", "target": "hospital_code", "goal": 1,
             "hint": "🧩 Разгадай код от двери морга"},
            {"type": "kill_boss", "target": "Медсестра-Смерть (Особый класс)", "goal": 1,
             "hint": "Победи Медсестру-Смерть в операционной больницы"},
            {"type": "have_item", "target": "Палец Сукуны", "goal": 1,
             "hint": "Забери Палец Сукуны и вернись к Годжо"},
        ],
        "reward_gold": 700,
        "reward_exp": 550,
        "temp_district": {
            "id": "abandoned_hospital",
            "name": "Заброшенная больница",
            "emoji": "🏥",
            "description": "Запах формалина въелся в стены. На этажах до сих пор горит аварийный свет.",
            "curses": [
                ("Проклятый Пациент", "4-й класс", 115, 15, 20, "🤕", "Использованный Бинт", 40),
                ("Проклятая Медсестра", "3-й класс", 150, 18, 24, "💉", "Шприц с Тёмной Жидкостью", 30),
                ("Тень Морга", "2-й класс", 196, 23, 30, "⚰️", "Табличка с Номером", 25),
                ("Безумный Хирург", "1-й класс", 311, 32, 41, "🔪", "Скальпель Проклятия", 5),
            ],
            "boss": {
                "name": "Медсестра-Смерть (Особый класс)",
                "hp": 1056,
                "dmg_min": 48, "dmg_max": 58,
                "defense": 0.25,
                "emoji": "💀",
                "reward_gold": 500,
                "reward_exp": 400,
                "drop_item": ("Палец Сукуны", "легендарный", 1),
            },
        },
    },
    {
        "id": "subway_finger",
        "num": 4,
        "title": "Третий палец",
        "min_level": 7,
        "intro": (
            "Затопленная ветка метро, закрытая после аварии много лет назад. "
            "Ассоциация давно туда не суётся — сигнал проклятой энергии там зашкаливает. "
            "Если моя догадка верна, это последний палец, который нам по силам достать своими руками. Будь готов."
        ),
        "steps": [
            {"type": "kill", "target": "flooded_subway", "goal": 4,
             "hint": "Изгони 4 проклятия в Затопленном метро"},
            {"type": "puzzle", "target": "subway_graffiti", "goal": 1,
             "hint": "🧩 Расшифруй граффити на стене вагона"},
            {"type": "kill_boss", "target": "Пожиратель Тоннелей (Особый класс)", "goal": 1,
             "hint": "Победи Пожирателя Тоннелей в глубине станции"},
            {"type": "have_item", "target": "Палец Сукуны", "goal": 1,
             "hint": "Забери Палец Сукуны и вернись к Годжо"},
        ],
        "reward_gold": 900,
        "reward_exp": 700,
        "temp_district": {
            "id": "flooded_subway",
            "name": "Затопленное метро",
            "emoji": "🚇",
            "description": "Вода по колено, ржавые вагоны в темноте, и эхо, которое не должно отвечать.",
            "curses": [
                ("Проклятый Пассажир", "4-й класс", 121, 16, 21, "🚶", "Проездной Билет", 40),
                ("Утопленник в Форме", "3-й класс", 155, 20, 25, "🎫", "Ржавый Ключ", 30),
                ("Голос из Тоннеля", "2-й класс", 201, 24, 31, "📢", "Сломанный Фонарь", 25),
                ("Машинист Бездны", "1-й класс", 322, 33, 43, "🚈", "Чёрный Жетон", 5),
            ],
            "boss": {
                "name": "Пожиратель Тоннелей (Особый класс)",
                "hp": 1140,
                "dmg_min": 46, "dmg_max": 57,
                "defense": 0.28,
                "emoji": "🕳️",
                "reward_gold": 600,
                "reward_exp": 480,
                "drop_item": ("Палец Сукуны", "легендарный", 1),
            },
        },
    },
    {
        "id": "awakening",
        "num": 5,
        "title": "Пробуждение Сукуны",
        "min_level": 10,
        "intro": (
            "Три пальца собраны. Этого достаточно, чтобы Сукуна начал шевелиться внутри своего вместилища. "
            "Ассоциация выставила временный барьер на окраине, чтобы сдержать всплеск, если станет хуже. "
            "Держись начеку — то, что мы разбудим сегодня, может оказаться сильнее всего, с чем ты сталкивался."
        ),
        "steps": [
            {"type": "kill", "target": "cursed_arena", "goal": 5,
             "hint": "Изгони 5 проклятий на Проклятой арене"},
            {"type": "puzzle", "target": "seal_sequence", "goal": 1,
             "hint": "🧩 Зажги печати барьера в правильном порядке"},
            {"type": "kill_boss", "target": "Сукуна (3 пальца) (Особый класс)", "goal": 1,
             "hint": "Победи пробудившегося Сукуну"},
            {"type": "have_item", "target": "Метка Сукуны", "goal": 1,
             "hint": "Забери Метку Сукуны и вернись к Годжо"},
        ],
        "reward_gold": 1500,
        "reward_exp": 1200,
        "temp_district": {
            "id": "cursed_arena",
            "name": "Проклятая арена",
            "emoji": "⛩️",
            "description": "Временный барьер трещит по швам. Воздух густой от проклятой энергии, земля дрожит.",
            "curses": [
                ("Отголосок Сукуны", "4-й класс", 127, 17, 22, "👹", "Осколок Ауры", 40),
                ("Клык Проклятого Духа", "3-й класс", 161, 21, 26, "🦷", "Кровавая Метка", 30),
                ("Страж Барьера", "2-й класс", 207, 25, 32, "🛡️", "Печать Барьера", 25),
                ("Порождение Плоти", "1-й класс", 334, 35, 45, "🩸", "Плоть Проклятия", 5),
            ],
            "boss": {
                "name": "Сукуна (3 пальца) (Особый класс)",
                "hp": 1800,
                "dmg_min": 55, "dmg_max": 66,
                "defense": 0.32,
                "emoji": "👺",
                "reward_gold": 800,
                "reward_exp": 650,
                "drop_item": ("Метка Сукуны", "легендарный", 1),
            },
        },
    },
    {
        "id": "shibuya_incident",
        "num": 6,
        "title": "Инцидент в Сибуе",
        "min_level": 14,
        "intro": (
            "Сегодня Хэллоуин, и весь квартал Сибуи накрыло барьером — заранее спланированная ловушка. "
            "Связь потеряна, старшие маги один за другим выходят из строя, а я застрял там, где не могу помочь. "
            "Слушай внимательно: внутри действует существо, способное менять тела, как перчатки. Не геройствуй — просто выживи и продержись до прорыва барьера."
        ),
        "steps": [
            {"type": "kill", "target": "shibuya_barrier", "goal": 5,
             "hint": "Изгони 5 трансформированных в барьере Сибуи"},
            {"type": "puzzle", "target": "infinity_riddle", "goal": 1,
             "hint": "🧩 Отгадай загадку Годжо про его технику"},
            {"type": "kill_boss", "target": "Махито (Особый класс)", "goal": 1,
             "hint": "Победи Махито на разрушенной площади Сибуи"},
            {"type": "have_item", "target": "Душа Проклятия", "goal": 1,
             "hint": "Забери Душу Проклятия и вернись к Годжо"},
        ],
        "reward_gold": 2500,
        "reward_exp": 2000,
        "temp_district": {
            "id": "shibuya_barrier",
            "name": "Барьер Сибуи",
            "emoji": "🌆",
            "description": (
                "Неоновые вывески мигают над пустыми улицами. За барьером застряли "
                "сотни людей, и Махито уже переделал некоторых из них в нечто иное."
            ),
            "curses": [
                ("Трансформированный Прохожий", "4-й класс",
                 52, 44, 60, "🧍", "Искажённая Рука", 40),
                ("Трансформированный Пассажир", "3-й класс",
                 75, 58, 78, "🎎", "Ошмёток Плоти", 30),
                ("Трансформированная Душа", "2-й класс",
                 104, 78, 101, "🧟", "Сгусток Искажённой Души", 25),
                ("Искажённая Плоть", "1-й класс",
                 150, 104, 132, "🩸", "Ядро Трансформации", 5),
            ],
            "boss": {
                "name": "Махито (Особый класс)",
                "hp": 1680,
                "dmg_min": 57, "dmg_max": 67,
                "defense": 0.35,
                "emoji": "🎭",
                "reward_gold": 1000,
                "reward_exp": 800,
                "drop_item": ("Душа Проклятия", "легендарный", 1),
            },
        },
    },
]


PUZZLES = {
    "gojo_cipher": {
        "chapter_id": "finger_hunt",
        "type": "cipher",
        "shift": 3,
        "answer": "ПОДВАЛ",
        "flavor": (
            "Среди вещей Хранителя Пальца — потрёпанный блокнот. На последней "
            "странице кто-то оставил шифр Цезаря со сдвигом на 3 буквы."
        ),
    },
    "hospital_code": {
        "chapter_id": "hospital_finger",
        "type": "code_lock",
        "code": "683",
        "clues": [
            "Первая цифра: 9 − 3",
            "Вторая цифра: 2 × 4",
            "Третья цифра: 12 разделить на 4",
        ],
        "flavor": "На двери в морг — механический кодовый замок на 3 цифры.",
    },
    "subway_graffiti": {
        "chapter_id": "subway_finger",
        "type": "graffiti",
        "mapping": [
            ("🔺", "С"),
            ("🔵", "Т"),
            ("⭐", "О"),
            ("⬛", "П"),
        ],
        "word_symbols": "🔺🔵⭐⬛",
        "answer": "СТОП",
        "flavor": (
            "Вагон стоит на рельсах, но что-то в нём не так. На стене "
            "кто-то оставил граффити: символы рядом с буквами. "
            "Похоже, это ключ к тому, что нужно сделать."
        ),
    },
    "seal_sequence": {
        "chapter_id": "awakening",
        "type": "sequence",
        "sequence": ["🔵", "🔺", "⭐", "⬛"],
        "symbols": ["🔺", "🔵", "⬛", "⭐"],
        "flavor": (
            "Чтобы пройти сквозь временный барьер, нужно зажечь проклятые печати "
            "в правильном порядке. Порядок неизвестен — придётся подбирать. "
            "Если ошибёшься, все печати гаснут и начинаешь заново."
        ),
    },
    "infinity_riddle": {
        "chapter_id": "shibuya_incident",
        "type": "riddle",
        "question": (
            "«Между мной и любой атакой всегда остаётся крошечный зазор — он "
            "замедляет всё, что летит в мою сторону, будто пространство "
            "растягивается само по себе. Как называется эта техника?»"
        ),
        "answers": ["бесконечность", "муре кушо", "мурё кусё", "предел безграничного"],
        "flavor": (
            "Пока ты пробираешься через барьер, в голове звучит голос Годжо — "
            "он загадывает загадку, чтобы отвлечь тебя от паники."
        ),
    },
}

# ВАЖНО: буква Ё включена, чтобы сдвиг Цезаря считался правильно.
RU_ALPHABET = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"


def _caesar_encode(text: str, shift: int) -> str:
    out = []
    for ch in text.upper():
        if ch in RU_ALPHABET:
            idx = RU_ALPHABET.index(ch)
            out.append(RU_ALPHABET[(idx + shift) % len(RU_ALPHABET)])
        else:
            out.append(ch)
    return "".join(out)


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def get_puzzle(puzzle_id: str) -> dict | None:
    return PUZZLES.get(puzzle_id)


def _get_puzzle_state(user_id: int, puzzle_id: str) -> dict:
    state = _get_row(user_id)
    return state["progress"].get("_puzzle", {}).get(puzzle_id, {})


def _set_puzzle_state(user_id: int, puzzle_id: str, data: dict):
    state = _get_row(user_id)
    progress = state["progress"]
    progress.setdefault("_puzzle", {})
    progress["_puzzle"][puzzle_id] = data
    state["progress"] = progress
    _save(user_id, state)


def get_current_puzzle_step(user_id: int):
    chapter = get_current_chapter(user_id)
    if not chapter:
        return None
    state = _get_row(user_id)
    for i, step in enumerate(chapter["steps"]):
        if step["type"] != "puzzle":
            continue
        if state["progress"].get(str(i), 0) >= step["goal"]:
            continue
        puzzle_id = step["target"]
        puzzle = PUZZLES.get(puzzle_id)
        if puzzle:
            return i, puzzle_id, puzzle
    return None


def format_puzzle_prompt(user_id: int) -> str | None:
    found = get_current_puzzle_step(user_id)
    if not found:
        return None
    _, puzzle_id, puzzle = found
    ptype = puzzle["type"]

    lines = ["🧩 <b>Головоломка</b>", "", puzzle["flavor"], ""]

    if ptype == "cipher":
        encoded = _caesar_encode(puzzle["answer"], puzzle["shift"])
        lines.append(f"Зашифрованное слово (сдвиг {puzzle['shift']}):")
        lines.append(f"<code>{encoded}</code>")
        lines.append("")
        lines.append("Отправь расшифрованное слово одним сообщением.")
    elif ptype == "code_lock":
        lines.append("Подсказки:")
        for clue in puzzle["clues"]:
            lines.append(f"• {clue}")
        lines.append("")
        lines.append("Отправь код тремя цифрами.")
    elif ptype == "graffiti":
        lines.append("На стене вагона — граффити:")
        lines.append("")
        for sym, letter in puzzle["mapping"]:
            lines.append(f"  {sym}  =  <b>{letter}</b>")
        lines.append("")
        lines.append(f"Ниже крупно нацарапано: <b>{puzzle['word_symbols']}</b>")
        lines.append("")
        lines.append("Отправь расшифрованное слово одним сообщением.")
    elif ptype == "riddle":
        lines.append(puzzle["question"])
        lines.append("")
        lines.append("Отправь ответ одним словом или короткой фразой.")
    elif ptype == "reaction":
        lines.append("Нажми кнопку «▶️ Начать», а затем «🛑 Тормоз» точно в нужный момент.")
    elif ptype == "sequence":
        total = len(puzzle["sequence"])
        bar = " ".join("⬜" for _ in range(total))
        lines.append(f"<b>Прогресс:</b> {bar}")
        lines.append(f"<b>Угадано:</b> 0 из {total}")
        lines.append("")
        lines.append("Нажимай печати по одной. Если ошибёшься — все гаснут.")

    return "\n".join(lines)


def solve_current_puzzle_text(user_id: int, text: str) -> dict:
    found = get_current_puzzle_step(user_id)
    if not found:
        return {"active": False}

    i, puzzle_id, puzzle = found
    ptype = puzzle["type"]

    if ptype not in ("cipher", "code_lock", "riddle", "graffiti"):
        return {"active": True, "correct": False, "wrong_type": True,
                "puzzle_id": puzzle_id, "step_idx": i}

    correct = False
    if ptype == "cipher":
        correct = _normalize(text) == puzzle["answer"].lower()
    elif ptype == "code_lock":
        digits = "".join(ch for ch in text if ch.isdigit())
        correct = digits == puzzle["code"]
    elif ptype == "riddle":
        correct = _normalize(text) in [a.lower() for a in puzzle["answers"]]
    elif ptype == "graffiti":
        correct = _normalize(text) == puzzle["answer"].lower()

    if correct:
        add_progress(user_id, "puzzle", target=puzzle_id, amount=1)

    return {"active": True, "correct": correct, "puzzle_id": puzzle_id, "step_idx": i}


def start_sequence_puzzle(user_id: int, puzzle_id: str) -> list[str]:
    puzzle = PUZZLES[puzzle_id]
    _set_puzzle_state(user_id, puzzle_id, {"position": 0})
    return puzzle["sequence"]


def format_sequence_keyboard(puzzle_id: str) -> list[tuple[str, str]]:
    puzzle = PUZZLES[puzzle_id]
    symbols = puzzle.get("symbols") or list(dict.fromkeys(puzzle["sequence"]))
    return [(sym, f"story_puzzle:{puzzle_id}:tap:{sym}") for sym in symbols]


def format_sequence_progress(puzzle_id: str, position: int) -> str:
    puzzle = PUZZLES[puzzle_id]
    seq = puzzle["sequence"]
    parts = []
    for i, sym in enumerate(seq):
        if i < position:
            parts.append(sym)
        else:
            parts.append("⬜")
    return " ".join(parts)


def check_sequence_tap(user_id: int, puzzle_id: str, tapped_symbol: str) -> dict:
    puzzle = PUZZLES[puzzle_id]
    pstate = _get_puzzle_state(user_id, puzzle_id)
    pos = pstate.get("position", 0)
    expected = puzzle["sequence"][pos]

    if tapped_symbol != expected:
        _set_puzzle_state(user_id, puzzle_id, {"position": 0})
        return {"result": "wrong", "position": 0}

    pos += 1
    if pos >= len(puzzle["sequence"]):
        add_progress(user_id, "puzzle", target=puzzle_id, amount=1)
        _set_puzzle_state(user_id, puzzle_id, {"position": 0})
        return {"result": "complete"}

    _set_puzzle_state(user_id, puzzle_id, {"position": pos})
    return {"result": "correct", "position": pos}


def start_reaction_puzzle(user_id: int, puzzle_id: str):
    _set_puzzle_state(user_id, puzzle_id, {"start_ts": time.time()})


def check_reaction_tap(user_id: int, puzzle_id: str) -> dict:
    puzzle = PUZZLES[puzzle_id]
    pstate = _get_puzzle_state(user_id, puzzle_id)
    start_ts = pstate.get("start_ts")

    if start_ts is None:
        return {"result": "not_started"}

    elapsed = time.time() - start_ts

    if elapsed < puzzle["delay_min"]:
        return {"result": "too_early", "elapsed": elapsed}

    if elapsed > puzzle["delay_max"]:
        _set_puzzle_state(user_id, puzzle_id, {})
        return {"result": "too_late", "elapsed": elapsed}

    add_progress(user_id, "puzzle", target=puzzle_id, amount=1)
    _set_puzzle_state(user_id, puzzle_id, {})
    return {"result": "success", "elapsed": elapsed}


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


def get_completed_chapters(user_id: int) -> int:
    state = _get_row(user_id)
    if state["finished"]:
        return len(CHAPTERS)
    return state["chapter_idx"]


def get_max_level(user_id: int) -> int:
    completed = get_completed_chapters(user_id)
    return LEVEL_CAP_BASE + LEVEL_CAP_PER_CHAPTER * completed


def is_level_capped(user_id: int) -> bool:
    player = database.get_or_create_player(user_id, "")
    return player["level"] >= get_max_level(user_id)


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
        if step["type"] == "puzzle" and kind != "puzzle":
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
    """Проверяет выполнение всех шагов главы.
    VIP даёт ×2 к золоту и опыту за главу.
    Пальцы Сукуны и другие have_item не удваиваются — они просто
    проверяются на наличие, а не выдаются через эту функцию."""
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

    vip = database.vip_mult(user_id)
    gold = int(chapter["reward_gold"] * vip)
    exp = int(chapter["reward_exp"] * vip)

    database.add_gold(user_id, gold)
    new_level, leveled = database.add_exp_and_level(user_id, exp)

    for step in chapter["steps"]:
        if step["type"] == "have_item":
            if step["target"] == "Палец Сукуны":
                continue
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
        "reward_gold": gold,
        "reward_exp": exp,
        "vip_applied": vip > 1.0,
        "leveled": leveled,
        "new_level": new_level,
        "new_max_level": get_max_level(user_id),
    }


def _progress_bar(progress: int, goal: int, width: int = 10) -> str:
    filled = 0 if goal <= 0 else min(width, progress * width // goal)
    return "▰" * filled + "▱" * (width - filled)


def format_story_screen(user_id: int) -> str:
    state = _get_row(user_id)
    player = database.get_or_create_player(user_id, "")
    max_level = get_max_level(user_id)

    if state["finished"]:
        return (
            "📖 <b>Сюжет</b>\n\n"
            "🏁 <b>Все доступные главы пройдены.</b>\n\n"
            f"📈 Текущий потолок уровня: <b>{max_level}</b>\n\n"
            "<i>Годжо: «Пока всё. Отдохни, а я подготовлю что-нибудь повеселее.»</i>\n\n"
            "Продолжение следует..."
        )

    chapter = get_current_chapter(user_id)
    if not chapter:
        return "📖 <b>Сюжет</b>\n\n<i>Пока ничего нового.</i>"

    min_level = chapter.get("min_level", 1)
    level_ok = player["level"] >= min_level

    lines = [f"📖 <b>Глава {chapter['num']}: {chapter['title']}</b>", ""]

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
    lines.append("<i>💎 VIP-игроки получают ×2 к награде за главу</i>")

    if player["level"] >= max_level:
        lines.append("")
        lines.append(
            f"⚠️ <b>Достигнут потолок уровня ({max_level}).</b> "
            "Пройди эту главу, чтобы качаться дальше."
        )

    return "\n".join(lines)


def format_intro(chapter: dict) -> str:
    return (
        f"📖 <b>Глава {chapter['num']}: {chapter['title']}</b>\n\n"
        f"💬 <b>Годжо:</b> <i>«{chapter['intro']}»</i>\n\n"
        f"📋 Открой вкладку «📖 Сюжет», чтобы посмотреть задачи."
    )


def format_completion(chapter: dict, reward_gold: int, reward_exp: int,
                      leveled: bool, new_level, vip_applied: bool = False) -> str:
    lines = [
        f"🏁 <b>Глава {chapter['num']} завершена!</b>",
        f"<i>{chapter['title']}</i>",
        "",
        "💬 <b>Годжо:</b> «Неплохо. Держи, заслужил.»",
        "",
        f"💠 +{reward_gold} очков Ассоциации, 🧬 +{reward_exp} опыта",
    ]
    if vip_applied:
        lines.append("💎 VIP: награды ×2")
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
