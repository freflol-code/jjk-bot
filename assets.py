"""
Работа с картинками и гифками для районов, монстров, НПС, техник,
эффектов и Боевого пропуска.

Структура:
    assets/biomes/<district_id>.(jpg|jpeg|png|gif|mp4)
    assets/monsters/<sanitize_name(monster_name)>.(...)
    assets/npcs/<npc_id>.(...)
    assets/techniques/<sanitize_name(technique_name)>.(...)
    assets/effects/<effect_key>.(...)
    assets/battle_pass/<season_id>.(...)       ← обложка сезона БП
    assets/battle_pass/_default.(...)          ← fallback для всех сезонов
    assets/battle_pass/level_<N>.(...)         ← опционально: картинка на уровень

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
BATTLE_PASS_DIR = os.path.join(ASSETS_DIR, "battle_pass")

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".mp4")

_biome_cache = {}
_monster_cache = {}
_npc_cache = {}
_technique_cache = {}
_effect_cache = {}
_battle_pass_cache = {}


def sanitize_name(name):
    """Превращает имя в безопасное имя файла.
    "Клык Тьмы (1-й класс)" -> "клык_тьмы_1-й_класс"
    "🐝 Королева пчёл"      -> "королева_пчёл"
    """
    name = name.strip().lower()
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-zа-яё0-9_\-]", "", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name


def _find_file(directory, base_name):
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


def _find_file_strict(directory, base_name):
    """Ищет ТОЛЬКО конкретный файл. Без fallback на _default.
    Полезно для наград, где default не нужен."""
    if not base_name:
        return None
    for ext in IMAGE_EXTENSIONS:
        path = os.path.join(directory, base_name + ext)
        if os.path.isfile(path):
            return path
    return None


def is_animation(path):
    """True, если файл — анимация (.gif или .mp4)."""
    if not path:
        return False
    return path.lower().endswith((".gif", ".mp4"))


# ---------------- Районы ----------------

def get_biome_image(biome_id):
    if biome_id in _biome_cache:
        return _biome_cache[biome_id]
    path = _find_file(BIOMES_DIR, biome_id)
    _biome_cache[biome_id] = path
    return path


# ---------------- Проклятия ----------------

def get_monster_image(monster_name):
    if monster_name in _monster_cache:
        return _monster_cache[monster_name]
    path = _find_file(MONSTERS_DIR, sanitize_name(monster_name))
    _monster_cache[monster_name] = path
    return path


# ---------------- НПС ----------------

def get_npc_image(npc_id):
    if npc_id in _npc_cache:
        return _npc_cache[npc_id]
    path = _find_file(NPCS_DIR, npc_id)
    _npc_cache[npc_id] = path
    return path


# ---------------- Техники ----------------

def get_technique_image(technique_name):
    if technique_name in _technique_cache:
        return _technique_cache[technique_name]
    path = _find_file(TECHNIQUES_DIR, sanitize_name(technique_name))
    _technique_cache[technique_name] = path
    return path


# ---------------- Эффекты ----------------

def get_effect_image(effect_key):
    if effect_key in _effect_cache:
        return _effect_cache[effect_key]
    path = _find_file(EFFECTS_DIR, effect_key)
    _effect_cache[effect_key] = path
    return path


# ---------------- Боевой пропуск ----------------

def get_battle_pass_image(season_id):
    """Обложка сезона БП.
    Ищет assets/battle_pass/<season_id>.<ext> (например s1.jpg).
    Если нет — assets/battle_pass/_default.<ext>.
    """
    if not season_id:
        return None
    key = season_id.lower()
    if key in _battle_pass_cache:
        return _battle_pass_cache[key]
    path = _find_file(BATTLE_PASS_DIR, key)
    _battle_pass_cache[key] = path
    return path


def get_battle_pass_level_image(level):
    """Опциональная картинка конкретного уровня БП.
    Ищет assets/battle_pass/level_<N>.<ext>. Без fallback на _default,
    чтобы не путать с обложкой сезона."""
    if level is None:
        return None
    key = f"level_{int(level)}"
    if key in _battle_pass_cache:
        return _battle_pass_cache[key]
    path = _find_file_strict(BATTLE_PASS_DIR, key)
    _battle_pass_cache[key] = path
    return path


def list_battle_pass_assets():
    """Возвращает список файлов в папке assets/battle_pass/ (для отладки)."""
    if not os.path.isdir(BATTLE_PASS_DIR):
        return []
    result = []
    for fname in os.listdir(BATTLE_PASS_DIR):
        path = os.path.join(BATTLE_PASS_DIR, fname)
        if os.path.isfile(path) and fname.lower().endswith(IMAGE_EXTENSIONS):
            result.append(fname)
    return sorted(result)
