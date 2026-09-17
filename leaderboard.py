"""
leaderboard.py — доска лидеров «Сила шамана».

Сила шамана (SP) считается по формуле:
    SP = текущая ПЭ + текущий HP * уровень

Пересчитывается на лету при каждом открытии доски. Если хочешь,
чтобы сила отражала «потенциал» игрока и не падала от потери HP —
поменяй в get_shaman_power hp на max_hp и ce на max_ce.

Имена игроков показываются обычным текстом (без кликабельных ссылок
на профиль) — в публичном боте это безопаснее.
"""
import database


def get_shaman_power(player_row) -> int:
    """Сила шамана = ПЭ + HP * уровень. Работает с sqlite3.Row и dict."""
    return int(player_row["ce"] + player_row["hp"] * player_row["level"])


def _all_players_with_power() -> list[dict]:
    """Список всех игроков с силой шамана, отсортированный по убыванию."""
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, level, hp, max_hp, ce, max_ce, ce_control FROM players"
    )
    rows = cur.fetchall()
    result = []
    for r in rows:
        result.append({
            "user_id": r["user_id"],
            "username": r["username"] or f"Игрок {r['user_id']}",
            "level": r["level"],
            "hp": r["hp"],
            "max_hp": r["max_hp"],
            "ce": r["ce"],
            "max_ce": r["max_ce"],
            "ce_control": r["ce_control"],
            "power": get_shaman_power(r),
        })
    result.sort(key=lambda p: p["power"], reverse=True)
    return result


def get_player_rank(user_id: int) -> dict:
    """{rank, power, total} для конкретного игрока. rank=None, если не найден."""
    all_players = _all_players_with_power()
    for i, p in enumerate(all_players, start=1):
        if p["user_id"] == user_id:
            return {"rank": i, "power": p["power"], "total": len(all_players)}
    return {"rank": None, "power": 0, "total": len(all_players)}


_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _safe(name: str) -> str:
    """Экранирует HTML-спецсимволы в имени игрока."""
    return name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_leaderboard(user_id: int, limit: int = 10) -> str:
    """HTML-текст доски лидеров. Текущий игрок подсвечивается 👈."""
    all_players = _all_players_with_power()
    if not all_players:
        return "🏆 <b>Доска лидеров — Сила шамана</b>\n\n<i>Пока никто не в списке. Будь первым!</i>"

    lines = ["🏆 <b>Доска лидеров — Сила шамана</b>"]
    lines.append("<i>SP = ПЭ + HP × уровень</i>\n")

    shown = all_players[:limit]
    me_in_top = False

    for i, p in enumerate(shown, start=1):
        medal = _MEDALS.get(i, f"{i:>2}.")
        name = _safe(p["username"])
        marker = " 👈" if p["user_id"] == user_id else ""
        lines.append(
            f"{medal} {name} — <b>{p['power']}</b> SP{marker}\n"
            f"     Ур. {p['level']} · ❤️ {p['hp']}/{p['max_hp']} · 🔵 {p['ce']}/{p['max_ce']}"
        )
        if p["user_id"] == user_id:
            me_in_top = True

    if not me_in_top:
        my = get_player_rank(user_id)
        if my["rank"] is not None:
            lines.append("")
            lines.append(f"⋯ Твоё место: <b>#{my['rank']}</b> из {my['total']} — {my['power']} SP")

    lines.append("")
    lines.append("<i>Годжо: «Сила — это не только ПЭ и HP. Но доска считает именно так.»</i>")
    return "\n".join(lines)