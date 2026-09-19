"""
rest.py — отдых в Токийской школе магии.

Игрок, находясь в районе jujutsu_high (X: -25..25), может нажать
«🧘 Отдохнуть» и мгновенно восстановить HP и Проклятую Энергию (ПЭ)
до ЭФФЕКТИВНОГО максимума (учитывая hp_mult/ce_mult от Проклятий Небес,
например Мехамару). Кулдаун — 150 секунд (2.5 минуты).

Колонка players.last_rest_at создаётся лениво при первом обращении.
"""
import time

import database
from ce_types import get_effective_stats


REST_COOLDOWN_SECONDS = 150  # 2.5 минуты


_ready = False


def _ensure_column():
    global _ready
    if _ready:
        return
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(players)")
    existing = {row["name"] for row in cur.fetchall()}
    if "last_rest_at" not in existing:
        conn.execute(
            "ALTER TABLE players ADD COLUMN last_rest_at INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    _ready = True


def can_rest(user_id: int) -> tuple[bool, int]:
    """Возвращает (можно_ли_отдохнуть, осталось_секунд).
    Если можно — второе число 0."""
    _ensure_column()
    conn = database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT last_rest_at FROM players WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return True, 0
    elapsed = int(time.time()) - row["last_rest_at"]
    remaining = REST_COOLDOWN_SECONDS - elapsed
    if remaining <= 0:
        return True, 0
    return False, remaining


def _fmt_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}м {s:02d}с" if m else f"{s}с"


def try_rest(user_id: int) -> dict:
    """Пытается отдохнуть. Восстанавливает HP и ПЭ до ЭФФЕКТИВНОГО максимума."""
    _ensure_column()
    player = database.get_or_create_player(user_id, "")

    ok, remaining = can_rest(user_id)
    if not ok:
        return {
            "ok": False,
            "msg": f"⏳ Годжо: «Дай себе передохнуть. Ещё {_fmt_time(remaining)} — и снова в бой.»",
        }

    # Эффективные максимумы с учётом проклятий Небес (Мехамару/Тоджи)
    eff = get_effective_stats(user_id, player)
    eff_max_hp = eff["max_hp"]
    eff_max_ce = eff["max_ce"]

    hp_full = player["hp"] >= eff_max_hp
    ce_full = player["ce"] >= eff_max_ce
    if hp_full and ce_full:
        return {
            "ok": False,
            "msg": "💚 HP и ПЭ уже полны. Нечего восстанавливать — иди патрулируй!",
        }

    hp_restored = max(0, eff_max_hp - player["hp"])
    ce_restored = max(0, eff_max_ce - player["ce"])

    conn = database.get_conn()
    conn.execute(
        "UPDATE players SET hp = ?, ce = ?, last_rest_at = ? WHERE user_id = ?",
        (eff_max_hp, eff_max_ce, int(time.time()), user_id),
    )
    conn.commit()

    lines = [
        "🧘 «Передохнул? Пойдём, район сам себя не зачистит.»",
        f"❤️ Восстановлено {hp_restored} HP (теперь {eff_max_hp}/{eff_max_hp})",
        f"🔵 Восстановлено {ce_restored} ПЭ (теперь {eff_max_ce}/{eff_max_ce})",
    ]
    return {
        "ok": True,
        "msg": "\n".join(lines),
        "hp_restored": hp_restored,
        "ce_restored": ce_restored,
    }
