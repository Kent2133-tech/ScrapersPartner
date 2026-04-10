"""
⛏ SCRAPERS BOT — Telegram Bot untuk Tambang Pasir
v3 — Input data ke Supabase + AI analisis + Catatan mandor
"""

import os, logging, asyncio, json, re
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import httpx
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
from anthropic import Anthropic

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger("scrapers-bot")

# ── CONFIG ──────────────────────────────────────────────────────
BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
SUPA_URL      = os.getenv("SUPABASE_URL", "https://tqmqdrifrbvupkrufecc.supabase.co")
SUPA_KEY      = os.getenv("SUPABASE_KEY", "sb_publishable_bQTJDIyQYhx6P3Wljt82JA_gJmnFud1")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

_raw_owners  = os.getenv("OWNER_CHAT_ID", "")
OWNER_CHATS  = set(int(x.strip()) for x in _raw_owners.split(",") if x.strip())
_raw_ops     = os.getenv("OPERATOR_IDS", "")
OPERATOR_IDS = set(int(x.strip()) for x in _raw_ops.split(",") if x.strip())

HEADERS = {
    "apikey": SUPA_KEY,
    "Authorization": f"Bearer {SUPA_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# Conversation states
(ASK_UNIT, ASK_SOLAR_L, ASK_SOLAR_HARGA,
 ASK_SVC_UNIT, ASK_SVC_JENIS, ASK_SVC_BIAYA,
 ASK_NOTE_DATE, ASK_NOTE_CONTENT) = range(8)

# ── SUPABASE ─────────────────────────────────────────────────────
async def supa_get(table: str, params: str = "") -> list:
    url = f"{SUPA_URL}/rest/v1/{table}?{params}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers=HEADERS)
            data = r.json()
            if r.status_code == 200 and isinstance(data, list):
                return data
            log.warning(f"supa_get {table} {r.status_code}: {str(data)[:100]}")
            return []
    except Exception as e:
        log.error(f"supa_get error {table}: {e}")
        return []

async def supa_post(table: str, data: dict) -> dict | None:
    url = f"{SUPA_URL}/rest/v1/{table}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, headers=HEADERS, json=data)
            if r.status_code in [200, 201]:
                result = r.json()
                return result[0] if isinstance(result, list) else result
            log.warning(f"supa_post {table} {r.status_code}: {r.text[:100]}")
            return None
    except Exception as e:
        log.error(f"supa_post error {table}: {e}")
        return None

async def supa_patch(table: str, match: str, data: dict) -> bool:
    url = f"{SUPA_URL}/rest/v1/{table}?{match}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.patch(url, headers=HEADERS, json=data)
            return r.status_code in [200, 204]
    except Exception as e:
        log.error(f"supa_patch error: {e}")
        return False

# ── HELPERS ──────────────────────────────────────────────────────
def rp(n) -> str:
    try: return f"Rp {int(n):,}".replace(",", ".")
    except: return "Rp 0"

def today_str() -> str:
    return date.today().strftime("%d %B %Y")

def today_iso() -> str:
    return date.today().isoformat()

def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def is_owner(uid: int) -> bool:
    return uid in OWNER_CHATS

def is_authorized(uid: int) -> bool:
    return uid in OWNER_CHATS or uid in OPERATOR_IDS

async def notify_owners(bot, sender_uid: int, text: str):
    for oc in OWNER_CHATS:
        if oc != sender_uid:
            try:
                await bot.send_message(oc, text, parse_mode="Markdown")
            except Exception as e:
                log.warning(f"Gagal notif owner {oc}: {e}")

def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Laporan Hari Ini"), KeyboardButton("🔔 Cek Maintenance")],
        [KeyboardButton("💰 Ringkasan Biaya"),  KeyboardButton("🚛 Status Unit")],
        [KeyboardButton("📦 Cek Stok Spare"),   KeyboardButton("🤖 Tanya AI")],
        [KeyboardButton("⛽ Input Solar"),       KeyboardButton("🔧 Input Service")],
        [KeyboardButton("📒 Catat Harian"),      KeyboardButton("📈 Analisis Cepat")],
    ], resize_keyboard=True)

def operator_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("⛽ Input Solar"),      KeyboardButton("🔧 Input Service")],
        [KeyboardButton("📦 Input Spare Part"), KeyboardButton("📒 Catat Harian")],
        [KeyboardButton("📊 Laporan Hari Ini")],
    ], resize_keyboard=True)

# ── LAPORAN BUILDER ──────────────────────────────────────────────
async def build_daily_report() -> str:
    today = today_iso()
    units    = await supa_get("units", "select=id,name,status")
    solar    = await supa_get("solar_logs",   f"select=*&date=eq.{today}")
    services = await supa_get("service_logs", f"select=*&date=eq.{today}")
    spares   = await supa_get("spare_stock",  "select=*&qty=lt.5")
    notes    = await supa_get("daily_notes",  f"select=*&note_date=eq.{today}")

    total_solar_l  = sum(s.get("liters", 0) or 0 for s in solar)
    total_solar_rp = sum((s.get("liters", 0) or 0) * (s.get("price_per_liter", 0) or 0) for s in solar)
    total_service  = sum(s.get("cost", 0) or 0 for s in services)
    unit_aktif     = sum(1 for u in units if u.get("status") == "aktif")

    lines = [
        f"⛏ *LAPORAN HARIAN SCRAPERS*",
        f"📅 {today_str()} · {now_str()}",
        "─" * 28,
        f"",
        f"🚛 *UNIT:* `{unit_aktif}/{len(units)}` aktif",
        f"",
        f"⛽ *SOLAR:* `{total_solar_l:,.0f} L` = `{rp(total_solar_rp)}`",
        f"🔧 *SERVICE:* `{len(services)} kegiatan` = `{rp(total_service)}`",
        f"",
    ]

    if notes:
        lines.append("📒 *CATATAN HARI INI:*")
        for n in notes[:2]:
            preview = (n.get("content","") or "")[:100]
            lines.append(f"  _{preview}..._")
        lines.append("")

    if spares:
        lines.append("⚠️ *STOK MENIPIS:*")
        for s in spares[:4]:
            lines.append(f"  • {s.get('name','?')}: `{s.get('qty',0)}`")
        lines.append("")

    total = total_solar_rp + total_service
    lines += [
        f"💰 *TOTAL BIAYA: `{rp(total)}`*",
        "─" * 28,
        f"_Scrapers Bot · {now_str()}_"
    ]
    return "\n".join(lines)

async def build_maintenance_alerts() -> str:
    units = await supa_get("units", "select=id,name,total_hours,last_service_hours,maintenance_intervals")
    alerts = []
    for u in units:
        total_h = u.get("total_hours", 0) or 0
        last_svc = u.get("last_service_hours", {}) or {}
        intervals = u.get("maintenance_intervals", {"ringan": 250, "sedang": 1000, "besar": 2000}) or {}
        for mt, interval in intervals.items():
            last = last_svc.get(mt, 0) or 0
            sisa = (last + interval) - total_h
            if sisa <= 0:
                alerts.append(f"🔴 *{u['name']}* — {mt} OVERDUE ({abs(int(sisa))}h lewat)")
            elif sisa <= 50:
                alerts.append(f"⚠️ *{u['name']}* — {mt} sisa `{int(sisa)}h`")
    return "\n".join(alerts) if alerts else "✅ Semua unit kondisi baik"

# ── COMMANDS ─────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name
    if not is_authorized(uid):
        await update.message.reply_text(
            f"🚫 Akses ditolak.\nChat ID kamu: `{uid}`\nHubungi owner untuk didaftarkan.",
            parse_mode="Markdown"
        )
        return
    role   = "👑 Owner" if is_owner(uid) else "👷 Operator"
    markup = owner_keyboard() if is_owner(uid) else operator_keyboard()
    await update.message.reply_text(
        f"⛏ *Selamat datang, {name}!*\n"
        f"Role: {role}\n\n"
        f"Pilih menu atau ketik perintah 👇",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def cmd_laporan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id): return
    msg = await update.message.reply_text("⏳ Mengambil data...")
    report = await build_daily_report()
    await msg.edit_text(report, parse_mode="Markdown")

async def cmd_maintenance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Hanya untuk owner.")
        return
    msg    = await update.message.reply_text("⏳ Cek maintenance...")
    alerts = await build_maintenance_alerts()
    await msg.edit_text(f"🔧 *STATUS MAINTENANCE*\n📅 {today_str()}\n\n{alerts}", parse_mode="Markdown")

async def cmd_units(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id): return
    units = await supa_get("units", "select=*&order=name")
    if not units:
        await update.message.reply_text("🚛 Belum ada unit terdaftar.")
        return
    lines = ["🚛 *STATUS UNIT*\n"]
    for u in units:
        status = u.get("status", "unknown")
        icon   = {"aktif": "🟢", "rusak": "🔴", "maintenance": "🟡"}.get(status, "⚪")
        lines.append(f"{icon} *{u.get('name','?')}* — `{u.get('total_hours',0):,}h` — `{status}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_stok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id): return
    stok = await supa_get("spare_stock", "select=*&order=qty.asc&limit=20")
    if not stok:
        await update.message.reply_text("📦 Belum ada data stok spare part.")
        return
    lines = ["📦 *STOK SPARE PART*\n"]
    for s in stok:
        qty  = s.get("qty", 0) or 0
        icon = "🔴" if qty < 3 else "⚠️" if qty < 5 else "✅"
        lines.append(f"{icon} {s.get('name','?')}: `{qty} {s.get('unit','pcs')}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_biaya(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Hanya untuk owner.")
        return
    today  = today_iso()
    solar  = await supa_get("solar_logs",   f"select=*&date=eq.{today}")
    svc    = await supa_get("service_logs", f"select=*&date=eq.{today}")
    costs  = await supa_get("cost_logs",    f"select=*&date=eq.{today}")

    t_solar = sum((s.get("liters",0) or 0) * (s.get("price_per_liter",0) or 0) for s in solar)
    t_svc   = sum(s.get("cost",0) or 0 for s in svc)
    t_lain  = sum(c.get("amount",0) or 0 for c in costs)
    total   = t_solar + t_svc + t_lain

    await update.message.reply_text(
        f"💰 *BIAYA HARI INI*\n📅 {today_str()}\n\n"
        f"⛽ Solar:    `{rp(t_solar)}`\n"
        f"🔧 Service:  `{rp(t_svc)}`\n"
        f"📋 Lainnya:  `{rp(t_lain)}`\n"
        f"─────────────────\n"
        f"💵 *TOTAL: `{rp(total)}`*",
        parse_mode="Markdown"
    )

# ── ANALISIS CEPAT ────────────────────────────────────────────────
async def cmd_analisis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Hanya untuk owner.")
        return
    msg = await update.message.reply_text("📈 Menganalisis data 7 hari terakhir...")

    # Ambil data 7 hari
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    solar    = await supa_get("solar_logs",   f"select=*&date=gte.{week_ago}")
    services = await supa_get("service_logs", f"select=*&date=gte.{week_ago}")
    units    = await supa_get("units",        "select=*")

    total_solar_l  = sum(s.get("liters", 0) or 0 for s in solar)
    total_solar_rp = sum((s.get("liters", 0) or 0) * (s.get("price_per_liter", 0) or 0) for s in solar)
    total_svc_rp   = sum(s.get("cost", 0) or 0 for s in services)
    total_biaya    = total_solar_rp + total_svc_rp
    avg_harian     = total_biaya / 7 if total_biaya else 0

    # Unit paling banyak service
    svc_count = {}
    for s in services:
        uid = s.get("unit_id", "unknown")
        svc_count[uid] = svc_count.get(uid, 0) + 1
    most_svc_uid = max(svc_count, key=svc_count.get) if svc_count else None
    most_svc_name = next((u["name"] for u in units if str(u.get("id")) == str(most_svc_uid)), "?") if most_svc_uid else "-"

    lines = [
        f"📈 *ANALISIS 7 HARI TERAKHIR*",
        f"📅 {(date.today()-timedelta(7)).strftime('%d/%m')} — {date.today().strftime('%d/%m/%Y')}",
        "─" * 28,
        f"",
        f"⛽ Solar: `{total_solar_l:,.0f} L` = `{rp(total_solar_rp)}`",
        f"🔧 Service: `{len(services)}x` = `{rp(total_svc_rp)}`",
        f"",
        f"💰 *Total 7 hari: `{rp(total_biaya)}`*",
        f"📊 Rata-rata/hari: `{rp(avg_harian)}`",
        f"📊 Rata-rata/bulan est.: `{rp(avg_harian * 30)}`",
        f"",
        f"🔧 Unit paling banyak service: *{most_svc_name}* (`{svc_count.get(most_svc_uid,0)}x`)" if most_svc_uid else "",
        f"",
        f"_Data real-time dari Supabase_"
    ]
    await msg.edit_text("\n".join(l for l in lines if l is not None), parse_mode="Markdown")

# ── INPUT SOLAR (Conversation) ────────────────────────────────────
async def solar_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END
    units = await supa_get("units", "select=id,name&order=name")
    if not units:
        await update.message.reply_text("❌ Tidak ada unit terdaftar.")
        return ConversationHandler.END
    ctx.user_data["units"] = units
    buttons = [[InlineKeyboardButton(u["name"], callback_data=f"unit_{u['id']}")] for u in units]
    await update.message.reply_text(
        "⛽ *INPUT SOLAR*\n\nPilih unit:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return ASK_UNIT

async def solar_got_unit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    unit_id = q.data.replace("unit_", "")
    units   = ctx.user_data.get("units", [])
    unit    = next((u for u in units if str(u["id"]) == unit_id), None)
    ctx.user_data["solar_unit_id"]   = unit_id
    ctx.user_data["solar_unit_name"] = unit["name"] if unit else "?"
    await q.edit_message_text(
        f"✅ Unit: *{ctx.user_data['solar_unit_name']}*\n\nBerapa liter solar?",
        parse_mode="Markdown"
    )
    return ASK_SOLAR_L

async def solar_got_liter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        liter = float(update.message.text.replace(",", "."))
        ctx.user_data["solar_liter"] = liter
        await update.message.reply_text(
            f"✅ {liter:,.0f} liter\n\nHarga per liter? (ketik angka atau /skip pakai Rp 10.000)"
        )
        return ASK_SOLAR_HARGA
    except:
        await update.message.reply_text("❌ Masukkan angka. Contoh: 150")
        return ASK_SOLAR_L

async def solar_got_harga(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.replace(".", "").replace(",", "").replace("rp","").replace("Rp","").strip()
        harga = float(text)
    except:
        harga = 10000
    await _save_solar(update, ctx, harga)
    return ConversationHandler.END

async def solar_skip_harga(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _save_solar(update, ctx, 10000)
    return ConversationHandler.END

async def _save_solar(update: Update, ctx: ContextTypes.DEFAULT_TYPE, harga: float):
    liter = ctx.user_data.get("solar_liter", 0)
    result = await supa_post("solar_logs", {
        "unit_id":         ctx.user_data.get("solar_unit_id"),
        "liters":          liter,
        "price_per_liter": harga,
        "operator_name":   update.effective_user.first_name,
        "date":            today_iso(),
        "created_at":      datetime.now().isoformat(),
        "synced":          1,
    })
    total = liter * harga
    status = "✅ Tersimpan!" if result else "⚠️ Gagal simpan ke cloud"
    await update.message.reply_text(
        f"{status}\n\n"
        f"⛽ *Solar dicatat*\n"
        f"🚛 Unit: {ctx.user_data.get('solar_unit_name')}\n"
        f"💧 Liter: `{liter:,.0f} L`\n"
        f"💵 Harga: `{rp(harga)}/L`\n"
        f"💰 Total: `{rp(total)}`",
        parse_mode="Markdown"
    )
    await notify_owners(
        ctx.bot, update.effective_user.id,
        f"🔔 *Solar Input*\nOleh: {update.effective_user.first_name}\n"
        f"Unit: {ctx.user_data.get('solar_unit_name')}\n"
        f"Solar: {liter:,.0f}L = {rp(total)}"
    )

# ── INPUT SERVICE (Conversation) ──────────────────────────────────
async def service_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END
    units = await supa_get("units", "select=id,name&order=name")
    ctx.user_data["units"] = units
    buttons = [[InlineKeyboardButton(u["name"], callback_data=f"svc_{u['id']}")] for u in units]
    await update.message.reply_text(
        "🔧 *INPUT SERVICE*\n\nPilih unit:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return ASK_SVC_UNIT

async def svc_got_unit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    unit_id = q.data.replace("svc_", "")
    units   = ctx.user_data.get("units", [])
    unit    = next((u for u in units if str(u["id"]) == unit_id), None)
    ctx.user_data["svc_unit_id"]   = unit_id
    ctx.user_data["svc_unit_name"] = unit["name"] if unit else "?"
    buttons = [
        [InlineKeyboardButton("Ringan (250h)",  callback_data="jenis_ringan")],
        [InlineKeyboardButton("Sedang (1000h)", callback_data="jenis_sedang")],
        [InlineKeyboardButton("Besar (2000h)",  callback_data="jenis_besar")],
        [InlineKeyboardButton("Overhaul",       callback_data="jenis_overhaul")],
        [InlineKeyboardButton("Perbaikan",      callback_data="jenis_perbaikan")],
    ]
    await q.edit_message_text(
        f"✅ Unit: *{ctx.user_data['svc_unit_name']}*\n\nJenis service:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return ASK_SVC_JENIS

async def svc_got_jenis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    jenis_map = {"ringan":"Ringan","sedang":"Sedang","besar":"Besar","overhaul":"Overhaul","perbaikan":"Perbaikan"}
    jenis = q.data.replace("jenis_", "")
    ctx.user_data["svc_jenis"] = jenis_map.get(jenis, jenis)
    await q.edit_message_text(
        f"✅ Jenis: *{ctx.user_data['svc_jenis']}*\n\nTotal biaya service? (Rp)\nKetik 0 kalau belum ada biaya.",
        parse_mode="Markdown"
    )
    return ASK_SVC_BIAYA

async def svc_got_biaya(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        biaya = float(update.message.text.replace(".", "").replace(",","").replace("rp","").replace("Rp","").strip())
    except:
        await update.message.reply_text("❌ Format salah. Contoh: 500000 atau 0")
        return ASK_SVC_BIAYA

    result = await supa_post("service_logs", {
        "unit_id":         ctx.user_data.get("svc_unit_id"),
        "maintenance_type": ctx.user_data.get("svc_jenis", "").lower(),
        "cost":            biaya,
        "operator_name":   update.effective_user.first_name,
        "date":            today_iso(),
        "created_at":      datetime.now().isoformat(),
        "synced":          1,
    })
    status = "✅ Tersimpan!" if result else "⚠️ Gagal simpan ke cloud"
    await update.message.reply_text(
        f"{status}\n\n"
        f"🔧 *Service dicatat*\n"
        f"🚛 Unit: {ctx.user_data.get('svc_unit_name')}\n"
        f"⚙️ Jenis: {ctx.user_data.get('svc_jenis')}\n"
        f"💰 Biaya: `{rp(biaya)}`",
        parse_mode="Markdown"
    )
    await notify_owners(
        ctx.bot, update.effective_user.id,
        f"🔔 *Service Input*\nOleh: {update.effective_user.first_name}\n"
        f"Unit: {ctx.user_data.get('svc_unit_name')}\n"
        f"Jenis: {ctx.user_data.get('svc_jenis')} · Biaya: {rp(biaya)}"
    )
    return ConversationHandler.END

# ── CATATAN HARIAN (Conversation) ─────────────────────────────────
async def note_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        f"📒 *CATATAN HARIAN*\n\n"
        f"Untuk tanggal berapa? (format: YYYY-MM-DD)\n"
        f"Contoh: `{today_iso()}`\n\n"
        f"Atau ketik /skip untuk pakai tanggal hari ini.",
        parse_mode="Markdown"
    )
    return ASK_NOTE_DATE

async def note_got_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # Validate date format
    try:
        datetime.strptime(text, "%Y-%m-%d")
        ctx.user_data["note_date"] = text
    except:
        await update.message.reply_text("❌ Format salah. Gunakan YYYY-MM-DD, contoh: 2025-04-15")
        return ASK_NOTE_DATE
    await update.message.reply_text(
        f"✅ Tanggal: `{ctx.user_data['note_date']}`\n\n"
        f"Sekarang tulis catatan kamu — bebas, sepanjang apapun.\n"
        f"Tulis semua pemasukan, pengeluaran, kejadian hari ini:",
        parse_mode="Markdown"
    )
    return ASK_NOTE_CONTENT

async def note_skip_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["note_date"] = today_iso()
    await update.message.reply_text(
        f"✅ Pakai tanggal hari ini: `{today_iso()}`\n\n"
        f"Tulis catatan kamu — bebas, sepanjang apapun:",
        parse_mode="Markdown"
    )
    return ASK_NOTE_CONTENT

async def note_got_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    content = update.message.text.strip()
    note_date = ctx.user_data.get("note_date", today_iso())
    author    = update.effective_user.first_name

    result = await supa_post("daily_notes", {
        "note_date":   note_date,
        "content":     content,
        "author_name": author,
        "created_at":  datetime.now().isoformat(),
        "synced":      1,
    })
    status = "✅ Catatan tersimpan!" if result else "⚠️ Gagal simpan ke cloud"
    preview = content[:150] + "..." if len(content) > 150 else content

    await update.message.reply_text(
        f"{status}\n\n"
        f"📒 *Catatan {note_date}*\n"
        f"✍️ Oleh: {author}\n\n"
        f"_{preview}_",
        parse_mode="Markdown"
    )
    await notify_owners(
        ctx.bot, update.effective_user.id,
        f"📒 *Catatan Harian Baru*\n"
        f"Tanggal: {note_date}\n"
        f"Oleh: {author}\n"
        f"_{preview}_"
    )
    return ConversationHandler.END

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Dibatalkan.")
    return ConversationHandler.END

# ── AI CHAT ──────────────────────────────────────────────────────
async def cmd_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Hanya untuk owner.")
        return
    await update.message.reply_text(
        "🤖 *Mode Tanya AI aktif!*\n\n"
        "Tanya apapun tentang tambang:\n"
        "• _Berapa total solar minggu ini?_\n"
        "• _Unit mana paling boros?_\n"
        "• _Analisis biaya bulan ini_\n\n"
        "Ketik /done untuk keluar.",
        parse_mode="Markdown"
    )
    ctx.user_data["ai_mode"] = True

async def handle_ai_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    if not ctx.user_data.get("ai_mode"): return
    if not ANTHROPIC_KEY:
        await update.message.reply_text("⚠️ API key AI belum dikonfigurasi.")
        return

    question = update.message.text
    msg = await update.message.reply_text("🤖 Menganalisa...")

    # Ambil data konteks
    units    = await supa_get("units",        "select=*")
    solar    = await supa_get("solar_logs",   "select=*&order=date.desc&limit=50")
    service  = await supa_get("service_logs", "select=*&order=date.desc&limit=50")
    stok     = await supa_get("spare_stock",  "select=*")
    notes    = await supa_get("daily_notes",  "select=*&order=note_date.desc&limit=20")

    context = f"""Kamu adalah asisten operasional tambang pasir SCRAPERS.
Data real-time:
UNITS: {json.dumps(units, ensure_ascii=False)}
SOLAR (50 terbaru): {json.dumps(solar, ensure_ascii=False)}
SERVICE (50 terbaru): {json.dumps(service, ensure_ascii=False)}
SPARE STOCK: {json.dumps(stok, ensure_ascii=False)}
CATATAN HARIAN (20 terbaru): {json.dumps(notes, ensure_ascii=False)}

Jawab dalam Bahasa Indonesia, ringkas, format Telegram-friendly.
Berikan insight actionable kalau relevan."""

    client   = Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=context,
        messages=[{"role": "user", "content": question}]
    )
    await msg.edit_text(f"🤖 *AI:*\n\n{response.content[0].text}", parse_mode="Markdown")

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ai_mode"] = False
    await update.message.reply_text("✅ Kembali ke menu.")

# ── MESSAGE ROUTER ────────────────────────────────────────────────
async def route_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id): return
    text = update.message.text or ""

    if ctx.user_data.get("ai_mode") and is_owner(update.effective_user.id):
        await handle_ai_query(update, ctx)
        return

    routes = {
        "📊 Laporan Hari Ini": cmd_laporan,
        "🔔 Cek Maintenance":  cmd_maintenance,
        "💰 Ringkasan Biaya":  cmd_biaya,
        "🚛 Status Unit":      cmd_units,
        "📦 Cek Stok Spare":   cmd_stok,
        "🤖 Tanya AI":         cmd_ai,
        "📈 Analisis Cepat":   cmd_analisis,
    }
    if text in routes:
        await routes[text](update, ctx)

# ── SCHEDULED JOBS ────────────────────────────────────────────────
async def job_daily_report(ctx: ContextTypes.DEFAULT_TYPE):
    if not OWNER_CHATS: return
    report = await build_daily_report()
    for oc in OWNER_CHATS:
        try:
            await ctx.bot.send_message(oc, report, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Gagal kirim laporan ke {oc}: {e}")

async def job_maintenance_check(ctx: ContextTypes.DEFAULT_TYPE):
    if not OWNER_CHATS: return
    alerts = await build_maintenance_alerts()
    if "🔴" in alerts or "⚠️" in alerts:
        for oc in OWNER_CHATS:
            try:
                await ctx.bot.send_message(oc, f"🔔 *MAINTENANCE ALERT*\n\n{alerts}", parse_mode="Markdown")
            except: pass

async def job_stok_check(ctx: ContextTypes.DEFAULT_TYPE):
    if not OWNER_CHATS: return
    spares = await supa_get("spare_stock", "select=*&qty=lt.3")
    if not spares: return
    lines = ["⚠️ *STOK KRITIS*\n"]
    for s in spares:
        lines.append(f"🔴 {s.get('name')}: `{s.get('qty')} {s.get('unit','pcs')}`")
    text = "\n".join(lines)
    for oc in OWNER_CHATS:
        try:
            await ctx.bot.send_message(oc, text, parse_mode="Markdown")
        except: pass

# ── KEEP ALIVE (untuk Render free tier) ──────────────────────────
async def job_keep_alive(ctx: ContextTypes.DEFAULT_TYPE):
    """Ping Supabase tiap 10 menit biar bot tidak tidur di Render"""
    try:
        await supa_get("units", "select=id&limit=1")
        log.info("Keep-alive ping OK")
    except: pass

# ── MAIN ──────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN tidak ada!")

    log.info(f"Owner IDs: {OWNER_CHATS}")
    log.info(f"Operator IDs: {OPERATOR_IDS}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Solar conversation
    solar_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⛽ Input Solar$"), solar_start)],
        states={
            ASK_UNIT:        [CallbackQueryHandler(solar_got_unit,  pattern="^unit_")],
            ASK_SOLAR_L:     [MessageHandler(filters.TEXT & ~filters.COMMAND, solar_got_liter)],
            ASK_SOLAR_HARGA: [
                CommandHandler("skip", solar_skip_harga),
                MessageHandler(filters.TEXT & ~filters.COMMAND, solar_got_harga)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

    # Service conversation
    svc_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔧 Input Service$"), service_start)],
        states={
            ASK_SVC_UNIT:  [CallbackQueryHandler(svc_got_unit,  pattern="^svc_")],
            ASK_SVC_JENIS: [CallbackQueryHandler(svc_got_jenis, pattern="^jenis_")],
            ASK_SVC_BIAYA: [MessageHandler(filters.TEXT & ~filters.COMMAND, svc_got_biaya)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

    # Catatan conversation
    note_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📒 Catat Harian$"), note_start)],
        states={
            ASK_NOTE_DATE: [
                CommandHandler("skip", note_skip_date),
                MessageHandler(filters.TEXT & ~filters.COMMAND, note_got_date)
            ],
            ASK_NOTE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_got_content)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

    # Handlers
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("laporan",     cmd_laporan))
    app.add_handler(CommandHandler("maintenance", cmd_maintenance))
    app.add_handler(CommandHandler("units",       cmd_units))
    app.add_handler(CommandHandler("stok",        cmd_stok))
    app.add_handler(CommandHandler("biaya",       cmd_biaya))
    app.add_handler(CommandHandler("analisis",    cmd_analisis))
    app.add_handler(CommandHandler("ai",          cmd_ai))
    app.add_handler(CommandHandler("done",        cmd_done))
    app.add_handler(solar_conv)
    app.add_handler(svc_conv)
    app.add_handler(note_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_message))

    # Scheduled jobs (UTC — WIB = UTC+7)
    jq = app.job_queue
    jq.run_daily(job_daily_report,      time=__import__("datetime").time(23, 0, 0))  # 06:00 WIB
    jq.run_daily(job_maintenance_check, time=__import__("datetime").time(0,  0, 0))  # 07:00 WIB
    jq.run_daily(job_stok_check,        time=__import__("datetime").time(1,  0, 0))  # 08:00 WIB
    jq.run_repeating(job_keep_alive, interval=600, first=60)  # Tiap 10 menit

    log.info("🤖 SCRAPERS Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
