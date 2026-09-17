"""
文化祭カウントダウン Bot
毎日 7:30 (JST) に「文化祭まであと○○日」を投稿する。
また、!role コマンドでメンバーが自分でロールを付け外しできる。
さらに、活動日(火・金)の前日18:00に自動案内、スレッド延命機能も持つ。

■ 必要な準備
  1. pip install discord.py
  2. Discord Developer Portal で Bot を作成し、TOKEN を取得
  3. Bot に対象チャンネルへの「メッセージ送信」権限を付与してサーバーに招待
  4. 下の設定値(CHANNEL_ID, EVENT_DATE, ASSIGNABLE_ROLES, ANNOUNCEMENT_CHANNEL_ID,
     OFFICER_ROLE_NAMES など)を書き換える
     ※ TOKEN は環境変数 DISCORD_BOT_TOKEN に入れる想定(コードに直書きしない)
  5. Discord Developer Portal の Bot ページで「MESSAGE CONTENT INTENT」をON
  6. サーバー設定でBotのロールを、ASSIGNABLE_ROLESに含めた全ロールより上に配置し、
     Botに「Manage Roles」権限を付与すること(これがないと付け外しに失敗する)
  7. スレッド延命機能を使うには、Botに「スレッドの管理」「メッセージの管理」権限も必要
  8. データを再デプロイ後も残すには、RailwayでこのサービスにVolumeを作成し、
     /data にマウントすること(Volume未設定でもエラーにはならないが、
     再デプロイのたびにデータが消える)

■ セルフロール機能の使い方
  /role list             付け外しできるロール一覧を表示
  /role add ロール名      ロールを付ける(選択肢から選べます)
  /role remove ロール名   ロールを外す(選択肢から選べます)
  !role list / !role add ロール名 / !role remove ロール名  ↑と同じことを!コマンドでも可能

■ 活動日スケジュール自動投稿について
  ACTIVITY_WEEKDAYSに指定した曜日(デフォルトは火・金)の前日18:00(JST)に、
  ANNOUNCEMENT_CHANNEL_IDのチャンネルへ「明日は活動日です！！」と自動投稿する。
  /skip 日付 : OFFICER_ROLE_NAMESのロールを持つ人だけが使える。指定日の投稿をスキップする
  /unskip 日付 : スキップ設定を解除する
  /skipped : 現在スキップ中の日付一覧を見る(誰でも使用可)
  ※ skipped_dates はSQLiteデータベース(DB_PATH)に保存され、
    Volumeをマウントしていれば再デプロイをまたいで保持される。

■ スレッド延命(/save)機能について
  スレッド内で /save を実行すると、そのスレッドをキープアライブ対象として登録する。
  THREAD_CHECK_INTERVAL_HOURSごとに全登録スレッドをチェックし、最終投稿から
  THREAD_BUMP_AFTER_DAYS日経過していたら中身のないメッセージを送って即削除することで、
  Discordの自動アーカイブ(既定では1週間投稿がないとアーカイブされる)を回避する。
  /unsave で解除できる。
  ※ saved_thread_ids もSQLiteデータベース(DB_PATH)に保存され、
    Volumeをマウントしていれば再デプロイをまたいで保持される。

■ /greeting コマンドについて
  サーバーの挨拶文・ルール説明を表示するスラッシュコマンド。

■ /skills コマンドについて
  このBotで使えるコマンドの一覧を表示するスラッシュコマンド。

■ スラッシュコマンド全般の注意
  スラッシュコマンドを使うには、Botの招待時に「applications.commands」スコープが
  付与されている必要がある(botスコープだけでは動かない)。
  すでに招待済みのBotの場合は、OAuth2 URL Generatorで
  SCOPES「bot」「applications.commands」の両方にチェックを入れて
  生成したURLを開き、再度同じサーバーを選んで認証し直すこと(役割等は変わらない)。
  初回のコマンド反映(同期)には最大1時間ほどかかる場合がある。

■ 起動方法
  python countdown_bot.py
"""

import os
import sqlite3
from datetime import date, datetime, time, timezone, timedelta

import discord
from discord.ext import commands, tasks

# ========= 設定値(ここを書き換える) =========

# 投稿したいチャンネルのID
CHANNEL_ID = 1355363072729944195  # 「広場」チャンネル

# 文化祭初日
EVENT_DATE = date(2026, 10, 31)

# データベース(SQLite)のファイルパス。
# Railwayで永続化するには、このパスにVolumeをマウントすること
# (マウント先の例: /data → DB_PATH=/data/bot.db)。
# マウントしていない場合、再デプロイのたびに中身が消える点に注意。
DB_PATH = os.environ.get("DB_PATH", "/data/bot.db")

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

# ---- 活動日スケジュール自動投稿 ----
ANNOUNCEMENT_CHANNEL_ID = 1355341015535587498  # 「お知らせ」チャンネル
ACTIVITY_WEEKDAYS = {1, 4}  # 月=0, 火=1, 水=2, 木=3, 金=4, 土=5, 日=6 → 火・金
SCHEDULE_POST_HOUR = 18
SCHEDULE_POST_MINUTE = 0
SCHEDULE_POST_TIME = time(hour=SCHEDULE_POST_HOUR, minute=SCHEDULE_POST_MINUTE, tzinfo=JST)  # 前日18:00(JST)に投稿
# /skip コマンドを使える権限を持つロール名(このいずれかを持つ人だけ実行できる)
OFFICER_ROLE_NAMES = ["管理者"]

# ---- スレッド延命(/save)機能 ----
THREAD_BUMP_AFTER_DAYS = 5  # 最終投稿からこの日数が経過したら延命メッセージを送る
THREAD_CHECK_INTERVAL_HOURS = 24  # 延命チェックを実行する間隔

# ============================================

GREETING_TEXT = """<@&1410488275898204271> 
## ようこそ、コンピュータ部Discordサーバー「Discombu群島」へ！！

部員全員の創作活動をなるべく支援できるよう、自由な体制で運営していきますが以下のルールは最低限守ってくれると助かります！
- サーバー内で表示される名前を(学年)(クラス) (名前)に変更する
  - 例：S2B Kakeru Ariizumi
- 公序良俗に反する発言を避ける
  - サーバーの規模がそこまで大きくない上に身内で利用してはいますが、不快に感じる人が一定数いる可能性のある表現はなるべく控えましょう
- 「お知らせ」などのチャンネルなど、重要なチャットには既読も兼ねてリアクションを付けていきましょう！！

また、部活動に関して、あるいはDiscordに関してなどの相談や質問がある際には、以下の部員に気軽に話しかけてみよう！優しい先輩が多いです...！
- コンピュータ部：<@1486593667178168441>
- 高校部長：<@1229001921017155656>
- 高校副部長：<@1296438201971376139>
- 中学部長：<@1358774038201237687>
- 中学副部長：<@1393939808480657508>
- 部長補佐：<@1302962326776844352>
- 部長補佐：<@964848876370677771>

以下は各チャンネルの簡単な説明です！
### 昆布本島
- <#1354804966304387155> ：サーバーに新しく入ってくるメンバーを歓迎する場です、挨拶大事！
- <#1355341015535587498> ：名前の通り、活動に関する重要なお知らせをします、最低限ここだけでも定期的に見てほしい！！お願いします
- <#1355363072729944195> ：主に雑談をします、トピックは基本自由ですが、盛り上がりすぎて過激な発言をしないように気をつけてくださいね
- <#1355688180140998777> ：ここでは、プロジェクトの設立や活動の提案などを行います、自分たちで部活動を良くする環境があります
- <#1491032416679100467> ：このサーバーは閲覧専用で、部長や副部長たちのオススメする動画やコンテストなどが載っています、余裕があったら覗いてみてね！
- <#1367280021969965146> ：今はあまり整理できていませんが、アーカイブとしてGoogleドライブや各種リンクなどが掲載されています
- 電話ボックス：チャットに限らず、音声通話もできます！ミーティングしたり、部員とゲームしたり...空いていれば自由に使ってみてください
### 昆布四島
- <#1355413309343531159> <#1355413349860511744> <#1355413420064772249> <#1355413454550208512> ：所属する島ごとのチャンネルです、積極的に使っていこう！
### 学年の集い
特定の学年専用のチャンネルです、管理者は閲覧できますが基本干渉せずその学年内で自由に使ってもらうことが可能です
### 昆布自治区
-# (過去の自治区の活動はアーカイブに保存されています)
現在アクティブな自治区はありませんが、昆布四島を跨いだ活動や、昆布四島の域を脱しているイレギュラーな活動ができます！「掲示板」チャンネルで設立したり募集してみよう！！"""


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


# ---- 活動日スケジュール自動投稿まわり ----
# 「休み」に指定した日付(date型)とスレッド延命対象のスレッドIDは、
# SQLiteデータベース(DB_PATH)に保存する。Volumeをマウントしていれば
# 再デプロイ・再起動をまたいで内容が保持される。


def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS skipped_dates (iso_date TEXT PRIMARY KEY)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS saved_threads (thread_id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    finally:
        conn.close()


def load_skipped_dates() -> set[date]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT iso_date FROM skipped_dates").fetchall()
        return {date.fromisoformat(row[0]) for row in rows}
    finally:
        conn.close()


def load_saved_thread_ids() -> set[int]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT thread_id FROM saved_threads").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def db_add_skipped_date(d: date) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO skipped_dates (iso_date) VALUES (?)", (d.isoformat(),)
        )
        conn.commit()
    finally:
        conn.close()


def db_remove_skipped_date(d: date) -> None:
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM skipped_dates WHERE iso_date = ?", (d.isoformat(),))
        conn.commit()
    finally:
        conn.close()


def db_add_saved_thread(thread_id: int) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO saved_threads (thread_id) VALUES (?)", (thread_id,)
        )
        conn.commit()
    finally:
        conn.close()


def db_remove_saved_thread(thread_id: int) -> None:
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM saved_threads WHERE thread_id = ?", (thread_id,))
        conn.commit()
    finally:
        conn.close()


# 起動時にDBを準備し、内容をメモリ上のキャッシュ(set)に読み込む。
# 以降、add/removeのたびにメモリとDBの両方を更新する。
init_db()
skipped_dates: set[date] = load_skipped_dates()
saved_thread_ids: set[int] = load_saved_thread_ids()


def is_officer(member: discord.Member) -> bool:
    """OFFICER_ROLE_NAMESに指定したロールのいずれかを持っているかを判定する。"""
    member_role_names = {role.name for role in member.roles}
    return any(name in member_role_names for name in OFFICER_ROLE_NAMES)


def parse_date_input(date_str: str, today: date) -> date | None:
    """「9/22」「9月22日」「2026-09-22」などの入力を date に変換する。
    年を省略した場合は今日以降で一番近い年を採用する。
    """
    date_str = date_str.strip()
    formats_without_year = ["%m/%d", "%m月%d日"]
    formats_with_year = ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]

    for fmt in formats_with_year:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    for fmt in formats_without_year:
        try:
            parsed = datetime.strptime(date_str, fmt)
            candidate = date(today.year, parsed.month, parsed.day)
            if candidate < today:
                candidate = date(today.year + 1, parsed.month, parsed.day)
            return candidate
        except ValueError:
            continue

    return None


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


@tasks.loop(time=SCHEDULE_POST_TIME)
async def schedule_announcer():
    """毎日SCHEDULE_POST_TIMEに実行し、翌日が活動日(火・金)かつskipped_datesに
    含まれていなければ「お知らせ」チャンネルに投稿する。
    """
    today = datetime.now(JST).date()
    tomorrow = today + timedelta(days=1)

    if tomorrow.weekday() not in ACTIVITY_WEEKDAYS:
        return
    if tomorrow in skipped_dates:
        print(f"[活動日案内] {tomorrow} はスキップ登録されているため投稿しません。")
        return

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        print(f"[エラー] お知らせチャンネル {ANNOUNCEMENT_CHANNEL_ID} が見つかりません。")
        return
    await channel.send("**明日は活動日です！！**")


@schedule_announcer.before_loop
async def before_schedule_announcer():
    await bot.wait_until_ready()


@tasks.loop(hours=THREAD_CHECK_INTERVAL_HOURS)
async def thread_keepalive_loop():
    """/save で登録されたスレッドを定期チェックし、
    最終投稿からTHREAD_BUMP_AFTER_DAYS日経過していたら延命メッセージを送って即削除する。
    すでにアーカイブされてしまっていた場合はアーカイブ解除も行う。
    """
    now_utc = datetime.now(timezone.utc)
    for thread_id in list(saved_thread_ids):
        thread = bot.get_channel(thread_id)
        if thread is None:
            try:
                thread = await bot.fetch_channel(thread_id)
            except (discord.NotFound, discord.Forbidden):
                print(f"[スレッド延命] {thread_id} が見つからないため登録を解除します。")
                saved_thread_ids.discard(thread_id)
                db_remove_saved_thread(thread_id)
                continue

        if not isinstance(thread, discord.Thread):
            saved_thread_ids.discard(thread_id)
            db_remove_saved_thread(thread_id)
            continue

        try:
            if thread.archived:
                await thread.edit(archived=False)

            last_id = thread.last_message_id or thread.id
            last_time = discord.utils.snowflake_time(last_id)
            elapsed = now_utc - last_time

            if elapsed >= timedelta(days=THREAD_BUMP_AFTER_DAYS):
                bump = await thread.send("🔖")
                await bump.delete()
        except discord.Forbidden:
            print(f"[スレッド延命エラー] {thread_id} で権限不足。Botの権限(スレッドの管理)を確認してください。")
        except Exception as e:
            print(f"[スレッド延命エラー] {thread_id}: {e}")


@thread_keepalive_loop.before_loop
async def before_thread_keepalive_loop():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Bot起動: {bot.user}")
    if not daily_countdown.is_running():
        daily_countdown.start()
    if not schedule_announcer.is_running():
        schedule_announcer.start()
    if not thread_keepalive_loop.is_running():
        thread_keepalive_loop.start()
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを{len(synced)}件同期しました")
    except Exception as e:
        print(f"[スラッシュコマンド同期エラー] {e}")


@bot.tree.command(name="greeting", description="サーバーの挨拶・ルール説明を表示します")
async def greeting_slash(interaction: discord.Interaction):
    await interaction.response.send_message(GREETING_TEXT)


@bot.tree.command(name="skip", description="【管理者専用】指定した日の活動日案内をスキップする")
async def skip_slash(interaction: discord.Interaction, 日付: str):
    if not is_officer(interaction.user):
        await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
        return

    today = datetime.now(JST).date()
    parsed = parse_date_input(日付, today)
    if parsed is None:
        await interaction.response.send_message(
            "日付の形式が認識できませんでした。例：`9/22` や `2026-09-22`",
            ephemeral=True,
        )
        return

    skipped_dates.add(parsed)
    db_add_skipped_date(parsed)
    await interaction.response.send_message(f"{parsed.strftime('%Y年%m月%d日')} の活動日案内をスキップに設定しました。", ephemeral=True)


@bot.tree.command(name="unskip", description="【管理者専用】スキップ設定を解除する")
async def unskip_slash(interaction: discord.Interaction, 日付: str):
    if not is_officer(interaction.user):
        await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
        return

    today = datetime.now(JST).date()
    parsed = parse_date_input(日付, today)
    if parsed is None:
        await interaction.response.send_message(
            "日付の形式が認識できませんでした。例：`9/22` や `2026-09-22`",
            ephemeral=True,
        )
        return

    if parsed in skipped_dates:
        skipped_dates.discard(parsed)
        db_remove_skipped_date(parsed)
        await interaction.response.send_message(f"{parsed.strftime('%Y年%m月%d日')} のスキップ設定を解除しました。", ephemeral=True)
    else:
        await interaction.response.send_message(f"{parsed.strftime('%Y年%m月%d日')} はスキップ登録されていません。", ephemeral=True)


@bot.tree.command(name="skipped", description="現在スキップ登録されている日付の一覧を表示する")
async def skipped_slash(interaction: discord.Interaction):
    if not skipped_dates:
        await interaction.response.send_message("現在スキップ登録されている日付はありません。", ephemeral=True)
        return
    lines = "\n".join(f"・{d.strftime('%Y年%m月%d日')}" for d in sorted(skipped_dates))
    await interaction.response.send_message(f"スキップ登録されている日付：\n{lines}", ephemeral=True)


@bot.tree.command(name="save", description="このスレッドが自動アーカイブされないよう延命登録する")
async def save_slash(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("このコマンドはスレッドの中でのみ使用できます。", ephemeral=True)
        return

    saved_thread_ids.add(interaction.channel.id)
    db_add_saved_thread(interaction.channel.id)
    await interaction.response.send_message("このスレッドを延命登録しました。表示され続けるよう自動でケアします。", ephemeral=True)


@bot.tree.command(name="unsave", description="このスレッドの延命登録を解除する")
async def unsave_slash(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("このコマンドはスレッドの中でのみ使用できます。", ephemeral=True)
        return

    if interaction.channel.id in saved_thread_ids:
        saved_thread_ids.discard(interaction.channel.id)
        db_remove_saved_thread(interaction.channel.id)
        await interaction.response.send_message("このスレッドの延命登録を解除しました。", ephemeral=True)
    else:
        await interaction.response.send_message("このスレッドは延命登録されていません。", ephemeral=True)


ROLE_CHOICES = [
    discord.app_commands.Choice(name=name, value=name) for name in ASSIGNABLE_ROLES
]


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


role_app_group = discord.app_commands.Group(name="role", description="自分のロールを付け外しする")


@role_app_group.command(name="list", description="付け外しできるロール一覧を表示")
async def role_list_slash(interaction: discord.Interaction):
    lines = "\n".join(f"・{name}" for name in ASSIGNABLE_ROLES)
    await interaction.response.send_message(f"付け外しできるロール一覧：\n{lines}", ephemeral=True)


@role_app_group.command(name="add", description="ロールを自分に付ける")
@discord.app_commands.choices(role_name=ROLE_CHOICES)
async def role_add_slash(interaction: discord.Interaction, role_name: discord.app_commands.Choice[str]):
    role = find_assignable_role(interaction.guild, role_name.value)
    if role is None:
        await interaction.response.send_message(
            f"「{role_name.value}」は付け外し可能なロールに含まれていません。`/role list` で一覧を確認してください。",
            ephemeral=True,
        )
        return

    if role in interaction.user.roles:
        await interaction.response.send_message(f"すでに「{role.name}」を持っています。", ephemeral=True)
        return

    try:
        await interaction.user.add_roles(role, reason="セルフロール機能による自己申請")
        await interaction.response.send_message(f"「{role.name}」を付けました。", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "権限が足りずロールを付けられませんでした。"
            "サーバー管理者に「Botのロール順位」と「Manage Roles権限」を確認してもらってください。",
            ephemeral=True,
        )


@role_app_group.command(name="remove", description="ロールを自分から外す")
@discord.app_commands.choices(role_name=ROLE_CHOICES)
async def role_remove_slash(interaction: discord.Interaction, role_name: discord.app_commands.Choice[str]):
    role = find_assignable_role(interaction.guild, role_name.value)
    if role is None:
        await interaction.response.send_message(
            f"「{role_name.value}」は付け外し可能なロールに含まれていません。`/role list` で一覧を確認してください。",
            ephemeral=True,
        )
        return

    if role not in interaction.user.roles:
        await interaction.response.send_message(f"「{role.name}」は付いていません。", ephemeral=True)
        return

    try:
        await interaction.user.remove_roles(role, reason="セルフロール機能による自己申請")
        await interaction.response.send_message(f"「{role.name}」を外しました。", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "権限が足りずロールを外せませんでした。"
            "サーバー管理者に「Botのロール順位」と「Manage Roles権限」を確認してもらってください。",
            ephemeral=True,
        )


bot.tree.add_command(role_app_group)


SKILLS_TEXT = """## このBotで使えるコマンド一覧

**カウントダウン**
`!countdown` : 「文化祭まであと○○日」を今すぐ投稿する

**活動日スケジュール**
`火・金の前日18:00に自動投稿されます`
`/skip 日付` : 【管理者専用】指定日の活動日案内をスキップする(例: /skip 9/22)
`/unskip 日付` : 【管理者専用】スキップ設定を解除する
`/skipped` : 現在スキップ登録されている日付一覧を見る

**スレッド延命**
`/save` : そのスレッド内で実行すると、自動アーカイブされないよう延命登録する
`/unsave` : 延命登録を解除する

**挨拶**
`/greeting` : サーバーの挨拶・ルール説明を表示する

**ロール(自分で付け外し)**
`/role list` : 付け外しできるロール一覧を表示
`/role add` : ロールを自分に付ける(選択肢から選べます)
`/role remove` : ロールを自分から外す(選択肢から選べます)
`!role list` / `!role add ロール名` / `!role remove ロール名` : 上と同じことを!コマンドでもできます

**このコマンド一覧**
`/skills` : このメッセージを表示する"""


@bot.tree.command(name="skills", description="このBotで使えるコマンドの一覧を表示します")
async def skills_slash(interaction: discord.Interaction):
    await interaction.response.send_message(SKILLS_TEXT, ephemeral=True)


# 動作確認用: 手動でカウントダウンを投稿させたいときに使うコマンド
@bot.command(name="countdown")
async def countdown_now(ctx):
    await ctx.send(build_message())


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
