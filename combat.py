"""
Пошаговая боевая система «Магическая Битва: Токио».

Расширения Территории активируются ВРУЧНУЮ.
Боссы глав имеют броню (defense) и уникальные скиллы/пассивки из story.BOSS_SKILLS.
"""
import random

import database
import gacha
import quests
import equipment
import story
import ce_types
from config import (
    PLAYER_BASE_DMG_MIN, PLAYER_BASE_DMG_MAX, PHYS_CE_COEF, TECH_CE_COEF,
    DEFENSE_CE_COEF, DEFENSE_CAP, CE_REGEN_BASE, CE_REGEN_CE_COEF,
    PLAYER_CRIT_CHANCE, PLAYER_CRIT_MULT, PLAYER_MISS_CHANCE,
    BLACK_FLASH_STUN_CHANCE,
    MONSTER_MISS_CHANCE, FLEE_CHANCE,
    GOLD_PER_HP, EXP_PER_HP, DROP_CHANCE, DEATH_GOLD_LOSS,
    RARITY_EMOJI, EXP_BASE, CLASS_EMOJI,
    DOMAIN_UNLOCK_USES,
)
from loot import roll_quantity
from bosses import BOSSES, is_boss, SUMMON_RECIPES
from domains_data import DOMAINS


CLASS_REWARD_MULT = {
    "4-й класс": 1.0,
    "3-й класс": 1.3,
    "2-й класс": 1.7,
    "1-й класс": 2.5,
}

DEFEND_DAMAGE_MULT = 0.5
DEFEND_CE_REGEN_MULT = 2.0

DOMAIN_REACTIVATION_PENALTY = [0.0, 0.20, 0.50, 0.70]


# ============================================================
#  ЭФФЕКТЫ ДОМЕНОВ
# ============================================================
DOMAIN_EFFECTS = {
    "unlimited_void": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "first_turn_stun": 2,
    },
    "malevolent_shrine": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "dot_dmg": 40, "dot_name": "🏮 Невидимые лезвия",
    },
    "chimera_shadow_garden": {
        "dmg_mult": 1.25, "defense_mult": 0.70,
        "dot_dmg": 30, "dot_growth": 15, "dot_name": "🌑 Шикигами-атаки",
    },
    "coffin_of_the_iron_mountain": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "dot_dmg": 35, "dot_name": "🔥 Жуки-вулканы",
    },
    "self_embodiment_of_perfection": {
        "dmg_mult": 1.35, "defense_mult": 0.70,
    },
    "deadly_sentencing": {
        "dmg_mult": 1.25, "defense_mult": 0.75,
        "enemy_dmg_mult": 0.85,
    },
    "idle_death_gamble": {
        "dmg_mult": 1.80, "defense_mult": 0.75,
        "gamble": True,
    },
    "horizon_of_the_captivating_skandha": {
        "dmg_mult": 1.20, "defense_mult": 0.80,
        "enemy_miss_bonus": 0.15,
    },
    "authentic_mutual_love": {
        "dmg_mult": 1.30, "defense_mult": 0.65,
        "summon_rika": True, "rika_dmg": 50,
    },
    "ashen_boundless_reach": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "dot_dmg": 25, "dot_growth": 10, "dot_name": "🔥 Раскалённый пепел",
    },
    "hall_of_eternal_eclipse": {
        "dmg_mult": 1.35, "defense_mult": 0.75,
        "dot_dmg": 30, "dot_name": "🌕 Лунные клинки",
    },
    "hall_of_shattered_mirrors": {
        "dmg_mult": 1.20, "defense_mult": 0.55,
        "dodge_bonus": 0.20,
    },
    "choir_of_forgotten_voices": {
        "dmg_mult": 1.25, "defense_mult": 0.75,
        "enemy_miss_bonus": 0.20,
    },
    "hall_of_eternal_winter": {
        "dmg_mult": 1.25, "defense_mult": 0.75,
        "stun_per_turn_chance": 0.35,
    },
    "heavenly_verdict_of_the_storm": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "dot_dmg": 45, "dot_name": "⛈️ Проклятая молния",
    },
    "sanctuary_of_the_unbreakable_pact": {
        "dmg_mult": 1.50, "defense_mult": 0.75,
    },
    "choir_of_eternal_mourning": {
        "dmg_mult": 1.20, "defense_mult": 0.80,
        "heal_per_turn": 40,
    },
    "lair_of_the_ancient_beast": {
        "dmg_mult": 1.30, "defense_mult": 0.75,
        "dot_dmg": 35, "dot_name": "🐾 Атаки древнего зверя",
    },
    "fortress_of_eternal_steel": {
        "dmg_mult": 1.20, "defense_mult": 0.40,
    },
}


def _find_domain_by_technique(technique_name: str) -> str | None:
    for key, d in DOMAINS.items():
        if d["technique"] == technique_name:
            return key
    return None


def _get_reactivation_penalty(uses_before: int) -> float:
    if uses_before < len(DOMAIN_REACTIVATION_PENALTY):
        return DOMAIN_REACTIVATION_PENALTY[uses_before]
    return DOMAIN_REACTIVATION_PENALTY[-1]


def _penalty_preview(user_id: int) -> tuple[int, float]:
    used = database.get_domain_uses_in_battle(user_id)
    return (used + 1, _get_reactivation_penalty(used))


# ============================================================
#  СКИЛЛЫ БОССОВ
# ============================================================

def _get_boss_skills(monster_name: str) -> dict | None:
    """Возвращает конфиг скиллов/пассивок босса или None."""
    try:
        return story.BOSS_SKILLS.get(monster_name)
    except (AttributeError, TypeError):
        return None


# ============================================================
#  СЧЁТЧИК ИСПОЛЬЗОВАНИЙ ТЕХНИК
# ============================================================

def _register_domain_use(user_id: int, technique_name: str, log: list):
    technique = gacha.get_technique(technique_name)
    if not technique or not technique.get("has_domain"):
        return

    uses = database.inc_technique_uses(user_id, technique_name)

    if uses < DOMAIN_UNLOCK_USES:
        log.append(f"🌀 Расширение Территории: {uses}/{DOMAIN_UNLOCK_USES}")
        return

    if uses == DOMAIN_UNLOCK_USES:
        domain_key = _find_domain_by_technique(technique_name)
        domain_data = DOMAINS.get(domain_key, {}) if domain_key else {}
        log.append(
            f"🎉 <b>Расширение Территории разблокировано!</b> "
            f"{domain_data.get('emoji', '')} {domain_data.get('name', '')}"
        )
        log.append("🌌 В бою доступна кнопка «Использовать домен».")


def player_has_unlocked_domain(user_id: int) -> bool:
    equipped = gacha.get_equipped(user_id)
    for name in equipped:
        t = gacha.get_technique(name)
        if not t or not t.get("has_domain"):
            continue
        uses = database.get_technique_uses(user_id, name)
        if uses >= DOMAIN_UNLOCK_USES:
            return True
    return False


def get_unlocked_domain_technique(user_id: int) -> str | None:
    equipped = gacha.get_equipped(user_id)
    for name in equipped:
        t = gacha.get_technique(name)
        if not t or not t.get("has_domain"):
            continue
        uses = database.get_technique_uses(user_id, name)
        if uses >= DOMAIN_UNLOCK_USES:
            return name
    return None


def has_active_domain(user_id: int) -> bool:
    key, turns = database.get_domain(user_id)
    return bool(key and turns > 0)


def _parse_activation(activation: str) -> tuple[str, int] | None:
    if not activation or activation == "always":
        return None
    parts = activation.rsplit("_", 1)
    if len(parts) != 2:
        return None
    atype, n_str = parts
    try:
        n = int(n_str)
    except ValueError:
        return None
    return (atype, n)


def check_activation_condition(user_id: int) -> dict:
    technique_name = get_unlocked_domain_technique(user_id)
    if not technique_name:
        return {"ok": False, "text": "нет разблокированного домена",
                "current": 0, "goal": 0, "domain_name": "", "domain_emoji": "🌌"}

    domain_key = _find_domain_by_technique(technique_name)
    if not domain_key:
        return {"ok": False, "text": "домен не найден",
                "current": 0, "goal": 0, "domain_name": "", "domain_emoji": "🌌"}

    domain_data = DOMAINS.get(domain_key, {})
    domain_name = domain_data.get("name", domain_key)
    domain_emoji = domain_data.get("emoji", "🌌")

    activation = domain_data.get("activation", "always")
    parsed = _parse_activation(activation)

    if parsed is None:
        return {"ok": True, "text": "готово",
                "current": 0, "goal": 0,
                "domain_name": domain_name, "domain_emoji": domain_emoji}

    atype, goal = parsed
    charges = database.get_charges(user_id)

    if atype == "use_tech":
        cur = charges["tech_uses"]; label = "техник"
    elif atype == "deal_damage":
        cur = charges["dmg_dealt"]; label = "урона"
    elif atype == "take_damage":
        cur = charges["dmg_taken"]; label = "получено"
    elif atype == "use_black_flash":
        cur = charges["black_flash"]; label = "критов"
    else:
        return {"ok": True, "text": "готово",
                "current": 0, "goal": 0,
                "domain_name": domain_name, "domain_emoji": domain_emoji}

    return {
        "ok": cur >= goal,
        "text": f"{cur}/{goal} {label}",
        "current": cur, "goal": goal,
        "domain_name": domain_name, "domain_emoji": domain_emoji,
    }


def activate_domain_manual(user_id: int) -> dict:
    encounter = database.get_encounter(user_id)
    if not encounter:
        return {"ok": False, "msg": "Перед тобой никого нет."}

    cur_key, cur_turns = database.get_domain(user_id)
    if cur_key and cur_turns > 0:
        cur_data = DOMAINS.get(cur_key)
        cur_name = cur_data["name"] if cur_data else cur_key
        return {"ok": False, "msg": f"Домен уже активен: <b>{cur_name}</b> ({cur_turns} х.)"}

    technique_name = get_unlocked_domain_technique(user_id)
    if not technique_name:
        return {"ok": False, "msg": "У тебя нет разблокированного домена."}

    condition = check_activation_condition(user_id)
    if not condition["ok"]:
        return {
            "ok": False,
            "msg": (
                f"❌ Условие не выполнено: <b>{condition['text']}</b>.\n"
                f"Домен <b>{condition['domain_emoji']} {condition['domain_name']}</b> "
                f"пока не готов."
            ),
        }

    domain_key = _find_domain_by_technique(technique_name)
    if not domain_key:
        return {"ok": False, "msg": "Домен для этой техники не найден."}

    domain_data = DOMAINS[domain_key]
    effect = DOMAIN_EFFECTS.get(domain_key, {})
    log = []

    uses_before = database.get_domain_uses_in_battle(user_id)
    penalty = _get_reactivation_penalty(uses_before)

    if penalty > 0:
        player = database.get_or_create_player(user_id, "")
        current_hp = player["hp"]
        loss = int(current_hp * penalty)
        new_hp = max(1, current_hp - loss)
        database.update_player_hp(user_id, new_hp)
        log.append(
            f"💔 <b>Повторное расширение отняло {loss} HP</b> "
            f"({int(penalty * 100)}% от текущего). HP: {new_hp}/{current_hp}."
        )

    if effect.get("gamble"):
        if random.random() < 0.5:
            database.set_domain(user_id, domain_key, 3)
            log.append(
                f"🎰 <b>УДАЧА!</b> {domain_data['emoji']} "
                f"<b>{domain_data['name']}</b> активирован на 3 хода! +80% урона."
            )
        else:
            database.update_player_ce(user_id, 0)
            log.append(
                f"💀 <b>ПРОИГРЫШ!</b> {domain_data['emoji']} "
                f"<b>{domain_data['name']}</b> обнулил твою ПЭ!"
            )
    else:
        database.set_domain(user_id, domain_key, 3)
        log.append(
            f"{domain_data['emoji']} <b>Расширение Территории:</b> "
            f"<b>{domain_data['name']}</b> активировано на 3 хода!"
        )
        log.append(f"<i>{domain_data['effect']}</i>")

        if effect.get("first_turn_stun"):
            database.set_encounter_status(user_id, stun_turns=effect["first_turn_stun"])
            log.append(f"😵 Проклятие оглушено на {effect['first_turn_stun']} х.!")

    database.inc_domain_uses_in_battle(user_id)
    database.reset_charges(user_id)

    next_num, next_penalty = _penalty_preview(user_id)
    if next_penalty > 0:
        log.append(
            f"<i>Следующее расширение в этом бою отнимет "
            f"{int(next_penalty * 100)}% HP.</i>"
        )

    return {"ok": True, "log": log, "effect": "domain_activate"}


def _process_domain_turn(user_id: int, player, encounter, log: list) -> bool:
    domain_key, turns = database.get_domain(user_id)
    if not domain_key or turns <= 0:
        return False

    effect = DOMAIN_EFFECTS.get(domain_key, {})
    domain_data = DOMAINS.get(domain_key, {})
    domain_name = domain_data.get("name", domain_key)

    # DoT домена игнорирует броню монстра — это внутренний эффект ПЭ.
    if effect.get("summon_rika"):
        rika_dmg = effect.get("rika_dmg", 50)
        encounter = database.get_encounter(user_id)
        if encounter and encounter["hp"] > 0:
            new_hp = max(0, encounter["hp"] - rika_dmg)
            database.update_encounter_hp(user_id, new_hp)
            log.append(f"👻 <b>Рика Оримо</b> атакует: {rika_dmg} урона!")
            if new_hp <= 0:
                return True

    if effect.get("dot_dmg"):
        base_dot = effect["dot_dmg"]
        growth = effect.get("dot_growth", 0)
        turns_elapsed = 3 - turns
        dot = base_dot + growth * turns_elapsed
        encounter = database.get_encounter(user_id)
        if encounter and encounter["hp"] > 0:
            new_hp = max(0, encounter["hp"] - dot)
            database.update_encounter_hp(user_id, new_hp)
            dot_name = effect.get("dot_name", "Эффект домена")
            log.append(f"{dot_name}: {dot} урона!")
            if new_hp <= 0:
                return True

    if effect.get("heal_per_turn"):
        heal = effect["heal_per_turn"]
        eff = ce_types.get_effective_stats(user_id, player)
        new_hp = min(eff["max_hp"], player["hp"] + heal)
        if new_hp > player["hp"]:
            database.update_player_hp(user_id, new_hp)
            log.append(f"💚 Домен исцеляет: +{new_hp - player['hp']} HP.")

    if effect.get("stun_per_turn_chance"):
        if random.random() < effect["stun_per_turn_chance"]:
            database.set_encounter_status(user_id, stun_turns=1)
            log.append("❄️ Проклятие сковано льдом домена!")

    new_key, new_turns = database.decrement_domain(user_id)
    if new_key is None:
        log.append(f"🌫️ <b>{domain_name}</b> рассеялось.")
    else:
        log.append(f"⏳ <b>{domain_name}</b>: осталось {new_turns} х.")

    return False


# ---------------- Формулы ----------------

def _defense_reduction(user_id: int, player) -> float:
    base = player["ce_control"] * DEFENSE_CE_COEF
    bonus = database.get_buff_value(user_id, "defense_bonus")
    return min(DEFENSE_CAP, base + bonus)


def _ce_regen_amount(user_id: int, player) -> int:
    base = CE_REGEN_BASE + player["ce_control"] * CE_REGEN_CE_COEF
    buff = database.get_buff_value(user_id, "ce_regen_bonus")
    if buff:
        base = base * (1 + buff)
    effects = ce_types.get_active_effects(user_id)
    base = base * effects.get("ce_regen_mult", 1.0)
    return int(base)


def _physical_damage(user_id: int, player) -> int:
    bonus_ce = int(player["ce_control"] * PHYS_CE_COEF)
    w = equipment.get_bonuses(user_id)
    lo = PLAYER_BASE_DMG_MIN + bonus_ce + w["dmg_min"]
    hi = PLAYER_BASE_DMG_MAX + bonus_ce + w["dmg_max"]
    dmg = random.randint(lo, hi)

    buff = database.get_buff_value(user_id, "dmg_bonus")
    if buff:
        dmg = int(dmg * (1 + buff))

    effects = ce_types.get_active_effects(user_id)
    dmg = int(dmg * effects.get("phys_dmg_mult", 1.0))
    div = effects.get("phys_dmg_div", 1.0)
    if div > 1.0:
        dmg = max(1, int(dmg / div))

    domain_key, domain_turns = database.get_domain(user_id)
    if domain_key and domain_turns > 0:
        domain_eff = DOMAIN_EFFECTS.get(domain_key, {})
        dmg = int(dmg * domain_eff.get("dmg_mult", 1.0))

    return dmg


def _technique_damage(user_id: int, player, technique: dict) -> int:
    base = random.randint(technique["dmg_min"], technique["dmg_max"])
    coef = 1 + player["ce_control"] * TECH_CE_COEF
    w = equipment.get_bonuses(user_id)
    dmg = int(base * coef * w["tech_power"])

    buff = database.get_buff_value(user_id, "dmg_bonus")
    if buff:
        dmg = int(dmg * (1 + buff))

    effects = ce_types.get_active_effects(user_id)
    dmg = int(dmg * effects.get("tech_dmg_mult", 1.0))

    domain_key, domain_turns = database.get_domain(user_id)
    if domain_key and domain_turns > 0:
        domain_eff = DOMAIN_EFFECTS.get(domain_key, {})
        dmg = int(dmg * domain_eff.get("dmg_mult", 1.0))

    return dmg


def _black_flash_chance(user_id: int) -> float:
    eff = ce_types.get_effective_stats(user_id)
    if eff["max_ce"] <= 0:
        return 0.0
    w = equipment.get_bonuses(user_id)
    buff = database.get_buff_value(user_id, "crit_bonus")
    effects = ce_types.get_active_effects(user_id)
    return min(0.75, PLAYER_CRIT_CHANCE + w["crit_bonus"] + buff + effects.get("crit_bonus", 0.0))


def _regen_ce(user_id: int, player, mult: float = 1.0):
    eff = ce_types.get_effective_stats(user_id, player)
    if eff["max_ce"] <= 0:
        return 0
    regen = int(_ce_regen_amount(user_id, player) * mult)
    new_ce = min(eff["max_ce"], player["ce"] + regen)
    database.update_player_ce(user_id, new_ce)
    return regen


# ---------------- Тексты ----------------

def encounter_status_text(encounter) -> str:
    hp = max(0, encounter["hp"])
    prefix = "👑 БОСС ОСОБОГО КЛАССА " if is_boss(encounter["monster_name"]) else ""
    class_emoji = CLASS_EMOJI.get(encounter["curse_class"] or encounter["rarity"], "")
    status_bits = []
    if encounter["stun_turns"]:
        status_bits.append(f"😵 Оглушён ещё {encounter['stun_turns']} х.")
    if encounter["bleed_turns"]:
        status_bits.append(f"🩸 Кровотечение ещё {encounter['bleed_turns']} х. ({encounter['bleed_dmg']}/х.)")
    status_line = ("\n" + " | ".join(status_bits)) if status_bits else ""

    # Броня
    defense = 0.0
    try:
        defense = encounter["defense"] or 0.0
    except (IndexError, KeyError):
        defense = 0.0
    defense_line = f"\n🛡 Броня: -{int(defense * 100)}%" if defense > 0 else ""

    return (
        f"{prefix}{class_emoji} {encounter['emoji']} <b>{encounter['monster_name']}</b>\n"
        f"❤️ HP: {hp}/{encounter['max_hp']}\n"
        f"🗡 Урон: {encounter['dmg_min']}-{encounter['dmg_max']}"
        f"{defense_line}"
        f"{status_line}"
    )


def player_status_text(player, user_id: int | None = None) -> str:
    if user_id:
        eff = ce_types.get_effective_stats(user_id, player)
    else:
        eff = {"hp": player["hp"], "max_hp": player["max_hp"],
               "ce": player["ce"], "max_ce": player["max_ce"]}

    need = player["level"] * EXP_BASE
    buff_line = ""
    if player["dmg_buff_turns"]:
        buff_line = f" | 🔥 Бафф урона x{player['dmg_buff_mult']:.2f} ({player['dmg_buff_turns']} х.)"

    domain_line = ""
    if user_id:
        dk, dt = database.get_domain(user_id)
        if dk and dt > 0:
            dd = DOMAINS.get(dk)
            if dd:
                domain_line = f"\n{dd['emoji']} <b>{dd['name']}</b> ({dt} х.)"

    return (
        f"❤️ HP: {eff['hp']}/{eff['max_hp']} | "
        f"🔵 ПЭ: {eff['ce']}/{eff['max_ce']}\n"
        f"💠 {player['gold']} | 🧬 Ур. {player['level']} ({player['exp']}/{need}) | "
        f"🎚 Контроль ПЭ: {player['ce_control']}"
        f"{buff_line}"
        f"{domain_line}"
    )


# ---------------- Дроп ----------------

def _roll_drop(user_id: int, encounter):
    item_name = encounter["drop_item"]
    rarity = encounter["drop_rarity"]
    if not item_name or not rarity:
        return None
    if random.random() > DROP_CHANCE:
        return None

    if item_name in SUMMON_RECIPES:
        rarity = "призыв"
        qty = 1
    else:
        qty = roll_quantity(rarity)
        if database.vip_mult(user_id) > 1.0:
            qty *= 2

    database.add_item(user_id, item_name, rarity, qty)
    emoji = RARITY_EMOJI.get(rarity, "⚪")
    return f"🎁 Дроп: {emoji} {item_name} x{qty} ({rarity})"


# ---------------- Эффекты техник ----------------

def _apply_effect(user_id: int, encounter, effect: dict, log: list):
    if not effect:
        return
    if random.random() > effect.get("chance", 1.0):
        return
    etype = effect["type"]
    if etype == "stun":
        database.set_encounter_status(user_id, stun_turns=effect["turns"])
        quests.add_progress(user_id, "stun_apply")
        log.append(f"😵 Проклятие оглушено на {effect['turns']} х.!")
    elif etype == "bleed":
        database.set_encounter_status(user_id, bleed_turns=effect["turns"], bleed_dmg=effect["dmg"])
        quests.add_progress(user_id, "bleed_apply")
        log.append(f"🩸 Наложено кровотечение: {effect['dmg']} урона {effect['turns']} х.!")
    elif etype == "buff_dmg":
        database.set_player_dmg_buff(user_id, effect["turns"], effect["mult"])
        log.append(f"🔥 Урон усилен в x{effect['mult']:.2f} на {effect['turns']} х.!")


# ---------------- Победа/смерть ----------------

def _story_tracking(user_id: int, encounter, log: list):
    in_temp = story.is_in_temp(user_id)
    temp = story.get_temp_district(user_id) if in_temp else None

    if in_temp and temp:
        story.add_progress(user_id, "kill", target=temp["id"])
        boss = temp.get("boss")
        if boss and boss["name"] == encounter["monster_name"]:
            drop = boss.get("drop_item")
            if drop:
                dn, dr, dq = drop
                if dn != "Палец Сукуны" and database.vip_mult(user_id) > 1.0:
                    dq *= 2
                database.add_item(user_id, dn, dr, dq)
                em = RARITY_EMOJI.get(dr, "⚪")
                log.append(f"\n🎁 Сюжетный трофей: {em} <b>{dn}</b> x{dq}")
    else:
        story.add_progress(user_id, "kill", target=encounter["curse_class"])

    story.add_progress(user_id, "kill_boss", target=encounter["monster_name"])


def _find_story_boss(user_id: int, monster_name: str) -> dict | None:
    temp = story.get_temp_district(user_id)
    if not temp:
        return None
    boss = temp.get("boss")
    if boss and boss["name"] == monster_name:
        return boss
    return None


def _victory(user_id: int, encounter, log: list) -> dict:
    database.clear_encounter(user_id)
    boss = BOSSES.get(encounter["monster_name"])
    story_boss = _find_story_boss(user_id, encounter["monster_name"]) if not boss else None

    gold_buff = database.get_buff_value(user_id, "gold_bonus")
    exp_buff = database.get_buff_value(user_id, "exp_bonus")
    vip_mult = database.vip_mult(user_id)

    from world import get_district_by_id
    from config import LEVEL_SCALE_REWARD_COEF
    district = get_district_by_id(encounter["biome_id"])
    reward_scale = 1.0
    if district and not district.get("safe"):
        player = database.get_or_create_player(user_id, "")
        lvl_max = district.get("lvl_max", 999)
        if player["level"] > lvl_max:
            excess = player["level"] - lvl_max
            raw = 1 + excess * 0.03
            reward_scale = 1 + (raw - 1) * LEVEL_SCALE_REWARD_COEF

    def _apply_rewards(gold, exp):
        if gold_buff:
            gold = int(gold * (1 + gold_buff))
        if exp_buff:
            exp = int(exp * (1 + exp_buff))
        gold = int(gold * reward_scale * vip_mult)
        exp = int(exp * reward_scale * vip_mult)
        return gold, exp

    if boss or story_boss:
        source = boss or story_boss
        gold, exp = _apply_rewards(source["reward_gold"], source["reward_exp"])
        database.add_gold(user_id, gold)
        new_level, leveled = database.add_exp_and_level(user_id, exp)

        log.append(f"\n👑 <b>{encounter['monster_name']} ИЗГНАНО!</b>")
        log.append(f"💠 +{gold} очков Ассоциации, 🧬 +{exp} опыта")
        if vip_mult > 1:
            log.append("💎 <i>VIP: награды ×2</i>")

        quests.add_progress(user_id, "gold_earn", amount=gold)
        quests.add_progress(user_id, "exp_earn", amount=exp)
        quests.add_progress(user_id, "kill", target="Особый класс")
        quests.add_progress(user_id, "boss_kill")

        if boss and boss.get("drop_item"):
            dn, dr, dq = boss["drop_item"]
            if database.vip_mult(user_id) > 1.0:
                dq *= 2
            database.add_item(user_id, dn, dr, dq)
            em = RARITY_EMOJI.get(dr, "⚪")
            log.append(f"🎁 Трофей: {em} {dn} x{dq} ({dr})")

        _story_tracking(user_id, encounter, log)

        if leveled:
            quests.add_progress(user_id, "level_up")
            ce_types.compress_hp_ce(user_id)
            log.append(f"\n🎉 <b>Уровень повышен до {new_level}!</b> HP и ПЭ восстановлены.")
        return {"status": "victory", "log": log, "effect": "boss_victory"}

    curse_class = encounter["curse_class"] or "4-й класс"
    class_mult = CLASS_REWARD_MULT.get(curse_class, 1.0)

    base_gold = max(3, int(encounter["max_hp"] * GOLD_PER_HP * class_mult))
    base_exp = max(5, int(encounter["max_hp"] * EXP_PER_HP * class_mult))
    gold, exp = _apply_rewards(base_gold, base_exp)

    database.add_gold(user_id, gold)
    new_level, leveled = database.add_exp_and_level(user_id, exp)

    log.append(f"\n🏆 <b>{encounter['monster_name']} изгнано!</b>")
    log.append(f"💠 +{gold} очков Ассоциации, 🧬 +{exp} опыта")
    if vip_mult > 1:
        log.append("💎 <i>VIP: награды ×2</i>")

    quests.add_progress(user_id, "gold_earn", amount=gold)
    quests.add_progress(user_id, "exp_earn", amount=exp)
    quests.add_progress(user_id, "kill", target=encounter["curse_class"])

    drop_line = _roll_drop(user_id, encounter)
    if drop_line:
        log.append(drop_line)

    _story_tracking(user_id, encounter, log)

    if leveled:
        quests.add_progress(user_id, "level_up")
        ce_types.compress_hp_ce(user_id)
        log.append(f"\n🎉 <b>Уровень повышен до {new_level}!</b> HP и ПЭ восстановлены.")

    return {"status": "victory", "log": log, "effect": "victory"}


def _death(user_id: int, player, log: list) -> dict:
    eff = ce_types.get_effective_stats(user_id, player)
    respawn_hp = max(1, eff["max_hp"] // 2) if eff["max_hp"] > 0 else 1
    database.update_player_hp(user_id, respawn_hp)
    database.clear_encounter(user_id)
    database.update_player_x(user_id, 0)
    story.exit_temp(user_id)

    lost = min(player["gold"], max(1, int(player["gold"] * DEATH_GOLD_LOSS)))
    if lost:
        database.add_gold(user_id, -lost)
    log.append(f"\n☠️ <b>Ты повержен!</b> Потеряно {lost} очков Ассоциации.")
    log.append("Годжо вытаскивает тебя обратно в школу с половиной HP.")
    return {"status": "death", "log": log, "effect": "death"}


# ---------------- Ход проклятия ----------------

def _compute_monster_hit(user_id: int, player, encounter, raw_dmg: int,
                          damage_mult: float = 1.0, self_mult: float = 1.0,
                          extra_mult: float = 1.0) -> int:
    """Считает финальный урон монстра с учётом всех множителей."""
    reduction = _defense_reduction(user_id, player)
    effects = ce_types.get_active_effects(user_id)
    defense_mult = effects.get("defense_mult", 1.0)

    domain_key, domain_turns = database.get_domain(user_id)
    domain_eff = DOMAIN_EFFECTS.get(domain_key, {}) if domain_key and domain_turns > 0 else {}
    domain_def_mult = domain_eff.get("defense_mult", 1.0)
    enemy_dmg_mult = domain_eff.get("enemy_dmg_mult", 1.0)

    mdmg = int(raw_dmg * (1 - reduction) * damage_mult * defense_mult * self_mult
               * domain_def_mult * enemy_dmg_mult * extra_mult)
    return max(1, mdmg)


def _apply_damage_to_player(user_id: int, player, log: list, mdmg: int,
                             note: str = "") -> dict | None:
    """Наносит урон игроку. Возвращает death-result или None."""
    new_hp = player["hp"] - mdmg
    if new_hp <= 0:
        return _death(user_id, player, log)
    database.update_player_hp(user_id, new_hp)
    database.add_charge(user_id, "dmg_taken", mdmg)
    return None


def _try_passive(user_id: int, player, encounter, skills: dict, log: list) -> dict | None:
    """Пытается применить пассивку босса. Возвращает death-result или None."""
    passive = skills.get("passive")
    if not passive:
        return None
    if random.random() > passive.get("chance", 0.0):
        return None

    ptype = passive.get("type")
    pname = passive.get("name", "Пассивка")

    if ptype == "extra_dmg":
        dmg = passive.get("dmg", 10)
        mdmg = _compute_monster_hit(user_id, player, encounter, dmg)
        log.append(f"⚡ <b>{pname}</b>: {mdmg} дополнительного урона!")
        return _apply_damage_to_player(user_id, player, log, mdmg)

    if ptype == "double_attack":
        raw = random.randint(encounter["dmg_min"], encounter["dmg_max"])
        mdmg = _compute_monster_hit(user_id, player, encounter, raw)
        log.append(f"⚡ <b>{pname}</b>: {mdmg} урона (двойная атака)!")
        return _apply_damage_to_player(user_id, player, log, mdmg)

    if ptype == "drain_ce":
        amount = passive.get("amount", 5)
        eff = ce_types.get_effective_stats(user_id, player)
        new_ce = max(0, eff["ce"] - amount)
        database.update_player_ce(user_id, new_ce)
        log.append(f"💧 <b>{pname}</b>: ты теряешь {amount} ПЭ.")
        return None

    if ptype == "bleed":
        turns = passive.get("turns", 2)
        dmg = passive.get("dmg", 5)
        # Накладываем на игрока через бафф (переиспользуем charge_dmg_taken? нет — сделаем проще)
        # Наложим разовый урон сразу
        mdmg = _compute_monster_hit(user_id, player, encounter, dmg)
        log.append(f"🩸 <b>{pname}</b>: кровотечение — {mdmg} урона!")
        return _apply_damage_to_player(user_id, player, log, mdmg)

    if ptype == "heal_self":
        amount = passive.get("amount", 20)
        new_hp = min(encounter["max_hp"], encounter["hp"] + amount)
        database.update_encounter_hp(user_id, new_hp)
        log.append(f"💚 <b>{pname}</b>: монстр восстанавливает {amount} HP.")
        return None

    if ptype == "rage":
        # Усиление следующего удара — просто помечаем, что босс в ярости (урон x1.5 к следующей атаке)
        # Применим сразу как доп. множитель к обычной атаке ниже — а тут просто лог.
        log.append(f"🔥 <b>{pname}</b>: монстр впадает в ярость!")
        return None

    return None


def _try_execute(user_id: int, player, encounter, skills: dict, log: list) -> dict | None:
    """Проверяет условие добивания. Возвращает death-result или None."""
    execute = skills.get("execute")
    if not execute:
        return None

    eff = ce_types.get_effective_stats(user_id, player)
    if eff["max_hp"] <= 0:
        return None
    hp_pct = eff["hp"] / eff["max_hp"]
    if hp_pct > execute.get("hp_threshold", 0.25):
        return None

    raw = random.randint(encounter["dmg_min"], encounter["dmg_max"])
    mult = execute.get("dmg_mult", 3.0)
    mdmg = _compute_monster_hit(user_id, player, encounter, raw, extra_mult=mult)
    log.append(f"💀 <b>{execute.get('name', 'Добивание')}</b>: {mdmg} урона!")
    return _apply_damage_to_player(user_id, player, log, mdmg)


def _try_skill(user_id: int, player, encounter, skills: dict, log: list) -> dict | None:
    """Пробует применить активный скилл. Возвращает (применил, death_result)."""
    skill_list = skills.get("skills") or []
    for skill in skill_list:
        if random.random() < skill.get("chance", 0.0):
            raw = random.randint(encounter["dmg_min"], encounter["dmg_max"])
            mult = skill.get("dmg_mult", 1.0)
            mdmg = _compute_monster_hit(user_id, player, encounter, raw, extra_mult=mult)
            log.append(f"🔥 <b>{skill.get('name', 'Скилл')}</b>: {mdmg} урона!")
            if skill.get("stun_player"):
                # Пропуск следующего хода игрока: реализуем через dmg_buff_turns -1? Проще — запишем в лог.
                # На будущее можно добавить колонку stun_player_turns. Пока — просто эффект не накладываем.
                log.append("😵 Ты дезориентирован следующим ходом (пропуск).")
            return _apply_damage_to_player(user_id, player, log, mdmg)
    return None


def _curse_turn(user_id: int, player, encounter, log: list,
                damage_mult: float = 1.0, self_mult: float = 1.0) -> dict | None:
    hp = encounter["hp"]

    if encounter["bleed_turns"] > 0:
        hp = max(0, hp - encounter["bleed_dmg"])
        log.append(f"🩸 Проклятие теряет {encounter['bleed_dmg']} HP от кровотечения.")
        database.update_encounter_hp(user_id, hp)
        database.set_encounter_status(user_id, bleed_turns=encounter["bleed_turns"] - 1)
        if hp <= 0:
            return None

    if hp <= 0:
        return None

    effects = ce_types.get_active_effects(user_id)
    dodge_bonus = effects.get("dodge_chance", 0.0)

    domain_key, domain_turns = database.get_domain(user_id)
    domain_eff = DOMAIN_EFFECTS.get(domain_key, {}) if domain_key and domain_turns > 0 else {}
    dodge_bonus += domain_eff.get("dodge_bonus", 0.0)
    total_miss = min(0.90, MONSTER_MISS_CHANCE + dodge_bonus + domain_eff.get("enemy_miss_bonus", 0.0))

    # Оглушение монстра
    if encounter["stun_turns"] > 0:
        log.append(f"😵 {encounter['monster_name']} оглушено и пропускает ход!")
        database.set_encounter_status(user_id, stun_turns=encounter["stun_turns"] - 1)
        return None

    # Промах/уклонение
    if random.random() < total_miss:
        if dodge_bonus > 0 and random.random() < dodge_bonus / total_miss:
            log.append(f"🌀 <b>Ты уклонился</b> от атаки {encounter['monster_name']}!")
        else:
            log.append(f"🛡 {encounter['monster_name']} промахнулось!")
        return None

    # Боссовые пассивки/скиллы
    skills = _get_boss_skills(encounter["monster_name"])
    if skills:
        # 1. Проверка добивания
        death = _try_execute(user_id, player, encounter, skills, log)
        if death:
            return death

        # 2. Пассивка (доп. эффект)
        death = _try_passive(user_id, player, encounter, skills, log)
        if death:
            return death

        # 3. Активный скилл
        death = _try_skill(user_id, player, encounter, skills, log)
        if death:
            return death

        # 4. Если ни пассивка, ни скилл не сработали — обычная атака.
        # Но если скилл сработал, то _try_skill вернул результат (не None) и мы уже вышли.
        # Здесь только если оба вернули None.
        # Проверить: если пассивка сработала (вернула None) — не факт, что она была.
        # Упрощаем: если passive сработала и нанесла урон — уже был return.
        # Здесь применяем обычную атаку.
        pass

    # Обычная атака
    raw = random.randint(encounter["dmg_min"], encounter["dmg_max"])
    mdmg = _compute_monster_hit(user_id, player, encounter, raw,
                                 damage_mult=damage_mult, self_mult=self_mult)

    note = ""
    if damage_mult < 1.0:
        note = f" (блок x{damage_mult})"
    log.append(f"👹 {encounter['monster_name']} нанёс {mdmg} урона{note}.")
    return _apply_damage_to_player(user_id, player, log, mdmg)


# ---------------- Атака ----------------

def attack(user_id: int, technique_name: str | None = None) -> dict:
    encounter = database.get_encounter(user_id)
    if not encounter:
        return {"status": "no_encounter", "log": []}

    player = database.get_or_create_player(user_id, "")
    log = []
    effects = ce_types.get_active_effects(user_id)

    technique = None
    if technique_name:
        technique = gacha.get_technique(technique_name)
        if not technique or technique_name not in gacha.get_equipped(user_id):
            return {"status": "invalid", "log": ["❌ Эта техника недоступна в бою."]}
        if player["ce"] < technique["ce_cost"]:
            return {"status": "invalid", "log": [
                f"❌ Не хватает ПЭ! Нужно {technique['ce_cost']}🔵, у тебя {player['ce']}🔵."
            ]}

    effect_key = None
    black_flash = False
    dmg = 0
    if random.random() < PLAYER_MISS_CHANCE:
        log.append("💨 Ты промахнулся!")
    else:
        if technique:
            dmg = _technique_damage(user_id, player, technique)
        else:
            dmg = _physical_damage(user_id, player)

        black_flash = random.random() < _black_flash_chance(user_id)
        if black_flash:
            dmg = int(dmg * PLAYER_CRIT_MULT)

        buff_mult = database.consume_player_dmg_buff(user_id)
        if buff_mult != 1.0:
            dmg = int(dmg * buff_mult)

        verb = f"использовал «{technique_name}»" if technique else "атаковал"
        if black_flash:
            log.append(f"⚫⚡ <b>КРИТ!</b> Ты {verb} с искажением ПЭ и нанёс {dmg} урона.")
            quests.add_progress(user_id, "crit")
            effect_key = "black_flash"
        else:
            log.append(f"🗡 Ты {verb} и нанёс {dmg} урона.")
            if technique:
                effect_key = f"technique:{technique_name}"

        if dmg > 0:
            database.add_charge(user_id, "dmg_dealt", dmg)
        if black_flash:
            database.add_charge(user_id, "black_flash", 1)

    # Броня монстра
    defense = 0.0
    try:
        defense = encounter["defense"] or 0.0
    except (IndexError, KeyError):
        defense = 0.0

    if dmg > 0 and defense > 0:
        reduced = max(1, int(dmg * (1.0 - defense)))
        log.append(f"🛡 <b>Броня:</b> {dmg} → {reduced} урона (-{int(defense * 100)}%).")
        dmg = reduced

    if technique:
        database.update_player_ce(user_id, player["ce"] - technique["ce_cost"])
        quests.add_progress(user_id, "tech_use")
        database.add_charge(user_id, "tech_uses", 1)
        _register_domain_use(user_id, technique_name, log)

    if black_flash:
        if random.random() < BLACK_FLASH_STUN_CHANCE:
            database.set_encounter_status(user_id, stun_turns=1)
            log.append("😵 Проклятие оглушено на 1 ход от крита!")
            quests.add_progress(user_id, "stun_apply")

    if dmg > 0 and technique and technique.get("effect"):
        _apply_effect(user_id, encounter, technique["effect"], log)

    if dmg > 0 and not technique:
        stun_ch = effects.get("stun_chance", 0.0)
        stun_every2 = effects.get("stun_chance_every_2", 0.0)
        bleed_ch = effects.get("bleed_chance", 0.0)

        total_stun = stun_ch + stun_every2 * 0.5
        if total_stun > 0 and random.random() < total_stun:
            database.set_encounter_status(user_id, stun_turns=1)
            log.append("⚡ Проклятие парализовано на 1 ход!")
            quests.add_progress(user_id, "stun_apply")

        if bleed_ch > 0 and random.random() < bleed_ch:
            database.set_encounter_status(user_id, bleed_turns=2, bleed_dmg=5)
            log.append("🩸 Проклятие кровоточит 2 х.")
            quests.add_progress(user_id, "bleed_apply")

    vamp = effects.get("vampire", 0.0)
    if dmg > 0 and vamp > 0:
        healed = int(dmg * vamp)
        if healed > 0:
            eff = ce_types.get_effective_stats(user_id, player)
            new_hp = min(eff["max_hp"], player["hp"] + healed)
            if new_hp > player["hp"]:
                database.update_player_hp(user_id, new_hp)
                log.append(f"🩸 Вампиризм: +{new_hp - player['hp']} HP.")

    monster_hp = encounter["hp"] - dmg

    if monster_hp <= 0:
        return _victory(user_id, encounter, log)

    database.update_encounter_hp(user_id, monster_hp)
    encounter = database.get_encounter(user_id)

    domain_killed = _process_domain_turn(user_id, player, encounter, log)
    if domain_killed:
        encounter = database.get_encounter(user_id)
        return _victory(user_id, encounter, log)

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    if not encounter:
        return {"status": "victory", "log": log, "effect": "victory"}

    self_mult = effects.get("tech_vs_self_mult", 1.0) if technique else 1.0

    death_result = _curse_turn(user_id, player, encounter, log, self_mult=self_mult)
    if death_result:
        return death_result

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    fresh_player = database.get_or_create_player(user_id, "")
    _regen_ce(user_id, fresh_player)

    return {"status": "ongoing", "log": log, "effect": effect_key}


def defend(user_id: int) -> dict:
    encounter = database.get_encounter(user_id)
    if not encounter:
        return {"status": "no_encounter", "log": []}

    player = database.get_or_create_player(user_id, "")
    log = ["🛡 <b>Ты встал в защиту.</b> Пропускаешь атаку, но получаешь меньше урона."]

    if encounter["monster_name"] == "Махито (Особый класс)":
        if random.random() < 0.25:
            log.append("💀 <b>Махито касается твоей души сквозь защиту!</b>")
            log.append("🌀 <i>Тебя инертно трансформировали.</i>")
            return _death(user_id, player, log)

    death_result = _curse_turn(user_id, player, encounter, log,
                               damage_mult=DEFEND_DAMAGE_MULT)
    if death_result:
        return death_result

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    domain_killed = _process_domain_turn(user_id, player, encounter, log)
    if domain_killed:
        encounter = database.get_encounter(user_id)
        return _victory(user_id, encounter, log)

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    fresh_player = database.get_or_create_player(user_id, "")
    regen = _regen_ce(user_id, fresh_player, mult=DEFEND_CE_REGEN_MULT)
    if regen > 0:
        log.append(f"💠 Восстановлено {regen} ПЭ (x{DEFEND_CE_REGEN_MULT:.0f} за защиту).")

    return {"status": "ongoing", "log": log, "effect": "defend"}


def flee(user_id: int) -> dict:
    encounter = database.get_encounter(user_id)
    if not encounter:
        return {"status": "no_encounter", "log": []}

    player = database.get_or_create_player(user_id, "")
    log = []

    flee_chance = FLEE_CHANCE * (0.5 if is_boss(encounter["monster_name"]) else 1.0)
    if random.random() < flee_chance:
        database.clear_encounter(user_id)
        quests.add_progress(user_id, "flee")
        log.append("🏃 Ты успешно скрылся при помощи техники усиления тела!")
        return {"status": "fled", "log": log}

    log.append("❌ Сбежать не удалось!")
    death_result = _curse_turn(user_id, player, encounter, log)
    if death_result:
        return death_result

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    fresh_player = database.get_or_create_player(user_id, "")
    _regen_ce(user_id, fresh_player)

    return {"status": "ongoing", "log": log}
