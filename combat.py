"""
Пошаговая боевая система «Магическая Битва: Токио».
Учитывает эффекты типа ПЭ, клана и Проклятия Небес.
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
)
from loot import roll_quantity
from bosses import BOSSES, is_boss, SUMMON_RECIPES


CLASS_REWARD_MULT = {
    "4-й класс": 1.0,
    "3-й класс": 1.3,
    "2-й класс": 1.7,
    "1-й класс": 2.5,
}

DEFEND_DAMAGE_MULT = 0.5
DEFEND_CE_REGEN_MULT = 2.0


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
    return dmg


def _black_flash_chance(user_id: int) -> float:
    w = equipment.get_bonuses(user_id)
    buff = database.get_buff_value(user_id, "crit_bonus")
    effects = ce_types.get_active_effects(user_id)
    return min(0.75, PLAYER_CRIT_CHANCE + w["crit_bonus"] + buff + effects.get("crit_bonus", 0.0))


def _regen_ce(user_id: int, player, mult: float = 1.0):
    eff = ce_types.get_effective_stats(user_id, player)
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
    return (
        f"{prefix}{class_emoji} {encounter['emoji']} <b>{encounter['monster_name']}</b>\n"
        f"❤️ HP: {hp}/{encounter['max_hp']}\n"
        f"🗡 Урон: {encounter['dmg_min']}-{encounter['dmg_max']}"
        f"{status_line}"
    )


def player_status_text(player, user_id: int | None = None) -> str:
    """Если user_id передан, используются эффективные max_hp/max_ce."""
    if user_id:
        eff = ce_types.get_effective_stats(user_id, player)
    else:
        eff = {"hp": player["hp"], "max_hp": player["max_hp"],
               "ce": player["ce"], "max_ce": player["max_ce"]}

    need = player["level"] * EXP_BASE
    buff_line = ""
    if player["dmg_buff_turns"]:
        buff_line = f" | 🔥 Бафф урона x{player['dmg_buff_mult']:.2f} ({player['dmg_buff_turns']} х.)"
    return (
        f"❤️ HP: {eff['hp']}/{eff['max_hp']} | "
        f"🔵 ПЭ: {eff['ce']}/{eff['max_ce']}\n"
        f"💠 {player['gold']} | 🧬 Ур. {player['level']} ({player['exp']}/{need}) | "
        f"🎚 Контроль ПЭ: {player['ce_control']}"
        f"{buff_line}"
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
    vip_mult = 2.0 if database.has_vip(user_id) else 1.0

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
    respawn_hp = max(1, eff["max_hp"] // 2)
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

    if encounter["stun_turns"] > 0:
        log.append(f"😵 {encounter['monster_name']} оглушено и пропускает ход!")
        database.set_encounter_status(user_id, stun_turns=encounter["stun_turns"] - 1)
    elif random.random() < MONSTER_MISS_CHANCE:
        log.append(f"🛡 {encounter['monster_name']} промахнулось!")
    else:
        raw = random.randint(encounter["dmg_min"], encounter["dmg_max"])
        reduction = _defense_reduction(user_id, player)

        effects = ce_types.get_active_effects(user_id)
        defense_mult = effects.get("defense_mult", 1.0)

        mdmg = int(raw * (1 - reduction) * damage_mult * defense_mult * self_mult)
        mdmg = max(1, mdmg)

        new_hp = player["hp"] - mdmg
        if new_hp <= 0:
            return _death(user_id, player, log)
        database.update_player_hp(user_id, new_hp)

        note = f"(защита -{int(reduction*100)}%"
        if damage_mult < 1.0:
            note += f", блок x{damage_mult}"
        if defense_mult < 1.0:
            note += f", ПЭ x{defense_mult:.2f}"
        if self_mult > 1.0:
            note += f", тех x{self_mult:.2f}"
        note += ")"
        log.append(f"👹 {encounter['monster_name']} нанёс {mdmg} урона {note}.")

    return None


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
    if random.random() < PLAYER_MISS_CHANCE:
        log.append("💨 Ты промахнулся!")
        dmg = 0
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
            log.append(f"⚫⚡ <b>ЧЁРНАЯ ВСПЫШКА!</b> Ты {verb} с искажением ПЭ и нанёс {dmg} урона.")
            quests.add_progress(user_id, "crit")
            effect_key = "black_flash"
        else:
            log.append(f"🗡 Ты {verb} и нанёс {dmg} урона.")
            if technique:
                effect_key = f"technique:{technique_name}"

    if technique:
        database.update_player_ce(user_id, player["ce"] - technique["ce_cost"])
        quests.add_progress(user_id, "tech_use")

    if black_flash:
        if random.random() < BLACK_FLASH_STUN_CHANCE:
            database.set_encounter_status(user_id, stun_turns=1)
            log.append("😵 Проклятие оглушено на 1 ход от Чёрной Вспышки!")
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

    fresh_player = database.get_or_create_player(user_id, "")
    regen = _regen_ce(user_id, fresh_player, mult=DEFEND_CE_REGEN_MULT)
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
