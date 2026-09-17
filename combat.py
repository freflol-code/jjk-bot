"""
Пошаговая боевая система «Магическая Битва: Токио».

Ход игрока (обычная атака ИЛИ врождённая техника) -> ход проклятия.
Всё завязано на стате "Контроль ПЭ".

С учётом оружия (equipment.py):
  - dmg_bonus_min/max прибавляются к физ. урону;
  - tech_power умножает урон врождённых техник;
  - crit_bonus повышает шанс Чёрной Вспышки.

С учётом активных баффов (реальное время, database.get_active_buffs):
  - dmg_bonus          — множитель физ. урона и урона техник;
  - defense_bonus      — плюс к защите (капается DEFENSE_CAP);
  - ce_regen_bonus     — множитель регена ПЭ;
  - crit_bonus         — плюс к шансу Чёрной Вспышки;
  - exp_bonus/gold_bonus — множители наград в _victory.

Крит оформлен как Чёрная Вспышка (Black Flash): двойной урон плюс шанс стана.

Награды за обычных проклятий умножаются на CLASS_REWARD_MULT в зависимости
от класса: 4-й ×1.0, 3-й ×1.3, 2-й ×1.7, 1-й ×2.5. У боссов Особого класса
награды фиксированные (не применяется множитель).

Печати (ритуальные предметы) дропаются с rarity="призыв" — это позволяет
показывать кнопку «⚡ Призвать» в инвентаре и блокирует продажу Хакари.
"""
import random

import database
import gacha
import quests
import equipment
import story
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


# ---------------- Формулы от "Контроля ПЭ" ----------------

def _defense_reduction(user_id: int, player) -> float:
    base = player["ce_control"] * DEFENSE_CE_COEF
    bonus = database.get_buff_value(user_id, "defense_bonus")
    return min(DEFENSE_CAP, base + bonus)


def _ce_regen_amount(user_id: int, player) -> int:
    base = CE_REGEN_BASE + player["ce_control"] * CE_REGEN_CE_COEF
    bonus = database.get_buff_value(user_id, "ce_regen_bonus")
    if bonus:
        base = base * (1 + bonus)
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
    return dmg


def _technique_damage(user_id: int, player, technique: dict) -> int:
    base = random.randint(technique["dmg_min"], technique["dmg_max"])
    coef = 1 + player["ce_control"] * TECH_CE_COEF
    w = equipment.get_bonuses(user_id)
    dmg = int(base * coef * w["tech_power"])
    buff = database.get_buff_value(user_id, "dmg_bonus")
    if buff:
        dmg = int(dmg * (1 + buff))
    return dmg


def _black_flash_chance(user_id: int) -> float:
    w = equipment.get_bonuses(user_id)
    buff = database.get_buff_value(user_id, "crit_bonus")
    return min(0.5, PLAYER_CRIT_CHANCE + w["crit_bonus"] + buff)


def _regen_ce(user_id: int, player):
    regen = _ce_regen_amount(user_id, player)
    new_ce = min(player["max_ce"], player["ce"] + regen)
    database.update_player_ce(user_id, new_ce)


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


def player_status_text(player) -> str:
    need = player["level"] * EXP_BASE
    buff_line = ""
    if player["dmg_buff_turns"]:
        buff_line = f" | 🔥 Бафф урона x{player['dmg_buff_mult']:.2f} ({player['dmg_buff_turns']} х.)"
    return (
        f"❤️ HP: {player['hp']}/{player['max_hp']} | "
        f"🔵 ПЭ: {player['ce']}/{player['max_ce']}\n"
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

    # Печати (ритуальные) — особый тип предметов с rarity="призыв",
    # чтобы в инвентаре появлялась кнопка «⚡ Призвать» и их нельзя было продать.
    if item_name in SUMMON_RECIPES:
        rarity = "призыв"
        qty = 1
    else:
        qty = roll_quantity(rarity)

    database.add_item(user_id, item_name, rarity, qty)
    emoji = RARITY_EMOJI.get(rarity, "⚪")
    return f"🎁 Дроп: {emoji} {item_name} x{qty} ({rarity})"


# ---------------- Общая обработка эффекта техники ----------------

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


# ---------------- Победа и смерть ----------------

def _story_tracking(user_id: int, encounter, log: list):
    """Сюжетный трекинг: считаем обычные убийства и убийства боссов,
    а также выдаём гарантированный дроп с сюжетного босса."""
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
    """Если монстр — сюжетный босс из temp-локации, вернёт его dict."""
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

    # --- Босс Особого класса (обычный или сюжетный) ---
    if boss or story_boss:
        source = boss or story_boss
        gold = source["reward_gold"]
        exp = source["reward_exp"]
        if gold_buff:
            gold = int(gold * (1 + gold_buff))
        if exp_buff:
            exp = int(exp * (1 + exp_buff))

        database.add_gold(user_id, gold)
        new_level, leveled = database.add_exp_and_level(user_id, exp)

        log.append(f"\n👑 <b>{encounter['monster_name']} ИЗГНАНО!</b>")
        log.append(f"💠 +{gold} очков Ассоциации, 🧬 +{exp} опыта")

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
            log.append(f"\n🎉 <b>Уровень повышен до {new_level}!</b> HP и ПЭ восстановлены.")
        return {"status": "victory", "log": log, "effect": "boss_victory"}

    # --- Обычное проклятие ---
    curse_class = encounter["curse_class"] or "4-й класс"
    class_mult = CLASS_REWARD_MULT.get(curse_class, 1.0)

    gold = max(3, int(encounter["max_hp"] * GOLD_PER_HP * class_mult))
    exp = max(5, int(encounter["max_hp"] * EXP_PER_HP * class_mult))
    if gold_buff:
        gold = int(gold * (1 + gold_buff))
    if exp_buff:
        exp = int(exp * (1 + exp_buff))

    database.add_gold(user_id, gold)
    new_level, leveled = database.add_exp_and_level(user_id, exp)

    log.append(f"\n🏆 <b>{encounter['monster_name']} изгнано!</b>")
    log.append(f"💠 +{gold} очков Ассоциации, 🧬 +{exp} опыта")

    quests.add_progress(user_id, "gold_earn", amount=gold)
    quests.add_progress(user_id, "exp_earn", amount=exp)
    quests.add_progress(user_id, "kill", target=encounter["curse_class"])

    drop_line = _roll_drop(user_id, encounter)
    if drop_line:
        log.append(drop_line)

    _story_tracking(user_id, encounter, log)

    if leveled:
        quests.add_progress(user_id, "level_up")
        log.append(f"\n🎉 <b>Уровень повышен до {new_level}!</b> HP и ПЭ восстановлены.")

    return {"status": "victory", "log": log, "effect": "victory"}


def _death(user_id: int, player, log: list) -> dict:
    respawn_hp = max(1, player["max_hp"] // 2)
    database.update_player_hp(user_id, respawn_hp)
    database.clear_encounter(user_id)
    database.update_player_x(user_id, 0)

    # Если игрок погиб в сюжетной temp-локации — выкидываем его оттуда,
    # иначе он застрянет: будет в школе, но с флагом in_temp=True.
    story.exit_temp(user_id)

    lost = min(player["gold"], max(1, int(player["gold"] * DEATH_GOLD_LOSS)))
    if lost:
        database.add_gold(user_id, -lost)
    log.append(f"\n☠️ <b>Ты повержен!</b> Потеряно {lost} очков Ассоциации.")
    log.append("Годжо вытаскивает тебя обратно в школу с половиной HP.")
    return {"status": "death", "log": log, "effect": "death"}


def _curse_turn(user_id: int, player, encounter, log: list) -> dict | None:
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
        mdmg = max(1, int(raw * (1 - reduction)))
        new_hp = player["hp"] - mdmg
        if new_hp <= 0:
            return _death(user_id, player, log)
        database.update_player_hp(user_id, new_hp)
        log.append(f"👹 {encounter['monster_name']} нанёс {mdmg} урона (защита -{int(reduction*100)}%).")

    return None


def attack(user_id: int, technique_name: str | None = None) -> dict:
    encounter = database.get_encounter(user_id)
    if not encounter:
        return {"status": "no_encounter", "log": []}

    player = database.get_or_create_player(user_id, "")
    log = []

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

    monster_hp = encounter["hp"] - dmg

    if monster_hp <= 0:
        return _victory(user_id, encounter, log)

    database.update_encounter_hp(user_id, monster_hp)
    encounter = database.get_encounter(user_id)

    death_result = _curse_turn(user_id, player, encounter, log)
    if death_result:
        return death_result

    encounter = database.get_encounter(user_id)
    if encounter and encounter["hp"] <= 0:
        return _victory(user_id, encounter, log)

    fresh_player = database.get_or_create_player(user_id, "")
    _regen_ce(user_id, fresh_player)

    return {"status": "ongoing", "log": log, "effect": effect_key}


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