"""
Работа с картинками и гифками для районов, монстров, НПС, техник и эффектов.

Структура:
    assets/biomes/<district_id>.(jpg|jpeg|png|gif|mp4)
    assets/monsters/<sanitize_name(monster_name)>.(...)
    assets/npcs/<npc_id>.(...)
    assets/techniques/<sanitize_name(technique_name)>.(...)
    assets/effects/<effect_key>.(...)

Расширения ищутся в порядке: .jpg → .jpeg → .png → .gif → .mp4.
В каждой папке можно положить _default.<ext> — он покажется, если
для конкретного объекта файла нет.

Если файла нет вообще — функция возвращает None, а вызывающий код
откатывается на текстовый режим.
"""
import os
import re

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
BIOMES_DIR = os.path.join(ASSETS_DIR, "biomes")
MONSTERS_DIR = os.path.join(ASSETS_DIR, "monsters")
NPCS_DIR = os.path.join(ASSETS_DIR, "npcs")
TECHNIQUES_DIR = os.path.join(ASSETS_DIR, "techniques")
EFFECTS_DIR = os.path.join(ASSETS_DIR, "effects")

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".mp4")

_biome_cache: dict[str, str | None] = {}
_monster_cache: dict[str, str | None] = {}
_npc_cache: dict[str, str | None] = {}
_technique_cache: dict[str, str | None] = {}
_effect_cache: dict[str, str | None] = {}


def sanitize_name(name: str) -> str:
    """
    Превращает имя в безопасное имя файла:
    - нижний регистр
    - пробелы -> "_"
    - удаляются все символы, кроме букв/цифр/подчёркивания/дефиса
    - сохраняется буква "ё"

    "Клык Тьмы (1-й класс)" -> "клык_тьмы_1-й_класс"
    "🐝 Королева пчёл"      -> "королева_пчёл"
    """
    name = name.strip().lower()
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-zа-яё0-9_\-]", "", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name


def _find_file(directory: str, base_name: str) -> str | None:
    """Ищет файл: сначала конкретный, потом _default, потом None."""
    if not base_name:
        return None
    for ext in IMAGE_EXTENSIONS:
        path = os.path.join(directory, base_name + ext)
        if os.path.isfile(path):
            return path
    for ext in IMAGE_EXTENSIONS:
        path = os.path.join(directory, "_default" + ext)
        if os.path.isfile(path):
            return path
    return None


def is_animation(path: str | None) -> bool:
    """True, если файл — анимация (.gif или .mp4)."""
    if not path:
        return False
    return path.lower().endswith((".gif", ".mp4"))


# ---------------- Районы ----------------

def get_biome_image(biome_id: str) -> str | None:
    if biome_id in _biome_cache:
        return _biome_cache[biome_id]
    path = _find_file(BIOMES_DIR, biome_id)
    _biome_cache[biome_id] = path
    return path


# ---------------- Проклятия ----------------

def get_monster_image(monster_name: str) -> str | None:
    """Ищет по ПОЛНОМУ имени, как оно приходит из encounter (с классом в скобках)."""
    if monster_name in _monster_cache:
        return _monster_cache[monster_name]
    path = _find_file(MONSTERS_DIR, sanitize_name(monster_name))
    _monster_cache[monster_name] = path
    return path


# ---------------- НПС ----------------

def get_npc_image(npc_id: str) -> str | None:
    if npc_id in _npc_cache:
        return _npc_cache[npc_id]
    path = _find_file(NPCS_DIR, npc_id)
    _npc_cache[npc_id] = path
    return path


# ---------------- Техники ----------------

def get_technique_image(technique_name: str) -> str | None:
    if technique_name in _technique_cache:
        return _technique_cache[technique_name]
    path = _find_file(TECHNIQUES_DIR, sanitize_name(technique_name))
    _technique_cache[technique_name] = path
    return path


# ---------------- Эффекты ----------------

def get_effect_image(effect_key: str) -> str | None:
    """effect_key: black_flash, victory, death, level_up, encounter_start и т.д."""
    if effect_key in _effect_cache:
        return _effect_cache[effect_key]
    path = _find_file(EFFECTS_DIR, effect_key)
    _effect_cache[effect_key] = path
    return path