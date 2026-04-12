import discord
from discord.ext import commands
import random
import asyncio
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import os
from flask import Flask
import threading

# === ВЕБ-СЕРВЕР ДЛЯ RENDER ===
app = Flask(__name__)

@app.route('/')
def home():
    return "⚔️ Бот дуэлей работает 24/7!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))

threading.Thread(target=run_web).start()


# === НАСТРОЙКИ DISCORD ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


# === ID АДМИНА ===
ADMIN_ID = 1492635601294590115  # ЗАМЕНИ НА СВОЙ ID


# === ДАННЫЕ ИГРОКОВ ===
player_balances: Dict[int, int] = {}
player_classes: Dict[int, str] = {}
unlocked_classes: Dict[int, List[str]] = {}
player_stats: Dict[int, dict] = {}
daily_bonus: Dict[int, datetime] = {}
battle_history: Dict[int, List[dict]] = {}
player_quests: Dict[int, dict] = {}
player_win_streak: Dict[int, int] = {}

START_BALANCE = 100
DEFAULT_CLASS = "🗡️ Воин"
WIN_REWARD = 15
CURRENCY_NAME = "ДАЙР"
BASE_MMR = 1000


# === ДУЭЛИ ===
players_in_duel: set = set()
pending_duels: Dict[int, int] = {}

active_duels: Dict[int, dict] = {}
# === ДОСТИЖЕНИЯ ===
ACHIEVEMENTS = {
    "wins_10": {"name": "🔰 Новичок", "description": "Одержать 10 побед", "requirement": 10, "type": "wins"},
    "wins_25": {"name": "⚔️ Воин", "description": "Одержать 25 побед", "requirement": 25, "type": "wins"},
    "wins_50": {"name": "🛡️ Ветеран", "description": "Одержать 50 побед", "requirement": 50, "type": "wins"},
    "wins_100": {"name": "👑 Легенда", "description": "Одержать 100 побед", "requirement": 100, "type": "wins"},
    "balance_5000": {"name": "💰 Богач", "description": "Накопить 5000 ДАЙР", "requirement": 5000, "type": "balance"},
    "balance_10000": {"name": "💎 Миллионер", "description": "Накопить 10000 ДАЙР", "requirement": 10000, "type": "balance"},
    "mmr_1200": {"name": "📈 Продвинутый", "description": "Достичь 1200 MMR", "requirement": 1200, "type": "mmr"},
    "mmr_1500": {"name": "🎯 Мастер", "description": "Достичь 1500 MMR", "requirement": 1500, "type": "mmr"},
    "mmr_2000": {"name": "🏆 Грандмастер", "description": "Достичь 2000 MMR", "requirement": 2000, "type": "mmr"},
}

TITLES = {
    None: "🚫 Нет титула",
    "🔰 Новичок": "🔰 Новичок",
    "⚔️ Воин": "⚔️ Воин",
    "🛡️ Ветеран": "🛡️ Ветеран",
    "👑 Легенда": "👑 Легенда",
}

# === КЛАССЫ ===
CLASSES = {
    "🗡️ Воин": {
        "price": 0,
        "anime": "🌀 Стартовый",
        "description": "Обычный боец",
        "hp": 180,
        "damage_min": 10,
        "damage_max": 18,
        "crit_chance": 0.15,
        "heal_min": 10,
        "heal_max": 20,
        "heavy_min": 16,
        "heavy_max": 30,
        "heavy_miss": 0.20,
        "admin_only": False,
        "emoji": "🗡️",
        "skills": {
            "attack": "💥 Удар мечом",
            "heavy": "⚔️ Тяжёлый удар",
            "heal": "💊 Лечение"
        }
    }
}

# === ОРУЖИЕ ===
WEAPONS = {
    "🗡️ Катана": {"price": 800, "damage_bonus": 3},
    "⚔️ Занпакто": {"price": 2500, "damage_bonus": 8},
}

# === БРОНЯ ===
ARMORS = {
    "👕 Кимоно": {"price": 800, "hp_bonus": 20},
    "🛡️ Форма Шинигами": {"price": 2500, "hp_bonus": 50},
}

player_weapons: Dict[int, str] = {}
player_armors: Dict[int, str] = {}
unlocked_weapons: Dict[int, List[str]] = {}
unlocked_armors: Dict[int, List[str]] = {}

# === СТАТИСТИКА ===
def get_stats(user_id: int) -> dict:
    if user_id not in player_stats:
        player_stats[user_id] = {
            'wins': 0,
            'losses': 0,
            'mmr': BASE_MMR,
            'title': None,
            'achievements': []
        }
    return player_stats[user_id]


# === БАЛАНС ===
def get_balance(user_id: int) -> int:
    if user_id not in player_balances:
        player_balances[user_id] = START_BALANCE
    return player_balances[user_id]


def add_balance(user_id: int, amount: int):
    player_balances[user_id] = get_balance(user_id) + amount


def remove_balance(user_id: int, amount: int) -> bool:
    current = get_balance(user_id)
    if current < amount:
        return False
    player_balances[user_id] = current - amount
    return True


# === КЛАССЫ ===
def get_player_class(user_id: int) -> str:
    if user_id not in player_classes:
        player_classes[user_id] = DEFAULT_CLASS
    return player_classes[user_id]


def get_unlocked_classes(user_id: int) -> List[str]:
    if user_id not in unlocked_classes:
        unlocked_classes[user_id] = [DEFAULT_CLASS]
    return unlocked_classes[user_id]


def unlock_class(user_id: int, class_name: str) -> bool:
    if class_name not in CLASSES:
        return False
    if class_name in get_unlocked_classes(user_id):
        return False

    price = CLASSES[class_name]["price"]
    if not remove_balance(user_id, price):
        return False

    unlocked_classes[user_id].append(class_name)
    return True


# === БОНУСЫ ===
def get_weapon_bonus(user_id: int) -> int:
    weapon = player_weapons.get(user_id)
    if weapon and weapon in WEAPONS:
        return WEAPONS[weapon]["damage_bonus"]
    return 0


def get_armor_bonus(user_id: int) -> int:
    armor = player_armors.get(user_id)
    if armor and armor in ARMORS:
        return ARMORS[armor]["hp_bonus"]
    return 0


# === MMR ===
def update_mmr(winner_id: int, loser_id: int):
    winner_stats = get_stats(winner_id)
    loser_stats = get_stats(loser_id)

    k = 32

    expected_winner = 1 / (1 + 10 ** ((loser_stats['mmr'] - winner_stats['mmr']) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_stats['mmr'] - loser_stats['mmr']) / 400))

    winner_change = int(k * (1 - expected_winner))
    loser_change = int(k * (0 - expected_loser))

    winner_stats['mmr'] += winner_change
    loser_stats['mmr'] = max(0, loser_stats['mmr'] + loser_change)

    return winner_change, loser_change


# === ДОСТИЖЕНИЯ ===
def check_achievements(user_id: int) -> List[str]:
    stats = get_stats(user_id)
    balance = get_balance(user_id)
    unlocked = []

    for ach_id, ach_data in ACHIEVEMENTS.items():
        if ach_data['name'] in stats.get('achievements', []):
            continue

        if ach_data['type'] == 'wins' and stats['wins'] >= ach_data['requirement']:
            unlocked.append(ach_data['name'])

        elif ach_data['type'] == 'balance' and balance >= ach_data['requirement']:
            unlocked.append(ach_data['name'])

        elif ach_data['type'] == 'mmr' and stats['mmr'] >= ach_data['requirement']:
            unlocked.append(ach_data['name'])

    if unlocked:
        if 'achievements' not in stats:
            stats['achievements'] = []

        for title in unlocked:
            if title not in stats['achievements']:
                stats['achievements'].append(title)
                add_balance(user_id, 200)

    return unlocked


# === ИСТОРИЯ БОЁВ ===
def add_battle_history(winner_id: int, loser_id: int, winner_hp: int, loser_hp: int):
    record = {
        'timestamp': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'winner': winner_id,
        'loser': loser_id,
        'winner_hp': winner_hp,
        'loser_hp': loser_hp
    }

    for uid in [winner_id, loser_id]:
        if uid not in battle_history:
            battle_history[uid] = []

        battle_history[uid].insert(0, record)

        if len(battle_history[uid]) > 10:
            battle_history[uid].pop()


# === КВЕСТЫ ===
DAILY_QUESTS = [
    {"name": "Тренировка", "description": "Выиграть 1 дуэль", "target": 1, "reward": (5, 10)},
    {"name": "Боец", "description": "Выиграть 3 дуэли", "target": 3, "reward": (10, 15)},
]

WEEKLY_QUESTS = [
    {"name": "Ветеран арены", "description": "Выиграть 10 дуэлей", "target": 10, "reward": (15, 25)},
]


def generate_daily_quests():
    quests = random.sample(DAILY_QUESTS, min(2, len(DAILY_QUESTS)))
    return {
        "quests": quests,
        "progress": [0] * len(quests),
        "completed": [False] * len(quests),
        "last_reset": datetime.now().date()
    }


def generate_weekly_quests():
    quests = random.sample(WEEKLY_QUESTS, min(2, len(WEEKLY_QUESTS)))
    return {
        "quests": quests,
        "progress": [0] * len(quests),
        "completed": [False] * len(quests),
        "last_reset": datetime.now().date()
    }


def get_quests(user_id: int):
    if user_id not in player_quests:
        player_quests[user_id] = {
            "daily": generate_daily_quests(),
            "weekly": generate_weekly_quests()
        }
    return player_quests[user_id]

class Duel:
    def __init__(self, player1: discord.Member, player2: discord.Member):
        self.p1 = player1
        self.p2 = player2

        self.p1_class = get_player_class(player1.id)
        self.p2_class = get_player_class(player2.id)

        base_hp1 = CLASSES[self.p1_class]["hp"]
        base_hp2 = CLASSES[self.p2_class]["hp"]

        armor1 = get_armor_bonus(player1.id)
        armor2 = get_armor_bonus(player2.id)

        self.p1_max_hp = base_hp1 + armor1
        self.p2_max_hp = base_hp2 + armor2

        self.p1_hp = self.p1_max_hp
        self.p2_hp = self.p2_max_hp

        self.turn = random.choice([self.p1, self.p2])
        self.active = False
        self.ended = False
        self.winner = None

        self.bets: Dict[int, dict] = {}
        self.total_damage = {self.p1.id: 0, self.p2.id: 0}
        self.total_heal = {self.p1.id: 0, self.p2.id: 0}

        self.last_heal = {self.p1.id: False, self.p2.id: False}

        self.message = None
        self.bet_message = None

    # ======================
    # СТАВКИ
    # ======================
    def place_bet(self, user: discord.Member, target: discord.Member, amount: int):
        if user.id in self.bets:
            return False, "❌ Ты уже ставил!"

        if user.id in [self.p1.id, self.p2.id]:
            return False, "❌ Игроки не ставят ставки!"

        if target.id not in [self.p1.id, self.p2.id]:
            return False, "❌ Можно ставить только на участников!"

        if not remove_balance(user.id, amount):
            return False, f"❌ Нет {CURRENCY_NAME}"

        self.bets[user.id] = {"target": target, "amount": amount}
        return True, "✅ Ставка принята!"

    # ======================
    # УРОН
    # ======================
    def attack(self, attacker: discord.Member, defender: discord.Member):
        cls = CLASSES[get_player_class(attacker.id)]

        dmg = random.randint(cls["damage_min"], cls["damage_max"])
        dmg += get_weapon_bonus(attacker.id)

        crit = random.random() < cls["crit_chance"]
        if crit:
            dmg *= 2

        if defender.id == self.p1.id:
            self.p1_hp = max(0, self.p1_hp - dmg)
            hp = self.p1_hp
            max_hp = self.p1_max_hp
        else:
            self.p2_hp = max(0, self.p2_hp - dmg)
            hp = self.p2_hp
            max_hp = self.p2_max_hp

        self.total_damage[attacker.id] += dmg

        return f"{'💥 КРИТ! ' if crit else ''}{attacker.mention} наносит **{dmg}** урона → {hp}/{max_hp} HP"

    # ======================
    # СУПЕР
    # ======================
    def heavy_attack(self, attacker: discord.Member, defender: discord.Member):
        cls = CLASSES[get_player_class(attacker.id)]

        if random.random() < cls["heavy_miss"]:
            return f"😵 {attacker.mention} промахнулся!"

        dmg = random.randint(cls["heavy_min"], cls["heavy_max"])
        dmg += get_weapon_bonus(attacker.id)

        if defender.id == self.p1.id:
            self.p1_hp = max(0, self.p1_hp - dmg)
            hp = self.p1_hp
            max_hp = self.p1_max_hp
        else:
            self.p2_hp = max(0, self.p2_hp - dmg)
            hp = self.p2_hp
            max_hp = self.p2_max_hp

        self.total_damage[attacker.id] += dmg

        return f"🔥 {attacker.mention} супер-атака → **{dmg}** урона ({hp}/{max_hp})"

    # ======================
    # ЛЕЧЕНИЕ (ИСПРАВЛЕНО)
    # ======================
    def heal(self, healer: discord.Member):
        cls = CLASSES[get_player_class(healer.id)]

        if self.last_heal[healer.id]:
            return f"❌ {healer.mention} нельзя лечиться 2 раза подряд!"

        heal = random.randint(cls["heal_min"], cls["heal_max"])

        if healer.id == self.p1.id:
            self.p1_hp = min(self.p1_max_hp, self.p1_hp + heal)
            hp = self.p1_hp
            max_hp = self.p1_max_hp
        else:
            self.p2_hp = min(self.p2_max_hp, self.p2_hp + heal)
            hp = self.p2_hp
            max_hp = self.p2_max_hp

        self.last_heal[healer.id] = True

        return f"💚 {healer.mention} лечится +{heal} HP ({hp}/{max_hp})"

    # ======================
    # ПОБЕДИТЕЛЬ
    # ======================
    def check_winner(self):
        if self.p1_hp <= 0:
            self.winner = self.p2
            self.ended = True
            return self.p2

        if self.p2_hp <= 0:
            self.winner = self.p1
            self.ended = True
            return self.p1

        return None

    # ======================
    # СТАВКИ ВЫПЛАТА
    # ======================
    def payout_bets(self):
        if not self.winner:
            return "Нет победителя", 0

        total = sum(b["amount"] for b in self.bets.values())
        winners = [b for b in self.bets.values() if b["target"].id == self.winner.id]

        if not winners:
            reward = int(total * 0.5)
            add_balance(self.winner.id, reward)
            return f"🎰 никто не угадал → {reward}", reward

        pool = sum(b["amount"] for b in winners)

        result_text = ""
        bonus = 0

        for uid, bet in self.bets.items():
            if bet["target"].id == self.winner.id:
                win = int(bet["amount"] * (total / pool))
                add_balance(uid, win)
                result_text += f"<@{uid}> +{win}\n"
            else:
                result_text += f"<@{uid}> проиграл\n"

        return result_text, bonus

    # ======================
    # СТАТУС
    # ======================
    def is_over(self):
        return self.p1_hp <= 0 or self.p2_hp <= 0
    
    bot.run(os.getenv('DISCORD_TOKEN'))