# SCRAPERS Bot — Deploy ke Render.com

## File yang diperlukan
- `bot.py` — kode bot utama
- `requirements.txt` — dependencies
- `render.yaml` — konfigurasi Render (opsional)

---

## Cara Deploy ke Render.com

### Step 1 — Upload ke GitHub
1. Buka github.com → New repository → nama: `scrapers-bot`
2. Upload 3 file: `bot.py`, `requirements.txt`, `render.yaml`

### Step 2 — Connect ke Render
1. Buka **render.com** → Sign up gratis (pakai Google/GitHub)
2. Klik **"New +"** → pilih **"Background Worker"**
3. Connect GitHub → pilih repo `scrapers-bot`
4. Isi settings:
   - **Name:** scrapers-bot
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. Klik **"Create Background Worker"**

### Step 3 — Set Environment Variables
Di halaman Render service → tab **"Environment"** → tambah:

| Key | Value |
|-----|-------|
| `TELEGRAM_BOT_TOKEN` | `8669650950:AAEyLg4LATqXMMWv7gvDfJaOCkgeREWXv6U` |
| `SUPABASE_URL` | `https://tqmqdrifrbvupkrufecc.supabase.co` |
| `SUPABASE_KEY` | `sb_publishable_bQTJDIyQYhx6P3Wljt82JA_gJmnFud1` |
| `OWNER_CHAT_ID` | `1953642141,8117718091` |
| `OPERATOR_IDS` | (isi kalau ada operator terdaftar) |
| `ANTHROPIC_API_KEY` | (isi untuk fitur AI) |

Klik **"Save Changes"** → bot otomatis restart dan jalan.

---

## Fitur Bot v3

### Menu Owner (👑)
- 📊 Laporan Hari Ini
- 🔔 Cek Maintenance
- 💰 Ringkasan Biaya
- 🚛 Status Unit
- 📦 Cek Stok Spare
- 📈 Analisis Cepat (7 hari)
- 🤖 Tanya AI (natural language)
- ⛽ Input Solar
- 🔧 Input Service
- 📒 Catat Harian

### Menu Operator (👷)
- ⛽ Input Solar → simpan ke Supabase → notif ke owner
- 🔧 Input Service → simpan ke Supabase → notif ke owner
- 📒 Catat Harian → tulis bebas → simpan ke Supabase
- 📊 Laporan Hari Ini

### Scheduled (otomatis)
- 06:00 WIB → Laporan harian ke owner
- 07:00 WIB → Alert maintenance kalau ada yang overdue
- 08:00 WIB → Alert stok spare kritis
- Tiap 10 menit → Keep-alive ping (biar bot tidak tidur di Render)

---

## Catatan Penting
- Render free tier: bot tidak pernah tidur selama ada traffic
- Keep-alive job tiap 10 menit memastikan bot tetap aktif
- Data yang diinput via bot langsung masuk Supabase
- PWA otomatis update karena baca Supabase yang sama
