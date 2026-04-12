import os
import random
import sqlite3
import threading
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask

# =========================
# FLASK (Render keep alive)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "⚔️ Anime Duel Bot ONLINE"


# =========================
# CONFIG
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")

DB_PATH = "bot.db"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# =========================
# SQLITE
# =========================
def db():
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id TEXT PRIMARY KEY,
        balance INTEGER DEFAULT 100,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        mmr INTEGER DEFAULT 1000,
        character TEXT DEFAULT 'Годжо',
        weapon TEXT DEFAULT 'none',
        armor TEXT DEFAULT 'none',
        last_daily TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_user(uid):
    conn = db()
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE id=?", (str(uid),))
    row = c.fetchone()

    if not row:
        c.execute("INSERT INTO users(id) VALUES(?)", (str(uid),))
        conn.commit()
        conn.close()
        return get_user(uid)

    conn.close()

    return {
        "id": row[0],
        "balance": row[1],
        "wins": row[2],
        "losses": row[3],
        "mmr": row[4],
        "character": row[5],
        "weapon": row[6],
        "armor": row[7],
        "last_daily": row[8]
    }


def update_user(uid, **kwargs):
    conn = db()
    c = conn.cursor()

    keys = ",".join([f"{k}=?" for k in kwargs.keys()])
    values = list(kwargs.values())
    values.append(str(uid))

    c.execute(f"UPDATE users SET {keys} WHERE id=?", values)
    conn.commit()
    conn.close()


# =========================
# ADMIN
# =========================
def is_admin(user_id):
    return str(user_id) in ADMIN_IDS


# =========================
# CHARACTERS (anime skills)
# =========================
CHARACTERS = {
    "Годжо": {"hp": 120, "min": 18, "max": 35, "crit": 0.20, "dodge": 0.15, "style": "Фиолетовая техника"},
    "Итадори": {"hp": 130, "min": 15, "max": 32, "crit": 0.18, "dodge": 0.10, "style": "Чёрная вспышка"},
    "Сукуна": {"hp": 150, "min": 22, "max": 40, "crit": 0.22, "dodge": 0.05, "style": "Проклятый разрез"},
    "Ичиго": {"hp": 140, "min": 18, "max": 34, "crit": 0.17, "dodge": 0.12, "style": "Гетсуга Теншоу"},
    "Луффи": {"hp": 155, "min": 16, "max": 33, "crit": 0.15, "dodge": 0.18, "style": "Гир 5 удар"},
    "Зоро": {"hp": 160, "min": 20, "max": 38, "crit": 0.16, "dodge": 0.08, "style": "Трёхмечевой стиль"},
    "Киллуа": {"hp": 125, "min": 17, "max": 30, "crit": 0.25, "dodge": 0.30, "style": "Годспид"},
    "Меруэм": {"hp": 200, "min": 25, "max": 45, "crit": 0.30, "dodge": 0.10, "style": "Королевский удар"},
}


# =========================
# SHOP
# =========================
WEAPONS = {
    "Катана": {"price": 800, "dmg": 3, "crit": 0.02},
    "Лук": {"price": 600, "dmg": 2, "crit": 0.05},
    "Кинжал": {"price": 400, "dmg": 1, "crit": 0.10},
    "Занпакто": {"price": 2500, "dmg": 8},
    "Экскалибур": {"price": 15000, "dmg": 35, "crit": 0.10},
}

ARMOR = {
    "Кимоно": {"price": 800, "hp": 20, "block": 0.05},
    "Доспех": {"price": 600, "hp": 15, "block": 0.08},
    "Шинигами": {"price": 2500, "hp": 50, "block": 0.12},
    "Золотая броня": {"price": 15000, "hp": 250, "block": 0.25},
}


# =========================
# UTILS COMBAT
# =========================
def roll(min_v, max_v):
    return random.randint(min_v, max_v)


def calc_damage(char, weapon):
    dmg = roll(char["min"], char["max"])
    dmg += WEAPONS.get(weapon, {}).get("dmg", 0)
    return dmg


def crit(char, weapon):
    base = char.get("crit", 0.1)
    base += WEAPONS.get(weapon, {}).get("crit", 0)
    return random.random() < base


def dodge(char):
    return random.random() < char.get("dodge", 0)


def block(armor):
    return random.random() < ARMOR.get(armor, {}).get("block", 0)


# =========================
# DUEL CORE
# =========================
async def duel_embed(ctx, p1_id, p2_id):
    p1 = get_user(p1_id)
    p2 = get_user(p2_id)

    c1 = CHARACTERS[p1["character"]]
    c2 = CHARACTERS[p2["character"]]

    hp1 = c1["hp"] + ARMOR.get(p1["armor"], {}).get("hp", 0)
    hp2 = c2["hp"] + ARMOR.get(p2["armor"], {}).get("hp", 0)

    log = []

    turn = True
    round_n = 1

    while hp1 > 0 and hp2 > 0:

        attacker = p1 if turn else p2
        defender = p2 if turn else p1
        ca = c1 if turn else c2
        cd = c2 if turn else c1

        weapon_a = attacker["weapon"]

        dmg = calc_damage(ca, weapon_a)

        # dodge
        if dodge(cd):
            log.append(f"💨 {defender['character']} уклонился!")
            turn = not turn
            continue

        # block
        if block(defender["armor"]):
            dmg = int(dmg * 0.5)
            log.append(f"🛡️ {defender['character']} заблокировал удар!")

        # crit
        if crit(ca, weapon_a):
            dmg *= 2
            log.append(f"💥 КРИТ от {attacker['character']}!")

        hp = hp2 if turn else hp1
        hp -= dmg

        if turn:
            hp2 = hp
        else:
            hp1 = hp

        style = ca["style"]
        log.append(f"⚔️ {attacker['character']} использует {style} и наносит {dmg}")

        turn = not turn
        round_n += 1

        if round_n > 50:
            break

    winner = p1 if hp1 > hp2 else p2
    loser = p2 if winner == p1 else p1

    # rewards
    winner["wins"] += 1
    loser["losses"] += 1

    winner["balance"] += 15

    update_user(winner["id"],
                wins=winner["wins"],
                balance=winner["balance"])

    update_user(loser["id"], losses=loser["losses"])

    embed = discord.Embed(title="⚔️ ДУЭЛЬ ЗАВЕРШЕНА", color=0xff0000)
    embed.add_field(name="🏆 Победитель", value=winner["character"])
    embed.add_field(name="📜 Лог боя", value="\n".join(log[:8]), inline=False)

    await ctx.send(embed=embed)


# =========================
# COMMANDS
# =========================
@bot.command()
async def баланс(ctx):
    u = get_user(ctx.author.id)
    await ctx.send(f"💰 Баланс: {u['balance']} ДАЙР")


@bot.command()
async def дуэль(ctx, enemy: discord.Member):
    await duel_embed(ctx, ctx.author.id, enemy.id)


@bot.command()
async def магазин(ctx):
    text = "🛒 ОРУЖИЕ:\n"
    for k,v in WEAPONS.items():
        text += f"{k} - {v['price']}\n"

    text += "\n🛡 БРОНЯ:\n"
    for k,v in ARMOR.items():
        text += f"{k} - {v['price']}\n"

    await ctx.send(text)


@bot.command()
async def купить(ctx, item):
    u = get_user(ctx.author.id)

    if item in WEAPONS:
        price = WEAPONS[item]["price"]
        if u["balance"] >= price:
            update_user(ctx.author.id, balance=u["balance"] - price, weapon=item)
            return await ctx.send("⚔️ куплено")

    if item in ARMOR:
        price = ARMOR[item]["price"]
        if u["balance"] >= price:
            update_user(ctx.author.id, balance=u["balance"] - price, armor=item)
            return await ctx.send("🛡 куплено")

    await ctx.send("❌ нет")


# =========================
# SLASH
# =========================
@tree.command(name="баланс")
async def slash_balance(interaction):
    u = get_user(interaction.user.id)
    await interaction.response.send_message(f"💰 {u['balance']} ДАЙР")


# =========================
# LEADERBOARD
# =========================
@bot.command()
async def топ(ctx):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    text = "🏆 TOP:\n"
    for r in rows:
        text += f"{r[0]} - {r[1]}\n"

    await ctx.send(text)


# =========================
# START
# =========================
@bot.event
async def on_ready():
    tree.sync()
    print("BOT READY")


def run_bot():
    bot.run(TOKEN)


if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))