import os, logging, asyncio, json, re
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import httpx
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

# ── CONFIG ──────────────────────────────────────────────────────
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
SUPA_URL       = os.getenv("SUPABASE_URL")
SUPA_KEY       = os.getenv("SUPABASE_KEY")
GEMINI_KEY     = os.getenv("GEMINI_API_KEY")
SHEET_URL      = os.getenv("SPREADSHEET_URL")
GOOGLE_CREDS   = os.getenv("GOOGLE_CREDS")

# Setup Gemini
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# ── HELPER DATA ──────────────────────────────────────────────────
def get_sheets_data():
    try:
        if not GOOGLE_CREDS or not SHEET_URL: return "Data Sheets tdk terpasang."
        creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDS), 
                scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SHEET_URL).sheet1
        return str(sheet.get_all_records()[:50]) # Ambil 50 baris aja biar ga kepenuhan
    except Exception as e:
        return f"Error Sheets: {str(e)}"

async def fetch_supabase(table):
    url = f"{SUPA_URL}/rest/v1/{table}?select=*&limit=10"
    headers = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)
        return r.json() if r.status_code == 200 else []

# ── FUNGSI AI UTAMA ──────────────────────────────────────────────
async def ask_ai(prompt):
    try:
        # Tarik data pendukung buat otak AI
        data_unit = await fetch_supabase("units")
        data_keuangan = get_sheets_data()
        
        full_prompt = f"""
        Lo adalah asisten tambang pasir SCRAPERS. Jawab pake bahasa santai lo-gue.
        
        DATA OPERASIONAL: {data_unit}
        DATA KEUANGAN SHEETS: {data_keuangan}
        
        PERTANYAAN BOS: {prompt}
        """
        
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Waduh bos, AI-nya pusing: {str(e)}"

# ── HANDLER TELEGRAM ─────────────────────────────────────────────
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)
    if not question:
        await update.message.reply_text("Mau nanya apa bos? Contoh: /ai gimana stok solar?")
        return
    
    msg = await update.message.reply_text("Bentar, gue cek data dulu...")
    jawaban = await ask_ai(question)
    await msg.edit_text(jawaban)

# ... (Sisa kode bot lo yang lain tetep sama, tinggal sesuaikan bagian handler di bawah) ...

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("ai", cmd_ai))
    # Tambahin handler lo yang lain di sini...
    app.run_polling()

if __name__ == "__main__":
    main()
