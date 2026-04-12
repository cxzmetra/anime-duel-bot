import discord
from discord.ext import commands
from discord import ui
import random
import asyncio
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import sqlite3
import os
import json

# === БАЗА ДАННЫХ SQLite ===
conn = sqlite3.connect("duel_bot.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 100,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    mmr INTEGER DEFAULT 1000,
    class TEXT DEFAULT '🗡️ Воин',
    weapon TEXT DEFAULT NULL,
    armor TEXT DEFAULT NULL,
    title TEXT DEFAULT NULL,
    daily_last TEXT DEFAULT NULL,
    daily_streak INTEGER DEFAULT 0,
    achievements TEXT DEFAULT '[]',
    daily_quests TEXT DEFAULT '{}',
    quests_completed TEXT DEFAULT '[]'
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS unlocked_classes (
    user_id INTEGER,
    class_name TEXT,
    PRIMARY KEY (user_id, class_name)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS unlocked_weapons (
    user_id INTEGER,
    weapon_name TEXT,
    PRIMARY KEY (user_id, weapon_name)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS unlocked_armors (
    user_id INTEGER,
    armor_name TEXT,
    PRIMARY KEY (user_id, armor_name)
)
""")

conn.commit()

# === ФУНКЦИИ БД ===
def get_player(user_id: int) -> dict:
    cur.execute("SELECT * FROM players WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    
    if not row:
        cur.execute("INSERT INTO players (user_id) VALUES (?)", (user_id,))
        conn.commit()
        cur.execute("INSERT INTO unlocked_classes (user_id, class_name) VALUES (?, ?)", (user_id, "🗡️ Воин"))
        conn.commit()
        cur.execute("SELECT * FROM players WHERE user_id=?", (user_id,))
        row = cur.fetchone()
    
    return {
        "user_id": row[0] if len(row) > 0 else user_id,
        "balance": row[1] if len(row) > 1 else 100,
        "wins": row[2] if len(row) > 2 else 0,
        "losses": row[3] if len(row) > 3 else 0,
        "mmr": row[4] if len(row) > 4 else 1000,
        "class": row[5] if len(row) > 5 else "🗡️ Воин",
        "weapon": row[6] if len(row) > 6 else None,
        "armor": row[7] if len(row) > 7 else None,
        "title": row[8] if len(row) > 8 else None,
        "daily_last": row[9] if len(row) > 9 else None,
        "daily_streak": row[10] if len(row) > 10 else 0,
        "achievements": row[11] if len(row) > 11 else "[]",
        "daily_quests": row[12] if len(row) > 12 else "{}",
        "quests_completed": row[13] if len(row) > 13 else "[]"
    }

def update_player(user_id: int, field: str, value):
    cur.execute(f"UPDATE players SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()

def get_unlocked_classes(user_id: int) -> List[str]:
    cur.execute("SELECT class_name FROM unlocked_classes WHERE user_id=?", (user_id,))
    return [row[0] for row in cur.fetchall()]

def unlock_class(user_id: int, class_name: str):
    cur.execute("INSERT OR IGNORE INTO unlocked_classes VALUES (?, ?)", (user_id, class_name))
    conn.commit()

def get_unlocked_weapons(user_id: int) -> List[str]:
    cur.execute("SELECT weapon_name FROM unlocked_weapons WHERE user_id=?", (user_id,))
    return [row[0] for row in cur.fetchall()]

def unlock_weapon(user_id: int, weapon_name: str):
    cur.execute("INSERT OR IGNORE INTO unlocked_weapons VALUES (?, ?)", (user_id, weapon_name))
    conn.commit()

def get_unlocked_armors(user_id: int) -> List[str]:
    cur.execute("SELECT armor_name FROM unlocked_armors WHERE user_id=?", (user_id,))
    return [row[0] for row in cur.fetchall()]

def unlock_armor(user_id: int, armor_name: str):
    cur.execute("INSERT OR IGNORE INTO unlocked_armors VALUES (?, ?)", (user_id, armor_name))
    conn.commit()

def get_balance(user_id: int) -> int:
    return get_player(user_id)["balance"]

def add_balance(user_id: int, amount: int):
    p = get_player(user_id)
    update_player(user_id, "balance", p["balance"] + amount)

def remove_balance(user_id: int, amount: int) -> bool:
    p = get_player(user_id)
    if p["balance"] < amount:
        return False
    update_player(user_id, "balance", p["balance"] - amount)
    return True

def update_mmr(winner_id: int, loser_id: int) -> tuple:
    winner = get_player(winner_id)
    loser = get_player(loser_id)
    
    K = 32
    expected_winner = 1 / (1 + 10 ** ((loser["mmr"] - winner["mmr"]) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner["mmr"] - loser["mmr"]) / 400))
    
    winner_change = int(K * (1 - expected_winner))
    loser_change = int(K * (0 - expected_loser))
    
    update_player(winner_id, "mmr", winner["mmr"] + winner_change)
    update_player(loser_id, "mmr", max(0, loser["mmr"] + loser_change))
    
    return winner_change, loser_change

# === ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ===
DAILY_QUEST_TEMPLATES = [
    {"name": "Тренировка", "desc": "Выиграть 1 дуэль", "target": 1, "reward": (5, 10), "type": "wins"},
    {"name": "Боец", "desc": "Выиграть 3 дуэли", "target": 3, "reward": (10, 15), "type": "wins"},
    {"name": "Ставки", "desc": "Сделать 2 ставки", "target": 2, "reward": (3, 8), "type": "bets"},
    {"name": "Урон", "desc": "Нанести 200 урона", "target": 200, "reward": (5, 12), "type": "damage"},
    {"name": "Лекарь", "desc": "Вылечить 100 HP", "target": 100, "reward": (4, 10), "type": "heal"},
]

def generate_daily_quests() -> dict:
    quests = random.sample(DAILY_QUEST_TEMPLATES, 3)
    return {
        "quests": quests,
        "progress": [0, 0, 0],
        "completed": [False, False, False],
        "claimed": [False, False, False],
        "last_reset": datetime.now().strftime("%Y-%m-%d")
    }

def get_daily_quests(user_id: int) -> dict:
    p = get_player(user_id)
    quests_str = p.get("daily_quests", "{}")
    
    if isinstance(quests_str, str):
        try:
            quests = json.loads(quests_str)
        except:
            quests = {}
    else:
        quests = quests_str
    
    if not quests:
        quests = generate_daily_quests()
        update_player(user_id, "daily_quests", json.dumps(quests))
        return quests
    
    last_reset = quests.get("last_reset", "")
    today = datetime.now().strftime("%Y-%m-%d")
    
    if last_reset != today:
        quests = generate_daily_quests()
        update_player(user_id, "daily_quests", json.dumps(quests))
    
    return quests

def update_quest_progress(user_id: int, quest_type: str, value: int = 1):
    quests = get_daily_quests(user_id)
    
    for i, quest in enumerate(quests["quests"]):
        if quests["completed"][i]:
            continue
        if quest["type"] == quest_type:
            quests["progress"][i] += value
            if quests["progress"][i] >= quest["target"]:
                quests["completed"][i] = True
    
    update_player(user_id, "daily_quests", json.dumps(quests))

def claim_quest_reward(user_id: int, quest_index: int) -> int:
    quests = get_daily_quests(user_id)
    
    if quest_index < 0 or quest_index >= 3:
        return 0
    if not quests["completed"][quest_index]:
        return 0
    if quests["claimed"][quest_index]:
        return 0
    
    quest = quests["quests"][quest_index]
    reward = random.randint(quest["reward"][0], quest["reward"][1])
    
    quests["claimed"][quest_index] = True
    update_player(user_id, "daily_quests", json.dumps(quests))
    add_balance(user_id, reward)
    
    return reward

# === НАСТРОЙКИ ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

ADMIN_ID = 916315142168379392  # ЗАМЕНИ НА СВОЙ ID

CURRENCY_NAME = "ДАЙР"
WIN_REWARD = 15

players_in_duel: set = set()
pending_duels: Dict[int, int] = {}
player_win_streak: Dict[int, int] = {}

# === КЛАССЫ (ПОЛНЫЙ СПИСОК) ===
CLASSES = {
    # СТАРТОВЫЙ
    "🗡️ Воин": {
        "price": 0, "anime": "🌀 Стартовый", "description": "Обычный боец",
        "hp": 180, "damage_min": 10, "damage_max": 18, "crit_chance": 0.15,
        "heal_min": 10, "heal_max": 20, "heavy_min": 20, "heavy_max": 35, "heavy_miss": 0.35,
        "block_chance": 0.25,
        "admin_only": False, "emoji": "🗡️",
        "skills": {"attack": "💥 Удар мечом", "heavy": "⚔️ Тяжёлый удар", "heal": "💊 Лечение", "block": "🛡️ Блок"}
    },
    
    # === JUJUTSU KAISEN ===
    "👁️ Годжо Сатору": {
        "price": 8000, "anime": "🔴 Jujutsu Kaisen", "description": "*Безграничная пустота*",
        "hp": 300, "damage_min": 40, "damage_max": 60, "crit_chance": 0.35,
        "heal_min": 25, "heal_max": 40, "heavy_min": 65, "heavy_max": 105, "heavy_miss": 0.15,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "👁️",
        "skills": {"attack": "🔴 Красный", "heavy": "🔵 Синий", "heal": "🔄 Обратное проклятие", "block": "♾️ Бесконечность"}
    },
    "🔥 Итадори Юджи": {
        "price": 5000, "anime": "🔴 Jujutsu Kaisen", "description": "*Сукуна внутри*",
        "hp": 240, "damage_min": 30, "damage_max": 45, "crit_chance": 0.25,
        "heal_min": 18, "heal_max": 30, "heavy_min": 48, "heavy_max": 75, "heavy_miss": 0.25,
        "block_chance": 0.20,
        "admin_only": False, "emoji": "🔥",
        "skills": {"attack": "👊 Чёрная вспышка", "heavy": "💀 Рассечение", "heal": "💪 Регенерация", "block": "🛡️ Защита"}
    },
    "🌑 Фушигуро Мегуми": {
        "price": 4500, "anime": "🔴 Jujutsu Kaisen", "description": "*Десять теней*",
        "hp": 210, "damage_min": 25, "damage_max": 40, "crit_chance": 0.20,
        "heal_min": 18, "heal_max": 25, "heavy_min": 43, "heavy_max": 68, "heavy_miss": 0.20,
        "block_chance": 0.22,
        "admin_only": False, "emoji": "🌑",
        "skills": {"attack": "🐺 Божественные псы", "heavy": "🐸 Жаба", "heal": "🌿 Теневой покров", "block": "🌑 Теневой блок"}
    },
    "💀 Сукуна": {
        "price": 12000, "anime": "🔴 Jujutsu Kaisen", "description": "*Король проклятий*",
        "hp": 375, "damage_min": 50, "damage_max": 80, "crit_chance": 0.40,
        "heal_min": 30, "heal_max": 50, "heavy_min": 73, "heavy_max": 125, "heavy_miss": 0.10,
        "block_chance": 0.15,
        "admin_only": False, "emoji": "💀",
        "skills": {"attack": "✂️ Рассечение", "heavy": "🔥 Открытие", "heal": "🩸 Регенерация", "block": "💀 Проклятый блок"}
    },
    "🔵 Тодо Аой": {
        "price": 4000, "anime": "🔴 Jujutsu Kaisen", "description": "*Буги-вуги*",
        "hp": 220, "damage_min": 28, "damage_max": 42, "crit_chance": 0.20,
        "heal_min": 15, "heal_max": 25, "heavy_min": 43, "heavy_max": 63, "heavy_miss": 0.20,
        "block_chance": 0.28,
        "admin_only": False, "emoji": "🔵",
        "skills": {"attack": "👏 Буги-вуги", "heavy": "💢 Чёрная вспышка", "heal": "💪 Укрепление", "block": "🔄 Обмен"}
    },
    "⚡ Зенин Тодзи": {
        "price": 6000, "anime": "🔴 Jujutsu Kaisen", "description": "*Убийца магов*",
        "hp": 280, "damage_min": 35, "damage_max": 55, "crit_chance": 0.30,
        "heal_min": 20, "heal_max": 30, "heavy_min": 53, "heavy_max": 83, "heavy_miss": 0.15,
        "block_chance": 0.20,
        "admin_only": False, "emoji": "⚡",
        "skills": {"attack": "🗡️ Рассекатель душ", "heavy": "💨 Мгновенный удар", "heal": "💪 Физическая мощь", "block": "⚡ Уклонение"}
    },
    
    # === BLEACH ===
    "⚔️ Ичиго Куросаки": {
        "price": 7000, "anime": "🟠 Bleach", "description": "*Банкай: Тенса Зангецу*",
        "hp": 270, "damage_min": 35, "damage_max": 55, "crit_chance": 0.30,
        "heal_min": 22, "heal_max": 35, "heavy_min": 58, "heavy_max": 95, "heavy_miss": 0.20,
        "block_chance": 0.25,
        "admin_only": False, "emoji": "⚔️",
        "skills": {"attack": "🌙 Гецуга Теншо", "heavy": "⚫ Банкай", "heal": "🩸 Регенерация пустого", "block": "🛡️ Блок мечом"}
    },
    "❄️ Хицугая Тоширо": {
        "price": 5500, "anime": "🟠 Bleach", "description": "*Хьёринмару*",
        "hp": 225, "damage_min": 28, "damage_max": 42, "crit_chance": 0.25,
        "heal_min": 18, "heal_max": 28, "heavy_min": 45, "heavy_max": 73, "heavy_miss": 0.22,
        "block_chance": 0.28,
        "admin_only": False, "emoji": "❄️",
        "skills": {"attack": "❄️ Ледяной удар", "heavy": "🐉 Дайгурен", "heal": "🧊 Ледяной покров", "block": "❄️ Ледяная стена"}
    },
    "🌸 Бьякуя Кучики": {
        "price": 6000, "anime": "🟠 Bleach", "description": "*Сенбонзакура*",
        "hp": 240, "damage_min": 30, "damage_max": 48, "crit_chance": 0.28,
        "heal_min": 15, "heal_max": 25, "heavy_min": 51, "heavy_max": 83, "heavy_miss": 0.15,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "🌸",
        "skills": {"attack": "🌸 Рассеивание", "heavy": "🌪️ Банкай", "heal": "🍃 Шаг сенки", "block": "🌸 Лепестки"}
    },
    "🔥 Ямамото": {
        "price": 15000, "anime": "🟠 Bleach", "description": "*Рюджин Джакка*",
        "hp": 450, "damage_min": 60, "damage_max": 90, "crit_chance": 0.35,
        "heal_min": 15, "heal_max": 25, "heavy_min": 83, "heavy_max": 153, "heavy_miss": 0.25,
        "block_chance": 0.20,
        "admin_only": False, "emoji": "🔥",
        "skills": {"attack": "🔥 Рюджин Джакка", "heavy": "☀️ Занка-но Тачи", "heal": "♨️ Пламя жизни", "block": "🔥 Огненная стена"}
    },
    "💀 Кенпачи Зараки": {
        "price": 9000, "anime": "🟠 Bleach", "description": "*Берсерк*",
        "hp": 400, "damage_min": 50, "damage_max": 75, "crit_chance": 0.25,
        "heal_min": 10, "heal_max": 15, "heavy_min": 68, "heavy_max": 113, "heavy_miss": 0.30,
        "block_chance": 0.15,
        "admin_only": False, "emoji": "💀",
        "skills": {"attack": "🗡️ Ночи", "heavy": "😈 Банкай", "heal": "💢 Жажда битвы", "block": "💀 Игнорирование боли"}
    },
    "🦇 Айзен Соске": {
        "price": 20000, "anime": "🟠 Bleach", "description": "*Кёка Суйгецу*",
        "hp": 500, "damage_min": 70, "damage_max": 100, "crit_chance": 0.40,
        "heal_min": 40, "heal_max": 60, "heavy_min": 93, "heavy_max": 163, "heavy_miss": 0.10,
        "block_chance": 0.35,
        "admin_only": False, "emoji": "🦇",
        "skills": {"attack": "🌀 Иллюзия", "heavy": "🌑 Хадо #90", "heal": "🔄 Регенерация Хогёку", "block": "🦇 Полное подчинение"}
    },
    
    # === ONE PIECE ===
    "👒 Луффи": {
        "price": 7500, "anime": "🔵 One Piece", "description": "*Гир 5*",
        "hp": 330, "damage_min": 35, "damage_max": 55, "crit_chance": 0.25,
        "heal_min": 30, "heal_max": 45, "heavy_min": 53, "heavy_max": 90, "heavy_miss": 0.25,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "👒",
        "skills": {"attack": "👊 Гому Гому", "heavy": "🥁 Гир 5", "heal": "🍖 Поедание мяса", "block": "🎈 Резиновый блок"}
    },
    "⚡ Зоро": {
        "price": 6500, "anime": "🔵 One Piece", "description": "*Три меча*",
        "hp": 285, "damage_min": 40, "damage_max": 60, "crit_chance": 0.30,
        "heal_min": 15, "heal_max": 25, "heavy_min": 58, "heavy_max": 98, "heavy_miss": 0.20,
        "block_chance": 0.25,
        "admin_only": False, "emoji": "⚡",
        "skills": {"attack": "🗡️ Три тысячи миров", "heavy": "👑 Стиль короля ада", "heal": "🍶 Глоток саке", "block": "⚔️ Блок мечами"}
    },
    "🔥 Эйс": {
        "price": 6000, "anime": "🔵 One Piece", "description": "*Огонь-огонь*",
        "hp": 255, "damage_min": 38, "damage_max": 58, "crit_chance": 0.28,
        "heal_min": 18, "heal_max": 28, "heavy_min": 53, "heavy_max": 88, "heavy_miss": 0.20,
        "block_chance": 0.22,
        "admin_only": False, "emoji": "🔥",
        "skills": {"attack": "🔥 Огненный кулак", "heavy": "💥 Огненный император", "heal": "🔥 Пламенное восстановление", "block": "🔥 Огненный барьер"}
    },
    "⚫ Чёрная Борода": {
        "price": 10000, "anime": "🔵 One Piece", "description": "*Ями Ями но Ми*",
        "hp": 420, "damage_min": 45, "damage_max": 70, "crit_chance": 0.20,
        "heal_min": 25, "heal_max": 40, "heavy_min": 63, "heavy_max": 113, "heavy_miss": 0.30,
        "block_chance": 0.20,
        "admin_only": False, "emoji": "⚫",
        "skills": {"attack": "🌑 Ями Ями", "heavy": "💀 Гура Гура", "heal": "🖤 Поглощение", "block": "🌑 Тьма"}
    },
    "🦩 Дофламинго": {
        "price": 8500, "anime": "🔵 One Piece", "description": "*Ито Ито но Ми*",
        "hp": 300, "damage_min": 40, "damage_max": 60, "crit_chance": 0.25,
        "heal_min": 20, "heal_max": 30, "heavy_min": 58, "heavy_max": 93, "heavy_miss": 0.20,
        "block_chance": 0.28,
        "admin_only": False, "emoji": "🦩",
        "skills": {"attack": "🕸️ Нити", "heavy": "🐦 Птичья клетка", "heal": "🧵 Восстановление", "block": "🕸️ Сеть"}
    },
    "🐉 Кайдо": {
        "price": 18000, "anime": "🔵 One Piece", "description": "*Сильнейший зверь*",
        "hp": 550, "damage_min": 65, "damage_max": 95, "crit_chance": 0.30,
        "heal_min": 35, "heal_max": 50, "heavy_min": 88, "heavy_max": 143, "heavy_miss": 0.20,
        "block_chance": 0.25,
        "admin_only": False, "emoji": "🐉",
        "skills": {"attack": "🔥 Боро Брес", "heavy": "🐲 Гибрид", "heal": "💪 Мифический зоан", "block": "🐉 Драконья чешуя"}
    },
    
    # === HUNTER X HUNTER ===
    "🎣 Гон": {
        "price": 5000, "anime": "🟢 Hunter x Hunter", "description": "*Джанкен*",
        "hp": 240, "damage_min": 30, "damage_max": 48, "crit_chance": 0.22,
        "heal_min": 22, "heal_max": 35, "heavy_min": 48, "heavy_max": 80, "heavy_miss": 0.25,
        "block_chance": 0.20,
        "admin_only": False, "emoji": "🎣",
        "skills": {"attack": "✊ Джанкен — Камень", "heavy": "✌️ Джанкен — Ножницы", "heal": "🖐️ Джанкен — Бумага", "block": "🛡️ Защита"}
    },
    "⚡ Киллуа": {
        "price": 5500, "anime": "🟢 Hunter x Hunter", "description": "*Боги скорости*",
        "hp": 220, "damage_min": 32, "damage_max": 50, "crit_chance": 0.35,
        "heal_min": 18, "heal_max": 28, "heavy_min": 51, "heavy_max": 83, "heavy_miss": 0.15,
        "block_chance": 0.35,
        "admin_only": False, "emoji": "⚡",
        "skills": {"attack": "⚡ Молния", "heavy": "⛈️ Боги скорости", "heal": "🍫 Шоколадный робот", "block": "⚡ Уклонение"}
    },
    "🕷️ Хисока": {
        "price": 7000, "anime": "🟢 Hunter x Hunter", "description": "*Банджи Гам*",
        "hp": 260, "damage_min": 35, "damage_max": 55, "crit_chance": 0.30,
        "heal_min": 20, "heal_max": 32, "heavy_min": 55, "heavy_max": 91, "heavy_miss": 0.15,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "🕷️",
        "skills": {"attack": "🃏 Карта-удар", "heavy": "🕸️ Банджи Гам", "heal": "🎭 Текстурный сюрприз", "block": "🕸️ Эластичный блок"}
    },
    "👑 Меруэм": {
        "price": 20000, "anime": "🟢 Hunter x Hunter", "description": "*Король муравьёв*",
        "hp": 525, "damage_min": 70, "damage_max": 100, "crit_chance": 0.40,
        "heal_min": 40, "heal_max": 60, "heavy_min": 93, "heavy_max": 163, "heavy_miss": 0.10,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "👑",
        "skills": {"attack": "💢 Удар хвостом", "heavy": "☄️ Гнев короля", "heal": "👑 Поглощение", "block": "👑 Королевская защита"}
    },
    "🔥 Нетеро": {
        "price": 15000, "anime": "🟢 Hunter x Hunter", "description": "*100-type Guanyin Bodhisattva*",
        "hp": 400, "damage_min": 55, "damage_max": 85, "crit_chance": 0.35,
        "heal_min": 25, "heal_max": 40, "heavy_min": 83, "heavy_max": 133, "heavy_miss": 0.15,
        "block_chance": 0.35,
        "admin_only": False, "emoji": "🔥",
        "skills": {"attack": "🙏 Ладонь", "heavy": "💥 Нулевая рука", "heal": "🧘 Медитация", "block": "🙏 Молитва"}
    },
    "⛓️ Куроро": {
        "price": 12000, "anime": "🟢 Hunter x Hunter", "description": "*Skill Hunter*",
        "hp": 350, "damage_min": 45, "damage_max": 70, "crit_chance": 0.30,
        "heal_min": 25, "heal_max": 35, "heavy_min": 63, "heavy_max": 103, "heavy_miss": 0.15,
        "block_chance": 0.30,
        "admin_only": False, "emoji": "⛓️",
        "skills": {"attack": "📖 Кража", "heavy": "🎭 Комбо", "heal": "🔄 Копирование", "block": "📖 Закрытая книга"}
    },
    
    # === АДМИН ===
    "👑 АДМИН": {
        "price": 0, "anime": "💀 Владыка", "description": "*Божественное правосудие*",
        "hp": 999, "damage_min": 999, "damage_max": 999, "crit_chance": 1.0,
        "heal_min": 999, "heal_max": 999, "heavy_min": 999, "heavy_max": 999, "heavy_miss": 0.0,
        "block_chance": 0.80,
        "admin_only": True, "emoji": "👑",
        "skills": {"attack": "💀 Казнь", "heavy": "☠️ Абсолютная смерть", "heal": "✨ Восстановление", "block": "🛡️ Божественный блок"}
    },
}

# === АНИМЕ ГРУППЫ ===
ANIME_GROUPS = {
    "🌀 Стартовый": [],
    "🔴 Jujutsu Kaisen": [],
    "🟠 Bleach": [],
    "🔵 One Piece": [],
    "🟢 Hunter x Hunter": [],
    "💀 Владыка": []
}

for name, data in CLASSES.items():
    anime = data.get("anime", "🌀 Стартовый")
    if anime in ANIME_GROUPS:
        ANIME_GROUPS[anime].append(name)

# === ОРУЖИЕ (ПОЛНЫЙ СПИСОК) ===
WEAPONS = {
    "🗡️ Катана": {"price": 800, "damage_bonus": 3, "anime": "🌀 Обычное"},
    "🏹 Лук": {"price": 600, "damage_bonus": 2, "anime": "🌀 Обычное", "crit_bonus": 0.05},
    "🔪 Кинжал": {"price": 400, "damage_bonus": 1, "anime": "🌀 Обычное", "crit_bonus": 0.10},
    "⚔️ Занпакто": {"price": 2500, "damage_bonus": 8, "anime": "🟠 Bleach"},
    "❄️ Хьёринмару": {"price": 3500, "damage_bonus": 10, "anime": "🟠 Bleach", "freeze_chance": 0.15},
    "🌸 Сенбонзакура": {"price": 4000, "damage_bonus": 12, "anime": "🟠 Bleach"},
    "🔥 Рюджин Джакка": {"price": 8000, "damage_bonus": 25, "anime": "🟠 Bleach", "burn_damage": 5},
    "🔫 Проклятый пистолет": {"price": 3000, "damage_bonus": 10, "anime": "🔴 Jujutsu Kaisen"},
    "💀 Меч Сукуны": {"price": 8000, "damage_bonus": 25, "anime": "🔴 Jujutsu Kaisen"},
    "🔴 Перевёрнутое копьё": {"price": 5000, "damage_bonus": 15, "anime": "🔴 Jujutsu Kaisen"},
    "🍖 Легендарный меч": {"price": 5000, "damage_bonus": 15, "anime": "🔵 One Piece"},
    "🗡️ Энма": {"price": 7000, "damage_bonus": 20, "anime": "🔵 One Piece", "hp_drain": 5},
    "👊 Кастет": {"price": 2000, "damage_bonus": 5, "anime": "🔵 One Piece"},
    "🎣 Удочка Гона": {"price": 4000, "damage_bonus": 12, "anime": "🟢 Hunter x Hunter"},
    "🃏 Карты Хисоки": {"price": 3500, "damage_bonus": 8, "anime": "🟢 Hunter x Hunter", "crit_bonus": 0.15},
    "⚡ Йо-йо Киллуа": {"price": 4500, "damage_bonus": 14, "anime": "🟢 Hunter x Hunter"},
    "🌟 Экскалибур": {"price": 15000, "damage_bonus": 35, "anime": "✨ Легендарное"},
    "🌑 Мурамаса": {"price": 12000, "damage_bonus": 30, "anime": "✨ Легендарное", "lifesteal": 0.2},
}

# === БРОНЯ (ПОЛНЫЙ СПИСОК) ===
ARMORS = {
    "👕 Кимоно": {"price": 800, "hp_bonus": 20, "anime": "🌀 Обычное"},
    "🧥 Кожаный доспех": {"price": 600, "hp_bonus": 15, "anime": "🌀 Обычное"},
    "🎽 Лёгкая броня": {"price": 500, "hp_bonus": 10, "anime": "🌀 Обычное", "dodge_chance": 0.05},
    "🛡️ Форма Шинигами": {"price": 2500, "hp_bonus": 50, "anime": "🟠 Bleach"},
    "⚫ Плащ капитана": {"price": 4000, "hp_bonus": 75, "anime": "🟠 Bleach"},
    "❄️ Ледяной доспех": {"price": 3500, "hp_bonus": 65, "anime": "🟠 Bleach"},
    "🎽 Магическая форма": {"price": 3000, "hp_bonus": 65, "anime": "🔴 Jujutsu Kaisen"},
    "💀 Броня Сукуны": {"price": 8000, "hp_bonus": 180, "anime": "🔴 Jujutsu Kaisen"},
    "👁️ Повязка Годжо": {"price": 5000, "hp_bonus": 40, "anime": "🔴 Jujutsu Kaisen"},
    "👑 Плащ Луффи": {"price": 5000, "hp_bonus": 100, "anime": "🔵 One Piece"},
    "🦾 Кибернетическая броня": {"price": 6000, "hp_bonus": 120, "anime": "🔵 One Piece"},
    "🌊 Плащ Дзимбэя": {"price": 4000, "hp_bonus": 85, "anime": "🔵 One Piece"},
    "🧥 Куртка Киллуа": {"price": 4000, "hp_bonus": 80, "anime": "🟢 Hunter x Hunter"},
    "🎽 Охотничий жилет": {"price": 3500, "hp_bonus": 70, "anime": "🟢 Hunter x Hunter"},
    "🕷️ Паучий шёлк": {"price": 5000, "hp_bonus": 90, "anime": "🟢 Hunter x Hunter"},
    "👑 Золотая броня": {"price": 15000, "hp_bonus": 250, "anime": "✨ Легендарное"},
    "🐉 Чешуя дракона": {"price": 12000, "hp_bonus": 220, "anime": "✨ Легендарное"},
}

def get_weapon_bonus(user_id: int) -> int:
    weapon = get_player(user_id)["weapon"]
    if weapon and weapon in WEAPONS:
        return WEAPONS[weapon]["damage_bonus"]
    return 0

def get_armor_bonus(user_id: int) -> int:
    armor = get_player(user_id)["armor"]
    if armor and armor in ARMORS:
        return ARMORS[armor]["hp_bonus"]
    return 0

# === КЛАСС ДУЭЛИ ===
class Duel:
    def __init__(self, player1: discord.Member, player2: discord.Member):
        self.p1 = player1
        self.p2 = player2
        self.p1_class = get_player(player1.id)["class"]
        self.p2_class = get_player(player2.id)["class"]
        
        base_hp1 = CLASSES[self.p1_class]["hp"]
        base_hp2 = CLASSES[self.p2_class]["hp"]
        armor1 = get_armor_bonus(player1.id)
        armor2 = get_armor_bonus(player2.id)
        
        self.p1_max_hp = base_hp1 + armor1
        self.p2_max_hp = base_hp2 + armor2
        self.p1_hp = self.p1_max_hp
        self.p2_hp = self.p2_max_hp
        
        self.turn = random.choice([player1, player2])
        self.active = False
        self.winner = None
        self.message = None
        self.bets: Dict[int, dict] = {}
        self.betting_phase = True
        self.bet_message = None
        self.ended = False
        self.last_was_heal = {player1.id: False, player2.id: False}
        self.last_was_block = {player1.id: False, player2.id: False}
        self.total_damage = {player1.id: 0, player2.id: 0}
        self.total_heal = {player1.id: 0, player2.id: 0}

    def place_bet(self, user: discord.Member, on_player: discord.Member, amount: int) -> tuple:
        if user.id in self.bets:
            return False, "❌ Ты уже сделал ставку!"
        if on_player.id not in [self.p1.id, self.p2.id]:
            return False, "❌ Можно ставить только на участников!"
        if user.id in [self.p1.id, self.p2.id]:
            return False, "❌ Участники не могут делать ставки!"
        if not remove_balance(user.id, amount):
            return False, f"❌ Недостаточно {CURRENCY_NAME}!"
        self.bets[user.id] = {'player': on_player, 'amount': amount}
        update_quest_progress(user.id, "bets", 1)
        return True, f"✅ {user.mention} поставил **{amount}** {CURRENCY_NAME} на **{on_player.display_name}**!"

    def payout_bets(self) -> tuple:
        if not self.winner:
            return "Дуэль не завершена.", 0
        
        total_pool = sum(bet['amount'] for bet in self.bets.values())
        winning_bets = [bet for bet in self.bets.values() if bet['player'].id == self.winner.id]
        
        if not winning_bets:
            winner_bonus = int(total_pool * 0.5)
            add_balance(self.winner.id, winner_bonus)
            results = [f"🎉 На победителя никто не ставил! **{self.winner.display_name}** забирает **50%** банка: **{winner_bonus}** {CURRENCY_NAME}!"]
            for user_id, bet in self.bets.items():
                results.append(f"<@{user_id}> проиграл **{bet['amount']}** {CURRENCY_NAME}.")
            return "\n".join(results), winner_bonus
        
        winning_pool = sum(bet['amount'] for bet in winning_bets)
        
        if len(winning_bets) == 1 and winning_pool < 25:
            multiplier = 1.25
        else:
            multiplier = total_pool / winning_pool if winning_pool > 0 else 1
            if multiplier < 1.25 and len(winning_bets) <= 2:
                multiplier = 1.25
        
        if total_pool >= 25:
            winner_bonus = int(total_pool * 0.25)
        else:
            winner_bonus = random.randint(10, 22)
        
        add_balance(self.winner.id, winner_bonus)
        
        results = [f"💰 **{self.winner.display_name}** получает бонус **{winner_bonus}** {CURRENCY_NAME} со ставок!"]
        for user_id, bet in self.bets.items():
            if bet['player'].id == self.winner.id:
                win_amount = int(bet['amount'] * multiplier)
                add_balance(user_id, win_amount)
                results.append(f"<@{user_id}> выиграл **{win_amount}** {CURRENCY_NAME}! (x{multiplier:.2f})")
            else:
                results.append(f"<@{user_id}> проиграл **{bet['amount']}** {CURRENCY_NAME}.")
        
        return "\n".join(results), winner_bonus

    def attack(self, attacker: discord.Member, defender_name: str, is_heavy: bool = False) -> str:
        class_name = self.p1_class if attacker.id == self.p1.id else self.p2_class
        stats = CLASSES[class_name]
        weapon_bonus = get_weapon_bonus(attacker.id)
        
        if is_heavy:
            if random.random() < stats["heavy_miss"]:
                self.last_was_heal[attacker.id] = False
                self.last_was_block[attacker.id] = False
                return f"😫 {attacker.mention} промахнулся супер-атакой!"
            damage = random.randint(stats["heavy_min"], stats["heavy_max"]) + weapon_bonus
            skill_name = stats["skills"]["heavy"]
            prefix = "🔥"
        else:
            damage = random.randint(stats["damage_min"], stats["damage_max"]) + weapon_bonus
            skill_name = stats["skills"]["attack"]
            prefix = ""
        
        is_crit = random.random() < stats["crit_chance"]
        if is_crit:
            damage *= 2
        
        defender = self.p1 if defender_name == "p1" else self.p2
        defender_class = self.p1_class if defender_name == "p1" else self.p2_class
        defender_stats = CLASSES[defender_class]
        
        is_blocked = False
        if not self.last_was_block[defender.id] and random.random() < defender_stats["block_chance"]:
            is_blocked = True
            damage = int(damage * 0.25)
            self.last_was_block[defender.id] = True
        else:
            self.last_was_block[defender.id] = False
        
        if defender_name == "p1":
            self.p1_hp = max(0, self.p1_hp - damage)
            current_hp = self.p1_hp
            max_hp = self.p1_max_hp
        else:
            self.p2_hp = max(0, self.p2_hp - damage)
            current_hp = self.p2_hp
            max_hp = self.p2_max_hp
        
        self.total_damage[attacker.id] += damage
        update_quest_progress(attacker.id, "damage", damage)
        self.last_was_heal[attacker.id] = False
        
        crit_text = "💥 **КРИТ!** " if is_crit else ""
        block_text = f"\n🛡️ **{defender.display_name}** блокирует атаку! Урон снижен на 75%!" if is_blocked else ""
        
        return f"{prefix}{crit_text}{attacker.mention} использует **{skill_name}** и наносит **{damage}** урона! У противника **{current_hp}/{max_hp}** HP.{block_text}"

    def heavy_attack(self, attacker: discord.Member, defender_name: str) -> str:
        return self.attack(attacker, defender_name, is_heavy=True)

    def heal(self, healer: discord.Member) -> str:
        class_name = self.p1_class if healer.id == self.p1.id else self.p2_class
        stats = CLASSES[class_name]
        
        if self.last_was_heal[healer.id]:
            return f"❌ {healer.mention} нельзя лечиться два раза подряд!"
        
        heal_amount = random.randint(stats["heal_min"], stats["heal_max"])
        skill_name = stats["skills"]["heal"]
        if healer == self.p1:
            self.p1_hp = min(self.p1_max_hp, self.p1_hp + heal_amount)
        else:
            self.p2_hp = min(self.p2_max_hp, self.p2_hp + heal_amount)
        
        self.total_heal[healer.id] += heal_amount
        update_quest_progress(healer.id, "heal", heal_amount)
        self.last_was_heal[healer.id] = True
        self.last_was_block[healer.id] = False
        return f"💚 {healer.mention} использует **{skill_name}** и лечит **{heal_amount}** HP."

    def check_winner(self) -> Optional[discord.Member]:
        if self.p1_hp <= 0:
            self.winner = self.p2
            self.active = False
            self.ended = True
            return self.p2
        elif self.p2_hp <= 0:
            self.winner = self.p1
            self.active = False
            self.ended = True
            return self.p1
        return None

    def get_betting_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎰 ФАЗА СТАВОК 🎰", 
            description=f"**{self.p1.mention} ({self.p1_class}) VS {self.p2.mention} ({self.p2_class})**\n\n30 секунд на ставки!", 
            color=discord.Color.blue()
        )
        p1_bets = sum(b['amount'] for b in self.bets.values() if b['player'].id == self.p1.id)
        p2_bets = sum(b['amount'] for b in self.bets.values() if b['player'].id == self.p2.id)
        embed.add_field(name=f"На {self.p1.display_name}", value=f"**{p1_bets}** {CURRENCY_NAME}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        embed.add_field(name=f"На {self.p2.display_name}", value=f"**{p2_bets}** {CURRENCY_NAME}", inline=True)
        embed.add_field(name="💰 Банк", value=f"**{p1_bets + p2_bets}** {CURRENCY_NAME}", inline=False)
        
        # 🔥 ПОКАЗЫВАЕМ СТАВКИ СРАЗУ (даже если пусто)
        if self.bets:
            bettors_text = ""
            for user_id, bet in self.bets.items():
                user = bot.get_user(user_id)
                name = user.display_name if user else str(user_id)
                bettors_text += f"• {name}: **{bet['amount']}** {CURRENCY_NAME} на **{bet['player'].display_name}**\n"
            embed.add_field(name="📋 Ставки игроков", value=bettors_text, inline=False)
        else:
            embed.add_field(name="📋 Ставки игроков", value="*Пока никто не поставил...*", inline=False)
        
        embed.set_footer(text="Нажми на кнопку 💰 чтобы сделать ставку!")
        return embed

    def get_status_embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚔️ ДУЭЛЬ ⚔️", color=discord.Color.red())
        p1_bar = "█" * (self.p1_hp * 10 // self.p1_max_hp) + "░" * (10 - (self.p1_hp * 10 // self.p1_max_hp)) if self.p1_max_hp > 0 else "██████████"
        p2_bar = "█" * (self.p2_hp * 10 // self.p2_max_hp) + "░" * (10 - (self.p2_hp * 10 // self.p2_max_hp)) if self.p2_max_hp > 0 else "██████████"
        p1_mmr = get_player(self.p1.id)["mmr"]
        p2_mmr = get_player(self.p2.id)["mmr"]
        embed.add_field(name=f"{'👑' if self.turn == self.p1 else '⚔️'} {self.p1.display_name} ({self.p1_class})", value=f"❤️ **{self.p1_hp}/{self.p1_max_hp}** HP\n`{p1_bar}`\n📊 MMR: **{p1_mmr}**", inline=True)
        embed.add_field(name="VS", value="⚡⚡⚡", inline=True)
        embed.add_field(name=f"{'👑' if self.turn == self.p2 else '⚔️'} {self.p2.display_name} ({self.p2_class})", value=f"❤️ **{self.p2_hp}/{self.p2_max_hp}** HP\n`{p2_bar}`\n📊 MMR: **{p2_mmr}**", inline=True)
        if self.bets:
            p1_bets = sum(b['amount'] for b in self.bets.values() if b['player'].id == self.p1.id)
            p2_bets = sum(b['amount'] for b in self.bets.values() if b['player'].id == self.p2.id)
            embed.add_field(name="🎰 СТАВКИ", value=f"На **{self.p1.display_name}**: {p1_bets}\nНа **{self.p2.display_name}**: {p2_bets}\n💰 Банк: **{p1_bets + p2_bets}**", inline=False)
        embed.add_field(name="Ходит:", value=f"👉 {self.turn.mention}", inline=False)
        return embed

# === КНОПКИ ===
class BetModal(discord.ui.Modal, title="Сделать ставку"):
    def __init__(self, duel: Duel):
        super().__init__()
        self.duel = duel
    player_choice = discord.ui.TextInput(label="На кого ставишь? (1 или 2)", placeholder="1 или 2", max_length=1, required=True)
    amount = discord.ui.TextInput(label=f"Сумма в {CURRENCY_NAME}", placeholder="100", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if self.duel.ended:
            await interaction.response.send_message("❌ Дуэль завершена!", ephemeral=True)
            return
        try:
            choice = int(self.player_choice.value)
            if choice not in [1, 2]:
                await interaction.response.send_message("❌ Введи 1 или 2!", ephemeral=True)
                return
            bet_on = self.duel.p1 if choice == 1 else self.duel.p2
            amount = int(self.amount.value)
            if amount <= 0:
                await interaction.response.send_message("❌ Сумма > 0!", ephemeral=True)
                return
            success, message = self.duel.place_bet(interaction.user, bet_on, amount)
            if success:
                try:
                    embed = self.duel.get_betting_embed()
                    await self.duel.bet_message.edit(embed=embed)
                except:
                    pass
            await interaction.response.send_message(message, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Ошибка ввода!", ephemeral=True)

class BettingView(discord.ui.View):
    def __init__(self, duel: Duel):
        super().__init__(timeout=30)
        self.duel = duel
        self.started = False

    @discord.ui.button(label="💰 Сделать ставку", style=discord.ButtonStyle.primary, emoji="🎲")
    async def bet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.duel.ended:
            await interaction.response.send_message("❌ Дуэль завершена!", ephemeral=True)
            return
        modal = BetModal(self.duel)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        if self.duel.betting_phase and not self.duel.ended and not self.started:
            self.started = True
            self.duel.betting_phase = False
            await self.start_duel()

    async def start_duel(self):
        self.duel.active = True
        duel_view = DuelView(self.duel)
        embed = self.duel.get_status_embed()
        embed.description = f"**Дуэль начинается!** Первый ход: **{self.duel.turn.display_name}**"
        for child in self.children:
            child.disabled = True
        if self.duel.bet_message:
            try:
                await self.duel.bet_message.edit(embed=embed, view=duel_view)
                self.duel.message = self.duel.bet_message
            except:
                pass

class DuelView(discord.ui.View):
    def __init__(self, duel: Duel):
        super().__init__(timeout=590)
        self.duel = duel
        self.ended = False
        self.start_timer()

    def start_timer(self):
        async def timer():
            await asyncio.sleep(590)
            if not self.ended and not self.duel.ended and self.duel.active:
                loser = self.duel.turn
                winner = self.duel.p2 if loser.id == self.duel.p1.id else self.duel.p1
                self.duel.winner = winner
                self.ended = True
                self.duel.ended = True
                
                players_in_duel.discard(self.duel.p1.id)
                players_in_duel.discard(self.duel.p2.id)
                
                w = get_player(winner.id)
                l = get_player(loser.id)
                update_player(winner.id, "wins", w["wins"] + 1)
                update_player(loser.id, "losses", l["losses"] + 1)
                
                w_change, l_change = update_mmr(winner.id, loser.id)
                update_quest_progress(winner.id, "wins", 1)
                
                payout_text, winner_bonus = self.duel.payout_bets()
                total = WIN_REWARD + winner_bonus
                add_balance(winner.id, total)
                
                embed = discord.Embed(
                    title="⏰ ВРЕМЯ ВЫШЛО! ⏰",
                    description=f"{loser.mention} думал слишком долго...\n**{winner.mention} побеждает!**\n+{WIN_REWARD} база + {winner_bonus} ставки = **{total}** {CURRENCY_NAME}!",
                    color=discord.Color.orange()
                )
                embed.add_field(name="📊 MMR", value=f"{winner.display_name}: **{w['mmr'] + w_change}** (+{w_change})\n{loser.display_name}: **{l['mmr'] + l_change}** ({l_change})")
                embed.add_field(name="🎰 Ставки", value=payout_text, inline=False)
                
                for child in self.children:
                    child.disabled = True
                
                try:
                    await self.duel.message.edit(embed=embed, view=self)
                except:
                    pass
        asyncio.create_task(timer())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.duel.ended:
            await interaction.response.send_message("❌ Дуэль завершена!", ephemeral=True)
            return False
        if interaction.user.id != self.duel.turn.id:
            await interaction.response.send_message("❌ Не твой ход!", ephemeral=True)
            return False
        return True

    async def update_duel_message(self, interaction: discord.Interaction, action_result: str):
        winner = self.duel.check_winner()
        if winner:
            self.ended = True
            self.duel.ended = True
            loser = self.duel.p2 if winner.id == self.duel.p1.id else self.duel.p1
            
            players_in_duel.discard(self.duel.p1.id)
            players_in_duel.discard(self.duel.p2.id)
            
            w = get_player(winner.id)
            l = get_player(loser.id)
            update_player(winner.id, "wins", w["wins"] + 1)
            update_player(loser.id, "losses", l["losses"] + 1)
            
            w_change, l_change = update_mmr(winner.id, loser.id)
            update_quest_progress(winner.id, "wins", 1)
            
            payout_text, winner_bonus = self.duel.payout_bets()
            total_reward = WIN_REWARD + winner_bonus
            add_balance(winner.id, total_reward)
            
            embed = discord.Embed(
                title="🏆 ДУЭЛЬ ОКОНЧЕНА! 🏆",
                description=f"**{winner.mention} побеждает!**\n+{WIN_REWARD} база + {winner_bonus} ставки = **{total_reward}** {CURRENCY_NAME}!",
                color=discord.Color.gold()
            )
            embed.add_field(name="📊 MMR", value=f"{winner.display_name}: **{w['mmr'] + w_change}** (+{w_change})\n{loser.display_name}: **{l['mmr'] + l_change}** ({l_change})")
            embed.add_field(name="🎰 Ставки", value=payout_text, inline=False)
            
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            self.duel.turn = self.duel.p2 if self.duel.turn == self.duel.p1 else self.duel.p1
            embed = self.duel.get_status_embed()
            embed.description = f"**{action_result}**"
            await interaction.response.edit_message(embed=embed, view=self)
            self.start_timer()

    @discord.ui.button(label="⚔️ Атака", style=discord.ButtonStyle.danger)
    async def attack_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        defender = "p2" if interaction.user.id == self.duel.p1.id else "p1"
        await self.update_duel_message(interaction, self.duel.attack(interaction.user, defender))

    @discord.ui.button(label="💪 Супер", style=discord.ButtonStyle.primary)
    async def heavy_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        defender = "p2" if interaction.user.id == self.duel.p1.id else "p1"
        await self.update_duel_message(interaction, self.duel.heavy_attack(interaction.user, defender))

    @discord.ui.button(label="💊 Лечение", style=discord.ButtonStyle.success)
    async def heal_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await self.update_duel_message(interaction, self.duel.heal(interaction.user))

    @discord.ui.button(label="🛡️ Блок", style=discord.ButtonStyle.secondary)
    async def block_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.duel.last_was_heal[interaction.user.id] = False
        self.duel.last_was_block[interaction.user.id] = False
        
        class_name = self.duel.p1_class if interaction.user.id == self.duel.p1.id else self.duel.p2_class
        stats = CLASSES[class_name]
        skill_name = stats["skills"]["block"]
        
        await self.update_duel_message(interaction, f"🛡️ {interaction.user.mention} использует **{skill_name}** и готовится блокировать!")

    @discord.ui.button(label="🏳️ Сдаться", style=discord.ButtonStyle.danger)
    async def surrender_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id not in [self.duel.p1.id, self.duel.p2.id]:
            await interaction.response.send_message("❌ Ты не в дуэли!", ephemeral=True)
            return
        self.ended = True
        self.duel.ended = True
        loser = interaction.user
        winner = self.duel.p2 if loser.id == self.duel.p1.id else self.duel.p1
        self.duel.winner = winner
        
        players_in_duel.discard(self.duel.p1.id)
        players_in_duel.discard(self.duel.p2.id)
        
        w = get_player(winner.id)
        l = get_player(loser.id)
        update_player(winner.id, "wins", w["wins"] + 1)
        update_player(loser.id, "losses", l["losses"] + 1)
        
        w_change, l_change = update_mmr(winner.id, loser.id)
        update_quest_progress(winner.id, "wins", 1)
        
        payout_text, winner_bonus = self.duel.payout_bets()
        total = WIN_REWARD + winner_bonus
        add_balance(winner.id, total)
        
        embed = discord.Embed(title="🏳️ СДАЧА 🏳️", description=f"**{loser.mention} сдаётся!**\n**{winner.mention} побеждает!**\n+{WIN_REWARD} база + {winner_bonus} ставки = **{total}** {CURRENCY_NAME}!", color=discord.Color.light_grey())
        embed.add_field(name="📊 MMR", value=f"{winner.display_name}: **{w['mmr'] + w_change}** (+{w_change})\n{loser.display_name}: **{l['mmr'] + l_change}** ({l_change})")
        embed.add_field(name="🎰 Ставки", value=payout_text, inline=False)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

class DuelAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, target: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.target = target
        self.accepted = None
        self.message = None

    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("❌ Не тебя вызывали!", ephemeral=True)
            return
        self.accepted = True
        if self.message:
            await self.message.delete()
        self.stop()

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("❌ Не тебя вызывали!", ephemeral=True)
            return
        self.accepted = False
        if self.message:
            await self.message.delete()
        self.stop()

# === МАГАЗИН ===
class ShopMainView(ui.View):
    def __init__(self, user_id: int, user_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.user_name = user_name

    @ui.select(placeholder="🎭 Выбери категорию", options=[
        discord.SelectOption(label="🔴 Jujutsu Kaisen", description="Персонажи из JJK", emoji="👁️"),
        discord.SelectOption(label="🟠 Bleach", description="Персонажи из Bleach", emoji="⚔️"),
        discord.SelectOption(label="🔵 One Piece", description="Персонажи из One Piece", emoji="👒"),
        discord.SelectOption(label="🟢 Hunter x Hunter", description="Персонажи из HxH", emoji="🎣"),
        discord.SelectOption(label="⚔️ Оружие", description="Покупка оружия", emoji="🗡️"),
        discord.SelectOption(label="🛡️ Броня", description="Покупка брони", emoji="👕"),
    ])
    async def category_select(self, interaction: discord.Interaction, select: ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        category = select.values[0]
        
        if category == "⚔️ Оружие":
            view = WeaponShopView(self.user_id, self.user_name)
            embed = discord.Embed(title=f"⚔️ МАГАЗИН {self.user_name} — ОРУЖИЕ", description="Выбери оружие:", color=discord.Color.blue())
        elif category == "🛡️ Броня":
            view = ArmorShopView(self.user_id, self.user_name)
            embed = discord.Embed(title=f"🛡️ МАГАЗИН {self.user_name} — БРОНЯ", description="Выбери броню:", color=discord.Color.purple())
        else:
            view = AnimeShopView(self.user_id, self.user_name, category)
            embed = discord.Embed(title=f"🏮 МАГАЗИН {self.user_name} — {category}", description="Выбери персонажа:", color=discord.Color.gold())
        
        embed.set_footer(text=f"Твой баланс: {get_balance(self.user_id)} ДАЙР")
        await interaction.response.edit_message(embed=embed, view=view)

class AnimeShopView(ui.View):
    def __init__(self, user_id: int, user_name: str, anime: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.user_name = user_name
        self.anime = anime
        
        characters = ANIME_GROUPS.get(anime, [])
        options = []
        for name in characters:
            data = CLASSES[name]
            owned = name in get_unlocked_classes(user_id)
            if not owned:
                options.append(discord.SelectOption(label=name, description=f"{data['price']} ДАЙР | HP: {data['hp']}", emoji=data['emoji']))
        
        if options:
            select = ui.Select(placeholder="Выбери персонажа", options=options[:25])
            select.callback = self.buy_character
            self.add_item(select)
    
    async def buy_character(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        char_name = interaction.data["values"][0]
        data = CLASSES[char_name]
        
        if char_name in get_unlocked_classes(self.user_id):
            await interaction.response.send_message(f"❌ Уже разблокирован!", ephemeral=True)
            return
        
        if remove_balance(self.user_id, data['price']):
            unlock_class(self.user_id, char_name)
            await interaction.response.send_message(f"✅ Куплен **{char_name}**!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Недостаточно ДАЙР!", ephemeral=True)
    
    @ui.button(label="◀️ Назад", style=discord.ButtonStyle.grey)
    async def back_btn(self, interaction: discord.Interaction, btn: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        view = ShopMainView(self.user_id, self.user_name)
        embed = discord.Embed(title=f"🏮 МАГАЗИН {self.user_name}", description="Выбери категорию:", color=discord.Color.purple())
        embed.set_footer(text=f"Баланс: {get_balance(self.user_id)} ДАЙР")
        await interaction.response.edit_message(embed=embed, view=view)

class WeaponShopView(ui.View):
    def __init__(self, user_id: int, user_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.user_name = user_name
        
        options = []
        for name, data in WEAPONS.items():
            owned = name in get_unlocked_weapons(user_id)
            if not owned:
                options.append(discord.SelectOption(label=name, description=f"{data['price']} ДАЙР | +{data['damage_bonus']} урона"))
        
        if options:
            select = ui.Select(placeholder="Выбери оружие", options=options[:25])
            select.callback = self.buy_weapon
            self.add_item(select)
    
    async def buy_weapon(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        weapon_name = interaction.data["values"][0]
        data = WEAPONS[weapon_name]
        
        if remove_balance(self.user_id, data['price']):
            unlock_weapon(self.user_id, weapon_name)
            update_player(self.user_id, "weapon", weapon_name)
            await interaction.response.send_message(f"✅ Куплено **{weapon_name}**!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Недостаточно ДАЙР!", ephemeral=True)
    
    @ui.button(label="◀️ Назад", style=discord.ButtonStyle.grey)
    async def back_btn(self, interaction: discord.Interaction, btn: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        view = ShopMainView(self.user_id, self.user_name)
        embed = discord.Embed(title=f"🏮 МАГАЗИН {self.user_name}", description="Выбери категорию:", color=discord.Color.purple())
        embed.set_footer(text=f"Баланс: {get_balance(self.user_id)} ДАЙР")
        await interaction.response.edit_message(embed=embed, view=view)

class ArmorShopView(ui.View):
    def __init__(self, user_id: int, user_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.user_name = user_name
        
        options = []
        for name, data in ARMORS.items():
            owned = name in get_unlocked_armors(user_id)
            if not owned:
                options.append(discord.SelectOption(label=name, description=f"{data['price']} ДАЙР | +{data['hp_bonus']} HP"))
        
        if options:
            select = ui.Select(placeholder="Выбери броню", options=options[:25])
            select.callback = self.buy_armor
            self.add_item(select)
    
    async def buy_armor(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        armor_name = interaction.data["values"][0]
        data = ARMORS[armor_name]
        
        if remove_balance(self.user_id, data['price']):
            unlock_armor(self.user_id, armor_name)
            update_player(self.user_id, "armor", armor_name)
            await interaction.response.send_message(f"✅ Куплено **{armor_name}**!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Недостаточно ДАЙР!", ephemeral=True)
    
    @ui.button(label="◀️ Назад", style=discord.ButtonStyle.grey)
    async def back_btn(self, interaction: discord.Interaction, btn: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твой магазин!", ephemeral=True)
            return
        
        view = ShopMainView(self.user_id, self.user_name)
        embed = discord.Embed(title=f"🏮 МАГАЗИН {self.user_name}", description="Выбери категорию:", color=discord.Color.purple())
        embed.set_footer(text=f"Баланс: {get_balance(self.user_id)} ДАЙР")
        await interaction.response.edit_message(embed=embed, view=view)

class ClassSelectView(ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        
        unlocked = get_unlocked_classes(user_id)
        is_admin = (user_id == ADMIN_ID)
        
        options = []
        for name, data in CLASSES.items():
            if data.get("admin_only") and not is_admin:
                continue
            if name in unlocked or (is_admin and name == "👑 АДМИН"):
                options.append(discord.SelectOption(label=name, description=f"HP: {data['hp']} | Урон: {data['damage_min']}-{data['damage_max']}", emoji=data['emoji']))
        
        if options:
            select = ui.Select(placeholder="Выбери класс для боя", options=options[:25])
            select.callback = self.select_class
            self.add_item(select)
    
    async def select_class(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Не твоё меню!", ephemeral=True)
            return
        
        class_name = interaction.data["values"][0]
        update_player(self.user_id, "class", class_name)
        await interaction.response.send_message(f"✅ Выбран **{class_name}**!", ephemeral=True)

class QuestsView(ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        quests = get_daily_quests(user_id)
        
        for i in range(3):
            if quests["completed"][i] and not quests["claimed"][i]:
                btn = ui.Button(label=f"🎁 Забрать награду #{i+1}", style=discord.ButtonStyle.success, row=i)
                btn.callback = self.make_callback(i)
                self.add_item(btn)
    
    def make_callback(self, quest_index: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Не твои задания!", ephemeral=True)
                return
            
            reward = claim_quest_reward(self.user_id, quest_index)
            if reward > 0:
                await interaction.response.send_message(f"✅ Получено **{reward}** {CURRENCY_NAME}!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Нельзя забрать награду!", ephemeral=True)
        return cb

class LeaderboardView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    
    @ui.select(placeholder="🏆 Выбери рейтинг", options=[
        discord.SelectOption(label="🏆 По победам", description="Топ-10 по количеству побед", emoji="🏆"),
        discord.SelectOption(label="💰 По балансу", description="Топ-10 по количеству ДАЙР", emoji="💰"),
        discord.SelectOption(label="📊 По MMR", description="Топ-10 по рейтингу MMR", emoji="📊"),
    ])
    async def leaderboard_select(self, interaction: discord.Interaction, select: ui.Select):
        choice = select.values[0]
        
        if choice == "🏆 По победам":
            cur.execute("SELECT user_id, wins, losses FROM players ORDER BY wins DESC LIMIT 10")
            title = "🏆 ТАБЛИЦА ЛИДЕРОВ — ПОБЕДЫ"
        elif choice == "💰 По балансу":
            cur.execute("SELECT user_id, balance FROM players ORDER BY balance DESC LIMIT 10")
            title = "💰 ТАБЛИЦА ЛИДЕРОВ — БАЛАНС"
        else:
            cur.execute("SELECT user_id, mmr, wins FROM players ORDER BY mmr DESC LIMIT 10")
            title = "📊 ТАБЛИЦА ЛИДЕРОВ — MMR"
        
        rows = cur.fetchall()
        embed = discord.Embed(title=title, color=discord.Color.gold())
        
        if not rows:
            embed.description = "Пока никто не участвовал!"
        else:
            for i, row in enumerate(rows, 1):
                user = bot.get_user(row[0])
                name = user.display_name if user else str(row[0])
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                
                if choice == "🏆 По победам":
                    embed.add_field(name=f"{medal} {name}", value=f"🏆 Побед: **{row[1]}** | 💀 Поражений: **{row[2]}**", inline=False)
                elif choice == "💰 По балансу":
                    embed.add_field(name=f"{medal} {name}", value=f"💰 **{row[1]}** {CURRENCY_NAME}", inline=False)
                else:
                    embed.add_field(name=f"{medal} {name}", value=f"📊 MMR: **{row[1]}** | 🏆 Побед: **{row[2]}**", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

# === КОМАНДЫ ===
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    await bot.change_presence(activity=discord.Game(name="!дуэльхелп | !дуэль"))

@bot.command(name="дуэльхелп")
async def help_cmd(ctx):
    embed = discord.Embed(title="📋 КОМАНДЫ БОТА", color=discord.Color.blue())
    embed.add_field(name="⚔️ !дуэль @игрок", value="Вызвать на дуэль", inline=False)
    embed.add_field(name="💰 !дуэльбаланс", value="Проверить баланс", inline=False)
    embed.add_field(name="📊 !дуэльстата", value="Статистика и MMR", inline=False)
    embed.add_field(name="🏆 !дуэльлидеры", value="Таблица лидеров", inline=False)
    embed.add_field(name="📋 !дуэльзадания", value="Ежедневные задания", inline=False)
    embed.add_field(name="🛒 !дуэльмагазин", value="Открыть магазин", inline=False)
    embed.add_field(name="🎭 !дуэльвыбрать", value="Выбрать класс", inline=False)
    embed.add_field(name="💵 !дуэльдатьочки @игрок 100", value="(Админ) Выдать очки", inline=False)
    embed.add_field(name="💸 !дуэльснятьочки @игрок 100", value="(Админ) Снять очки", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="дуэль")
async def duel(ctx, opponent: discord.Member = None):
    if ctx.author.id in players_in_duel:
        await ctx.send("❌ Ты уже в дуэли!")
        return
    if opponent is None:
        await ctx.send("❌ !дуэль @игрок")
        return
    if opponent.id in players_in_duel:
        await ctx.send(f"❌ {opponent.display_name} уже в дуэли!")
        return
    
    view = DuelAcceptView(ctx.author, opponent)
    p1_mmr = get_player(ctx.author.id)["mmr"]
    p2_mmr = get_player(opponent.id)["mmr"]
    msg = await ctx.send(f"⚔️ {ctx.author.mention} ({get_player(ctx.author.id)['class']}) [MMR: {p1_mmr}] вызывает {opponent.mention} ({get_player(opponent.id)['class']}) [MMR: {p2_mmr}]!", view=view)
    view.message = msg
    
    await view.wait()
    
    if view.accepted:
        players_in_duel.add(ctx.author.id)
        players_in_duel.add(opponent.id)
        duel_obj = Duel(ctx.author, opponent)
        betting_view = BettingView(duel_obj)
        bet_msg = await ctx.send(embed=duel_obj.get_betting_embed(), view=betting_view)
        duel_obj.bet_message = bet_msg

@bot.command(name="дуэльбаланс")
async def balance_cmd(ctx, member: discord.Member = None):
    m = member or ctx.author
    await ctx.send(f"💰 {m.display_name}: **{get_balance(m.id)}** {CURRENCY_NAME}")

@bot.command(name="дуэльстата")
async def stats_cmd(ctx, member: discord.Member = None):
    m = member or ctx.author
    p = get_player(m.id)
    
    embed = discord.Embed(title=f"📊 Статистика {m.display_name}", color=discord.Color.blue())
    embed.add_field(name="🏆 Побед", value=str(p.get('wins', 0)), inline=True)
    embed.add_field(name="💀 Поражений", value=str(p.get('losses', 0)), inline=True)
    
    total = p.get('wins', 0) + p.get('losses', 0)
    winrate = round(p.get('wins', 0) / total * 100, 1) if total > 0 else 0
    embed.add_field(name="📈 Винрейт", value=f"{winrate}%", inline=True)
    
    embed.add_field(name="📊 MMR", value=str(p.get('mmr', 1000)), inline=True)
    embed.add_field(name="💰 Баланс", value=f"{p.get('balance', 0)} {CURRENCY_NAME}", inline=True)
    embed.add_field(name="🎭 Класс", value=str(p.get('class', '🗡️ Воин')), inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="дуэльлидеры")
async def leaderboard_cmd(ctx):
    view = LeaderboardView()
    embed = discord.Embed(title="🏆 ТАБЛИЦА ЛИДЕРОВ", description="Выбери категорию рейтинга:", color=discord.Color.gold())
    await ctx.send(embed=embed, view=view)

@bot.command(name="дуэльзадания")
async def quests_cmd(ctx):
    quests = get_daily_quests(ctx.author.id)
    
    embed = discord.Embed(title=f"📋 ЗАДАНИЯ — {ctx.author.display_name}", color=discord.Color.green())
    
    text = ""
    for i, quest in enumerate(quests["quests"]):
        prog = quests["progress"][i]
        target = quest["target"]
        completed = quests["completed"][i]
        claimed = quests["claimed"][i]
        
        if claimed:
            status = "✅ Забрано"
        elif completed:
            status = "🎁 Можно забрать!"
        else:
            status = f"❌ ({prog}/{target})"
        
        reward = f"{quest['reward'][0]}-{quest['reward'][1]}"
        text += f"{status} **{quest['name']}**: {quest['desc']} — {reward} {CURRENCY_NAME}\n"
    
    embed.add_field(name="📅 ЕЖЕДНЕВНЫЕ ЗАДАНИЯ", value=text or "Нет заданий", inline=False)
    
    view = QuestsView(ctx.author.id)
    await ctx.send(embed=embed, view=view)

@bot.command(name="дуэльмагазин")
async def shop_cmd(ctx):
    if ctx.author.id in players_in_duel:
        await ctx.send("❌ Нельзя использовать магазин во время дуэли!")
        return
    
    view = ShopMainView(ctx.author.id, ctx.author.display_name)
    embed = discord.Embed(title=f"🏮 МАГАЗИН {ctx.author.display_name}", description="Выбери категорию:", color=discord.Color.purple())
    embed.set_footer(text=f"Баланс: {get_balance(ctx.author.id)} ДАЙР")
    await ctx.send(embed=embed, view=view)

@bot.command(name="дуэльвыбрать")
async def select_cmd(ctx):
    if ctx.author.id in players_in_duel:
        await ctx.send("❌ Нельзя менять класс во время дуэли!")
        return
    
    view = ClassSelectView(ctx.author.id)
    embed = discord.Embed(title="🎭 ВЫБОР ПЕРСОНАЖА", description="Выбери класс для дуэлей:", color=discord.Color.purple())
    await ctx.send(embed=embed, view=view)

@bot.command(name="дуэльдатьочки")
@commands.has_permissions(administrator=True)
async def give_points_cmd(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Сумма > 0!")
        return
    add_balance(member.id, amount)
    await ctx.send(f"✅ +{amount} {CURRENCY_NAME} → {member.display_name}")

@bot.command(name="дуэльснятьочки")
@commands.has_permissions(administrator=True)
async def remove_points_cmd(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Сумма > 0!")
        return
    if remove_balance(member.id, amount):
        await ctx.send(f"✅ -{amount} {CURRENCY_NAME} у {member.display_name}")
    else:
        await ctx.send(f"❌ У {member.display_name} недостаточно {CURRENCY_NAME}!")

# === ЗАПУСК ===
bot.run(os.getenv('DISCORD_TOKEN'))
