"""
文化祭カウントダウン Bot
毎日 7:30 (JST) に「文化祭まであと○○日」を投稿する。
また、!role コマンドでメンバーが自分でロールを付け外しできる。

■ 必要な準備
  1. pip install discord.py
  2. Discord Developer Portal で Bot を作成し、TOKEN を取得
  3. Bot に対象チャンネルへの「メッセージ送信」権限を付与してサーバーに招待
  4. 下の設定値(CHANNEL_ID, EVENT_DATE, ASSIGNABLE_ROLES)を書き換える
     ※ TOKEN は環境変数 DISCORD_BOT_TOKEN に入れる想定(コードに直書きしない)
  5. Discord Developer Portal の Bot ページで「MESSAGE CONTENT INTENT」をON
  6. サーバー設定でBotのロールを、ASSIGNABLE_ROLESに含めた全ロールより上に配置し、
     Botに「Manage Roles」権限を付与すること(これがないと付け外しに失敗する)

■ セルフロール機能の使い方(Discord上で)
  !role list            付け外しできるロール一覧を表示
  !role add ロール名     ロールを付ける(例: !role add プログラミング島)
  !role remove ロール名  ロールを外す

■ 起動方法
  python countdown_bot.py
"""

import os
from datetime import date, datetime, time, timezone, timedelta

import discord
from discord.ext import commands, tasks

# ========= 設定値(ここを書き換える) =========

# 投稿したいチャンネルのID
CHANNEL_ID = 1355363072729944195  # 「広場」チャンネル

# 文化祭初日
EVENT_DATE = date(2026, 10, 31)

# 投稿時刻(JST 7:30)
JST = timezone(timedelta(hours=9))
POST_TIME = time(hour=7, minute=30, tzinfo=JST)

# チャットで自由に付け外しできるロール名の一覧(サーバーのロール名と完全一致させること)
# 学年ロール(J1〜J3, S1〜S3)・管理者・Bot用ロール(carl-bot, Combu BOT)は対象外
ASSIGNABLE_ROLES = [
    "音楽島",
    "プログラミング島",
    "映像島",
    "モデル島",
    "OB/OG",
    "ドローン島",
    "Java版マイクラ自治区",
    "VRChatお嬢様自治区",
    "Bloxd自治区",
    "電脳旋律研究所",
]

# ============================================


def get_days_left() -> int:
    """文化祭当日までの残り日数を計算(当日は0)"""
    today = datetime.now(JST).date()
    return (EVENT_DATE - today).days


def build_message() -> str:
    days_left = get_days_left()

    if days_left > 0:
        return f"**文化祭まであと{days_left}日！！**"
    elif days_left == 0:
        return "**今日から文化祭！！**"
    else:
        return "**文化祭、お疲れ様でした！！**"


intents = discord.Intents.default()
intents.message_content = True  # !countdown コマンドを読み取るために必要
bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(time=POST_TIME)
async def daily_countdown():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"[エラー] チャンネルID {CHANNEL_ID} が見つかりません。CHANNEL_IDを確認してください。")
        return
    await channel.send(build_message())


@daily_countdown.before_loop
async def before_daily_countdown():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Bot起動: {bot.user}")
    if not daily_countdown.is_running():
        daily_countdown.start()


# 動作確認用: 手動でカウントダウンを投稿させたいときに使うコマンド
@bot.command(name="countdown")
async def countdown_now(ctx):
    await ctx.send(build_message())


def find_assignable_role(guild: discord.Guild, role_name: str):
    """ホワイトリスト(ASSIGNABLE_ROLES)に含まれるロールだけを名前で検索する。
    大文字小文字・前後の空白の違いは吸収する。
    """
    target = role_name.strip().lower()
    allowed = {name.lower() for name in ASSIGNABLE_ROLES}
    if target not in allowed:
        return None
    for role in guild.roles:
        if role.name.lower() == target:
            return role
    return None


@bot.group(name="role", invoke_without_command=True)
async def role_group(ctx):
    """!role add <ロール名> / !role remove <ロール名> / !role list"""
    await ctx.send(
        "使い方：\n"
        "`!role list` : 付け外しできるロール一覧を見る\n"
        "`!role add ロール名` : ロールを付ける\n"
        "`!role remove ロール名` : ロールを外す"
    )


@role_group.command(name="list")
async def role_list(ctx):
    lines = "\n".join(f"・{name}" for name in ASSIGNABLE_ROLES)
    await ctx.send(f"付け外しできるロール一覧：\n{lines}")


@role_group.command(name="add")
async def role_add(ctx, *, role_name: str = None):
    if not role_name:
        await ctx.send("ロール名を指定してください。例：`!role add プログラミング島`")
        return

    role = find_assignable_role(ctx.guild, role_name)
    if role is None:
        await ctx.send(f"「{role_name}」は付け外し可能なロールに含まれていません。`!role list` で一覧を確認してください。")
        return

    if role in ctx.author.roles:
        await ctx.send(f"すでに「{role.name}」を持っています。")
        return

    try:
        await ctx.author.add_roles(role, reason="セルフロール機能による自己申請")
        await ctx.send(f"「{role.name}」を付けました。")
    except discord.Forbidden:
        await ctx.send(
            "権限が足りずロールを付けられませんでした。"
            "サーバー管理者に「Botのロール順位」と「Manage Roles権限」を確認してもらってください。"
        )


@role_group.command(name="remove")
async def role_remove(ctx, *, role_name: str = None):
    if not role_name:
        await ctx.send("ロール名を指定してください。例：`!role remove プログラミング島`")
        return

    role = find_assignable_role(ctx.guild, role_name)
    if role is None:
        await ctx.send(f"「{role_name}」は付け外し可能なロールに含まれていません。`!role list` で一覧を確認してください。")
        return

    if role not in ctx.author.roles:
        await ctx.send(f"「{role.name}」は付いていません。")
        return

    try:
        await ctx.author.remove_roles(role, reason="セルフロール機能による自己申請")
        await ctx.send(f"「{role.name}」を外しました。")
    except discord.Forbidden:
        await ctx.send(
            "権限が足りずロールを外せませんでした。"
            "サーバー管理者に「Botのロール順位」と「Manage Roles権限」を確認してもらってください。"
        )


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "環境変数 DISCORD_BOT_TOKEN が設定されていません。\n"
            "例: export DISCORD_BOT_TOKEN='your_token_here'"
        )
    bot.run(token)
