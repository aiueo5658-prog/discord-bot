"""
文化祭カウントダウン Bot
毎日 7:30 (JST) に「文化祭まであと○○日」+ 今日の占いデータ(外部API) + 軽い一言を投稿する。

■ 必要な準備
  1. pip install discord.py aiohttp
  2. Discord Developer Portal で Bot を作成し、TOKEN を取得
  3. Bot に対象チャンネルへの「メッセージ送信」権限を付与してサーバーに招待
  4. 下の設定値(CHANNEL_ID, EVENT_DATE)を書き換える
     ※ TOKEN は環境変数 DISCORD_BOT_TOKEN に入れる想定(コードに直書きしない)

■ 占いデータについて
  「今日は何の日API」(https://note.com/sooz/n/naffb68c7f53b)を利用しています。
  日付(mmdd)を渡すとその日の記念日をJSONで返す無料API(認証不要)。
  利用条件として、投稿元へのリンク掲示が求められているため、投稿文の末尾に毎回添えています。
  また提供者から「過度なアクセスは控えるように」と案内されているため、1日1回の利用に留めてください。

■ 起動方法
  python countdown_bot.py
"""

import os
import random
from datetime import date, datetime, time, timezone, timedelta

import aiohttp
import discord
from discord.ext import commands, tasks

# ========= 設定値(ここを書き換える) =========

# 投稿したいチャンネルのID(チャンネルを右クリック→IDをコピー。要:開発者モードON)
CHANNEL_ID = 1355363072729944195  # ← 自分のサーバーのチャンネルIDに変更してください

# 文化祭初日
EVENT_DATE = date(2026, 10, 31)

# 投稿時刻(JST 7:30)
JST = timezone(timedelta(hours=9))
POST_TIME = time(hour=7, minute=30, tzinfo=JST)

# 今日は何の日API(https://note.com/sooz/n/naffb68c7f53b)
WHATISTODAY_API_URL = "https://api.whatistoday.cyou/v3/anniv/{mmdd}"
WHATISTODAY_CREDIT = "記念日データ提供: 今日は何の日API (https://note.com/sooz/n/naffb68c7f53b)"

# ============================================

# 締めの一言(軽め・強制感なし)
CLOSINGS = [
    "ということでみんな頑張ろうね～",
    "まあ、ぼちぼちいきましょう",
    "そんな感じで今日も一日よろしくね",
    "というわけで、みんな適度にやっていこう",
    "今日もゆるく頑張ろう",
]


def get_days_left() -> int:
    """文化祭当日までの残り日数を計算(当日は0)"""
    today = datetime.now(JST).date()
    return (EVENT_DATE - today).days


async def fetch_today_calendar_data() -> dict:
    """暦データAPIから当月分を取得し、今日の1日分のデータを返す。
    取得に失敗した場合は None を返す。
    """
    today = datetime.now(JST).date()
    url = CALENDAR_API_URL.format(year=today.year, month=today.month)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
    except Exception as e:
        print(f"[暦データAPI取得エラー] {e}")
        return None

    try:
        day_data = next(d for d in data["days"] if d["day"] == today.day)
        return day_data
    except (KeyError, StopIteration, TypeError) as e:
        print(f"[暦データ形式エラー] {e}")
        return None


async def build_message() -> str:
    days_left = get_days_left()
    closing = random.choice(CLOSINGS)

    if days_left > 0:
        header = f"文化祭まであと{days_left}日"
    elif days_left == 0:
        header = "今日から文化祭!!!!"
    else:
        header = "文化祭、お疲れ様でした"

    day_data = await fetch_today_calendar_data()
    if day_data is None:
        fortune_block = "今日の暦情報：取得できませんでした"
    else:
        rokuyo = day_data.get("rokuyo", "不明")
        keyword = day_data.get("daily_keyword", "")
        advice = day_data.get("energy_advice", "")
        lines = [f"今日は{rokuyo}"]
        if keyword:
            lines.append(keyword)
        if advice:
            lines.append(advice)
        fortune_block = "\n".join(lines)

    return f"{header}\n\n{fortune_block}\n\n{closing}"


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(time=POST_TIME)
async def daily_countdown():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"[エラー] チャンネルID {CHANNEL_ID} が見つかりません。CHANNEL_IDを確認してください。")
        return
    await channel.send(await build_message())


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
    await ctx.send(await build_message())


if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "環境変数 DISCORD_BOT_TOKEN が設定されていません。\n"
            "例: export DISCORD_BOT_TOKEN='your_token_here'"
        )
    bot.run(token)

