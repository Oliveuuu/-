import discord
from discord.ext import commands, tasks
from discord import app_commands
import feedparser
import aiohttp
import json
import os
from datetime import datetime
from dateutil import parser as dateparser
from dico_token import Token

# === 파일 경로 ===
GAMES_FILE = "games.json"
CONFIG_FILE = "config.json"
LATEST_FILE = "latest.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# === 파일 입출력 ===
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_server_games(guild_id):
    all_games = load_json(GAMES_FILE)
    return all_games.get(str(guild_id), {})

def set_server_games(guild_id, games):
    all_games = load_json(GAMES_FILE)
    all_games[str(guild_id)] = games
    save_json(GAMES_FILE, all_games)

def get_server_latest(guild_id):
    all_latest = load_json(LATEST_FILE)
    return all_latest.get(str(guild_id), {})

def set_server_latest(guild_id, latest):
    all_latest = load_json(LATEST_FILE)
    all_latest[str(guild_id)] = latest
    save_json(LATEST_FILE, all_latest)

def get_server_config():
    return load_json(CONFIG_FILE)

def set_server_config(data):
    save_json(CONFIG_FILE, data)

# === Steam 앱 ID 검색 ===
async def search_app_id(game_name):
    url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=korean&cc=KR"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json()
            if data["total"] > 0:
                app = data["items"][0]
                return app["id"], app["name"]
    return None, None

# === 최신 뉴스 가져오기 ===
def get_latest_news(app_id):
    url = f"https://store.steampowered.com/feeds/news/app/{app_id}/"
    feed = feedparser.parse(url)
    if feed.entries:
        return {
            "title": feed.entries[0].title,
            "link": feed.entries[0].link,
            "published": feed.entries[0].published,
        }
    return None

# === /추가 ===
@tree.command(name="추가", description="스팀 게임 업데이트 감시 시작")
@app_commands.describe(게임이름="스팀 게임 이름")
async def add_game(interaction: discord.Interaction, 게임이름: str):
    await interaction.response.defer()
    app_id, name = await search_app_id(게임이름)
    if not app_id:
        await interaction.followup.send("❌ 게임을 찾을 수 없습니다.")
        return

    guild_id = interaction.guild_id
    games = get_server_games(guild_id)
    if str(app_id) in games:
        await interaction.followup.send(f"✅ 이미 등록된 게임입니다: **{name}**")
        return

    games[str(app_id)] = name
    set_server_games(guild_id, games)
    await interaction.followup.send(f"✅ **{name}** (App ID: {app_id}) 등록 완료!")

# === /제거 ===
@tree.command(name="제거", description="감시 중인 게임 제거")
@app_commands.describe(게임이름="제거할 게임 이름")
async def remove_game(interaction: discord.Interaction, 게임이름: str):
    await interaction.response.defer()
    guild_id = interaction.guild_id
    games = get_server_games(guild_id)
    found = None
    for app_id, name in games.items():
        if 게임이름.lower() in name.lower():
            found = app_id
            break

    if not found:
        await interaction.followup.send("❌ 해당 게임을 찾을 수 없습니다.")
        return

    removed_name = games.pop(found)
    set_server_games(guild_id, games)
    await interaction.followup.send(f"🗑️ **{removed_name}** 감시 중지 완료!")

# === /목록 ===
class RemoveGameView(discord.ui.View):
    def __init__(self, guild_id, games):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        for app_id, name in games.items():
            self.add_item(RemoveGameButton(guild_id, app_id, name))

class RemoveGameButton(discord.ui.Button):
    def __init__(self, guild_id, app_id, name):
        super().__init__(label=name, style=discord.ButtonStyle.danger)
        self.guild_id = guild_id
        self.app_id = app_id
        self.name = name

    async def callback(self, interaction: discord.Interaction):
        games = get_server_games(self.guild_id)
        if self.app_id in games:
            games.pop(self.app_id)
            set_server_games(self.guild_id, games)
            await interaction.response.send_message(f"🗑️ **{self.name}** 제거 완료!", ephemeral=True)
        else:
            await interaction.response.send_message("이미 제거되었거나 존재하지 않습니다.", ephemeral=True)

@tree.command(name="목록", description="감시 중인 게임 목록 보기")
async def list_games(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    games = get_server_games(guild_id)
    if not games:
        await interaction.response.send_message("📭 현재 감시 중인 게임이 없습니다.")
        return

    embed = discord.Embed(title="🎮 감시 중인 게임 목록", color=discord.Color.green())
    for app_id, name in games.items():
        embed.add_field(name=name, value=f"App ID: {app_id}", inline=False)

    await interaction.response.send_message(embed=embed, view=RemoveGameView(guild_id, games))

# === /채널설정 ===
@tree.command(name="채널설정", description="스팀 알림을 보낼 채널을 설정합니다.")
async def set_channel(interaction: discord.Interaction):
    config = get_server_config()
    config[str(interaction.guild_id)] = interaction.channel.id
    set_server_config(config)
    await interaction.response.send_message(f"✅ 알림 채널이 **#{interaction.channel.name}** 으로 설정되었습니다.")

# === /업뎃 ===
@tree.command(name="업뎃", description="특정 게임의 최신 업데이트 정보를 보여줍니다.")
@app_commands.describe(게임이름="스팀 게임 이름")
async def latest_update(interaction: discord.Interaction, 게임이름: str):
    await interaction.response.defer()
    app_id, name = await search_app_id(게임이름)
    if not app_id:
        await interaction.followup.send("❌ 게임을 찾을 수 없습니다.")
        return

    news = get_latest_news(app_id)
    if not news:
        await interaction.followup.send("📭 해당 게임에 대한 최근 뉴스가 없습니다.")
        return

    embed = discord.Embed(
        title=news["title"],
        url=news["link"],
        description=f"**{name}**의 최신 업데이트입니다.",
        color=discord.Color.orange()
    )
    embed.set_footer(text=news["published"])
    embed.set_thumbnail(url=f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/capsule_184x69.jpg")
    await interaction.followup.send(embed=embed)

# === 주기적인 업데이트 감지 ===
@tasks.loop(minutes=10)
async def check_updates():
    config = get_server_config()
    for guild_id, channel_id in config.items():
        guild_games = get_server_games(guild_id)
        guild_latest = get_server_latest(guild_id)

        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"❌ 채널 {channel_id} 찾을 수 없음 (서버 {guild_id})")
            continue

        for app_id, name in guild_games.items():
            news = get_latest_news(app_id)
            if not news:
                continue

            if app_id not in guild_latest or guild_latest[app_id]["title"] != news["title"]:
                guild_latest[app_id] = news
                set_server_latest(guild_id, guild_latest)

                embed = discord.Embed(
                    title=news["title"],
                    url=news["link"],
                    description=f"**{name}**에 새로운 업데이트가 있습니다!",
                    color=discord.Color.blurple()
                )
                embed.set_footer(text=news["published"])
                embed.set_thumbnail(url=f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/capsule_184x69.jpg")

                await channel.send(embed=embed)

# === 봇 시작 ===
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ {bot.user} 로그인 완료")
    check_updates.start()

bot.run(Token)
