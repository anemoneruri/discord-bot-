import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
from datetime import datetime
import feedparser

TOKEN = os.environ["TOKEN"]

# 募集を管理する辞書 {ユーザーID: メッセージID}
active_recruits = {}

# 募集専用チャンネルID（Discordで右クリック→IDをコピー）
RECRUIT_CHANNEL_ID = 1416484401058938880  

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    print(f"ログインしました: {bot.user}")

# /event コマンドの追加
@bot.tree.command(name="event", description="イベント情報を投稿します")
@app_commands.describe(
    name="イベント名",
    period="イベント期間",
    condition="参加条件",
    image_url="イベント画像URL"
)
async def event(interaction: discord.Interaction, name: str, period: str, condition: str, image_url: str = None):
    embed = discord.Embed(
        title=name,
        description=f"📅 期間: {period}\n📝 条件: {condition}",
        color=0x1abc9c
    )
    if image_url:
        embed.set_image(url=image_url)

    await interaction.response.send_message(embed=embed)

# /gacha コマンドの追加
@bot.tree.command(name="gacha", description="ガチャ情報を投稿します")
@app_commands.describe(
    name="ガチャ名",
    period="開催期間",
    characters="ピックアップキャラ",
    weapons="ピックアップ武器",
    image_url="ガチャ画像URL"
)
async def gacha(
    interaction: discord.Interaction,
    name: str,
    period: str,
    characters: str,
    weapons: str = None,
    image_url: str = None
):
    embed = discord.Embed(
        title=f"🎰 {name}",
        description=f"📅 開催期間: {period}",
        color=0xe67e22
    )
    embed.add_field(name="⭐ ピックアップキャラ", value=characters, inline=False)
    if weapons:
        embed.add_field(name="🗡️ ピックアップ武器", value=weapons, inline=False)
    if image_url:
        embed.set_image(url=image_url)

    await interaction.response.send_message(embed=embed)

class RecruitView(discord.ui.View):
    def __init__(self, owner_id, max_members):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.max_members = max_members
        self.members = []

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members:
            await interaction.response.send_message("⚠️ すでに参加しています！", ephemeral=True)
            return

        self.members.append(interaction.user.id)

        # Embedを更新
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name="参加者", value=", ".join([f"<@{m}>" for m in self.members]), inline=False)

        # 満員ならロック
        if len(self.members) >= self.max_members:
            button.disabled = True
            embed.color = 0xe74c3c
            embed.title = f"🔒 {embed.title.replace('📢 ', '')}（満員）"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.defer()

    @discord.ui.button(label="退出する", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members:
            await interaction.response.send_message("⚠️ 参加していません！", ephemeral=True)
            return

        self.members.remove(interaction.user.id)

        # Embedを更新
        embed = interaction.message.embeds[0]
        if self.members:
            embed.set_field_at(1, name="参加者", value=", ".join([f"<@{m}>" for m in self.members]), inline=False)
        else:
            embed.set_field_at(1, name="参加者", value="(まだいません)", inline=False)

        # ロック解除
        self.join.disabled = False
        embed.color = 0x1abc9c
        embed.title = f"📢 {embed.title.replace('🔒 ', '').replace('（満員）', '')}"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.defer()

@bot.tree.command(name="recruit", description="マルチ募集を作成します")
@app_commands.describe(
    title="募集タイトル",
    description="募集内容",
    max_members="募集人数",
    role="募集対象のロール"
)
async def recruit(
    interaction: discord.Interaction,
    title: str,
    description: str,
    max_members: int,
    role: discord.Role = None
):
    user_id = interaction.user.id

    # ① 1人1つまでの制限
    if user_id in active_recruits:
        await interaction.response.send_message("⚠️ すでにあなたの募集が存在します！", ephemeral=True)
        return

    # ② 特定チャンネル限定
    if interaction.channel_id != RECRUIT_CHANNEL_ID:
        await interaction.response.send_message("⚠️ このコマンドは #マルチ募集 チャンネルでしか使えません。", ephemeral=True)
        return

    # Embedを作成
    embed = discord.Embed(title=f"📢 {title}", description=description, color=0x1abc9c)
    embed.add_field(name="募集人数", value=f"{max_members}人", inline=True)
    embed.add_field(name="参加者", value="(まだいません)", inline=False)

    # ロール指定があれば先頭にメンションを追加
    content = f"{role.mention}" if role else None

    # ボタン付きメッセージ送信
    view = RecruitView(interaction.user.id, max_members)
    message = await interaction.channel.send(content=content, embed=embed, view=view)

    # 募集を記録
    active_recruits[user_id] = message.id
    await interaction.response.send_message("✅ 募集を作成しました！", ephemeral=True)

@bot.tree.command(name="close_recruit", description="自分の募集を終了します")
async def close_recruit(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    if user_id not in active_recruits:
        await interaction.response.send_message("募集中の投稿がありません。", ephemeral=True)
        return
    
    # 募集を削除
    del active_recruits[user_id]
    await interaction.response.send_message("募集を終了しました。", ephemeral=True)

@bot.tree.command(name="maintenance", description="メンテナンス情報を登録します")
@app_commands.describe(
    title="メンテナンスのタイトル",
    start_time="開始日時 (例: 2025-09-14 06:00)",
    end_time="終了日時 (例: 2025-09-14 11:00)"
)
async def maintenance(interaction: discord.Interaction, title: str, start_time: str, end_time: str):
    channel = interaction.channel

    # 時刻をdatetimeに変換
    fmt = "%Y-%m-%d %H:%M"
    start_dt = datetime.strptime(start_time, fmt)
    end_dt = datetime.strptime(end_time, fmt)

    # メンテ予定のEmbed
    embed = discord.Embed(
        title=f"🛠️ メンテナンス情報",
        description=f"**{title}**",
        color=0x3498db
    )
    embed.add_field(name="開始", value=start_dt.strftime("%Y-%m-%d %H:%M"), inline=False)
    embed.add_field(name="終了", value=end_dt.strftime("%Y-%m-%d %H:%M"), inline=False)

    await interaction.response.send_message(embed=embed)

    # メンテ開始通知タスク
    async def notify_start():
        await asyncio.sleep((start_dt - datetime.now()).total_seconds())
        await channel.send(f"⚠️ メンテナンス開始: **{title}**")

    # メンテ終了通知タスク
    async def notify_end():
        await asyncio.sleep((end_dt - datetime.now()).total_seconds())
        await channel.send(f"✅ メンテナンス終了: **{title}**")

    bot.loop.create_task(notify_start())
    bot.loop.create_task(notify_end())

# ニュースチェックコマンド
@bot.tree.command(name="check_news", description="最新の原神ニュースを確認します")
async def check_news(interaction: discord.Interaction):
    feed_url = "https://genshin-feed.com/feed/rss-ja-info.xml"
    feed = feedparser.parse(feed_url)

    if not feed.entries:
        await interaction.response.send_message("ニュースが取得できませんでした。", ephemeral=True)
        return

    latest = feed.entries[0]  # 最新記事
    title = latest.title
    link = latest.link
    published = latest.published if "published" in latest else "日付不明"

    embed = discord.Embed(
        title=f"📰 {title}",
        url=link,
        description=f"公開日: {published}",
        color=0x3498db
    )
    embed.set_footer(text="データ提供: genshin-feed.com")

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)