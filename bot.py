"""
Modüler Telegram Botu
Modüller: Çekiliş, Destek/Bilet, Grup Yönetimi, Aktivite Takibi
Her modül ayrı bölümde, müşteriye göre kolayca açılıp kapatılabilir.
"""
import asyncio
import html
import logging
import os
import random
import re
import sqlite3

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

# ---------------------------------------------------------------- AYARLAR
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "bot.db")
WELCOME_TEXT = os.getenv("WELCOME_TEXT", "Hoş geldin {name}! 👋 Kuralları okumayı unutma.")

# Müşteriye göre modül aç/kapat (.env içinde MODULES=cekilis,destek,grup,aktivite)
MODULES = set(os.getenv("MODULES", "cekilis,destek,grup,aktivite").split(","))

LINK_RE = re.compile(r"(https?://|www\.|t\.me/)", re.I)


# ---------------------------------------------------------------- VERİTABANI
def run(sql, args=(), one=False, all_=False):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, args)
        conn.commit()
        if one:
            return cur.fetchone()
        if all_:
            return cur.fetchall()
        return cur.lastrowid
    finally:
        conn.close()


def init_db():
    run(
        """CREATE TABLE IF NOT EXISTS users(
            chat_id INTEGER, user_id INTEGER, name TEXT, msg_count INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, user_id))"""
    )
    run(
        """CREATE TABLE IF NOT EXISTS giveaways(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, title TEXT,
            winners INTEGER, status TEXT)"""
    )
    run(
        """CREATE TABLE IF NOT EXISTS entries(
            giveaway_id INTEGER, user_id INTEGER, name TEXT,
            PRIMARY KEY(giveaway_id, user_id))"""
    )
    run(
        """CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
            text TEXT, status TEXT DEFAULT 'open')"""
    )
    run("CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER PRIMARY KEY, antilink INTEGER DEFAULT 0)")


# ---------------------------------------------------------------- YARDIMCI
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user, chat = update.effective_user, update.effective_chat
    if user.id in ADMIN_IDS:
        return True
    if chat.type in ("group", "supergroup"):
        member = await chat.get_member(user.id)
        return member.status in ("administrator", "creator")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Merhaba! Komutlar için /yardim yaz.")


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["<b>Komutlar</b>"]
    if "cekilis" in MODULES:
        lines += [
            "/cekilis_baslat &lt;kazanan sayısı&gt; &lt;başlık&gt; (yönetici)",
            "/cekilis_bitir &lt;no&gt; (yönetici)",
        ]
    if "destek" in MODULES:
        lines += [
            "/destek &lt;mesajın&gt; (özelden)",
            "/talepler, /yanit &lt;no&gt; &lt;mesaj&gt;, /kapat &lt;no&gt; (bot sahibi)",
        ]
    if "grup" in MODULES:
        lines += [
            "/ban, /at (bir mesaja yanıt vererek, yönetici)",
            "/linkengel ac|kapat (yönetici)",
        ]
    if "aktivite" in MODULES:
        lines += ["/top (en aktif 10 üye)", "/istatistik"]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------- MODÜL: ÇEKİLİŞ
async def cekilis_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /cekilis_baslat 3 Büyük Çekiliş")
        return
    winners = int(context.args[0])
    title = " ".join(context.args[1:]) or "Çekiliş"
    gid = run(
        "INSERT INTO giveaways(chat_id,title,winners,status) VALUES(?,?,?,'open')",
        (update.effective_chat.id, title, winners),
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Katıl", callback_data=f"join:{gid}")]])
    await update.message.reply_text(
        f"🎁 {title}\nKazanan sayısı: {winners}\nÇekiliş no: {gid}", reply_markup=kb
    )


async def cekilis_katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    gid = int(q.data.split(":")[1])
    g = run("SELECT * FROM giveaways WHERE id=?", (gid,), one=True)
    if not g or g["status"] != "open":
        await q.answer("Bu çekiliş kapandı.", show_alert=True)
        return
    u = q.from_user
    try:
        run("INSERT INTO entries VALUES(?,?,?)", (gid, u.id, u.full_name))
        await q.answer("Katıldın! 🍀")
    except sqlite3.IntegrityError:
        await q.answer("Zaten katıldın.")


async def cekilis_bitir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /cekilis_bitir <no>")
        return
    gid = int(context.args[0])
    g = run("SELECT * FROM giveaways WHERE id=?", (gid,), one=True)
    if not g or g["status"] != "open":
        await update.message.reply_text("Çekiliş bulunamadı veya zaten bitti.")
        return
    entries = run("SELECT * FROM entries WHERE giveaway_id=?", (gid,), all_=True)
    if not entries:
        await update.message.reply_text("Katılımcı yok.")
        return
    picked = random.sample(entries, min(g["winners"], len(entries)))
    run("UPDATE giveaways SET status='closed' WHERE id=?", (gid,))
    lines = [
        f'🏆 <a href="tg://user?id={w["user_id"]}">{html.escape(w["name"])}</a>' for w in picked
    ]
    await update.message.reply_text(
        f"🎉 <b>{html.escape(g['title'])}</b> kazananları:\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------- MODÜL: DESTEK
async def destek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Destek için bana özelden yaz.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Kullanım: /destek sorunun veya talebin")
        return
    u = update.effective_user
    tid = run("INSERT INTO tickets(user_id,name,text) VALUES(?,?,?)", (u.id, u.full_name, text))
    for aid in ADMIN_IDS:
        await context.bot.send_message(
            aid, f"🎫 Yeni talep #{tid}\nKullanıcı: {u.full_name}\n\n{text}\n\nYanıt: /yanit {tid} mesajın"
        )
    await update.message.reply_text(f"Talebin alındı (#{tid}). En kısa sürede dönüş yapılacak.")


async def yanit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /yanit <no> <mesaj>")
        return
    t = run("SELECT * FROM tickets WHERE id=?", (int(context.args[0]),), one=True)
    if not t:
        await update.message.reply_text("Talep bulunamadı.")
        return
    await context.bot.send_message(
        t["user_id"], f"💬 Talep #{t['id']} yanıtı:\n{' '.join(context.args[1:])}"
    )
    await update.message.reply_text("Yanıt gönderildi.")


async def talepler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    rows = run("SELECT * FROM tickets WHERE status='open' ORDER BY id DESC LIMIT 20", all_=True)
    if not rows:
        await update.message.reply_text("Açık talep yok.")
        return
    await update.message.reply_text("\n\n".join(f"#{r['id']} {r['name']}: {r['text'][:100]}" for r in rows))


async def kapat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /kapat <no>")
        return
    run("UPDATE tickets SET status='closed' WHERE id=?", (int(context.args[0]),))
    await update.message.reply_text("Talep kapatıldı.")


# ---------------------------------------------------------------- MODÜL: GRUP
async def hosgeldin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        if not m.is_bot:
            await update.message.reply_text(WELCOME_TEXT.replace("{name}", m.full_name))


async def linkengel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if not context.args or context.args[0] not in ("ac", "kapat"):
        await update.message.reply_text("Kullanım: /linkengel ac veya /linkengel kapat")
        return
    val = 1 if context.args[0] == "ac" else 0
    run(
        "INSERT INTO settings(chat_id,antilink) VALUES(?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET antilink=excluded.antilink",
        (update.effective_chat.id, val),
    )
    await update.message.reply_text("Link engelleme " + ("açıldı ✅" if val else "kapatıldı ❌"))


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    target = update.message.reply_to_message
    if not target:
        await update.message.reply_text("Bir mesaja yanıt vererek kullan.")
        return
    await update.effective_chat.ban_member(target.from_user.id)
    await update.message.reply_text("Kullanıcı banlandı.")


async def at(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    target = update.message.reply_to_message
    if not target:
        await update.message.reply_text("Bir mesaja yanıt vererek kullan.")
        return
    await update.effective_chat.ban_member(target.from_user.id)
    await update.effective_chat.unban_member(target.from_user.id)
    await update.message.reply_text("Kullanıcı gruptan atıldı.")


# ---------------------------------------------------------------- MODÜL: AKTİVİTE
async def grup_mesaji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not msg or not user or user.is_bot:
        return
    if "aktivite" in MODULES:
        run(
            "INSERT INTO users(chat_id,user_id,name,msg_count) VALUES(?,?,?,1) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET msg_count=msg_count+1, name=excluded.name",
            (chat.id, user.id, user.full_name),
        )
    if "grup" in MODULES:
        s = run("SELECT antilink FROM settings WHERE chat_id=?", (chat.id,), one=True)
        if s and s["antilink"] and LINK_RE.search(msg.text or msg.caption or ""):
            if not await is_admin(update, context):
                await msg.delete()
                await chat.send_message(f"{user.full_name}, bu grupta link paylaşımı yasak.")


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = run(
        "SELECT name, msg_count FROM users WHERE chat_id=? ORDER BY msg_count DESC LIMIT 10",
        (update.effective_chat.id,),
        all_=True,
    )
    if not rows:
        await update.message.reply_text("Henüz veri yok.")
        return
    text = "\n".join(f"{i}. {r['name']} — {r['msg_count']} mesaj" for i, r in enumerate(rows, 1))
    await update.message.reply_text("🔥 En aktif üyeler\n" + text)


async def istatistik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = run(
        "SELECT COUNT(*) AS n, COALESCE(SUM(msg_count),0) AS total FROM users WHERE chat_id=?",
        (update.effective_chat.id,),
        one=True,
    )
    await update.message.reply_text(f"👥 Aktif üye: {r['n']}\n💬 Toplam mesaj: {r['total']}")


# ---------------------------------------------------------------- BAŞLAT
def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN bulunamadı. .env dosyasını doldur.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", yardim))

    if "cekilis" in MODULES:
        app.add_handler(CommandHandler("cekilis_baslat", cekilis_baslat))
        app.add_handler(CommandHandler("cekilis_bitir", cekilis_bitir))
        app.add_handler(CallbackQueryHandler(cekilis_katil, pattern=r"^join:"))
    if "destek" in MODULES:
        app.add_handler(CommandHandler("destek", destek))
        app.add_handler(CommandHandler("yanit", yanit))
        app.add_handler(CommandHandler("talepler", talepler))
        app.add_handler(CommandHandler("kapat", kapat))
    if "grup" in MODULES:
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
        app.add_handler(CommandHandler("linkengel", linkengel))
        app.add_handler(CommandHandler("ban", ban))
        app.add_handler(CommandHandler("at", at))
    if "aktivite" in MODULES:
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("istatistik", istatistik))
    if "aktivite" in MODULES or "grup" in MODULES:
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, grup_mesaji))
        
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling()


if __name__ == "__main__":
    main()
