"""
╔═════════════════════════════════════════════════════════════╗
║                                                             ║
║            NEXUS v6.5 - Full Fidelity Data Cache            ║
║        Auto-Fetch Sniper & Hierarchy UI Integration         ║
║                                                             ║
╚═════════════════════════════════════════════════════════════╝
"""

import discord
from discord.ext import commands
import asyncio
import os
import sqlite3
import time
import requests
import aiohttp
import base64
import difflib
import re
import sys
from collections import deque
import psutil 
from datetime import datetime, timedelta
from dotenv import load_dotenv
from keep_alive import keep_alive
import io
import itertools

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION & SQLITE SETUP
# ═══════════════════════════════════════════════════════════════

load_dotenv()
token_rahasia = os.environ.get('DISCORD_TOKEN')
gemini_api_key = os.environ.get('GEMINI_API_KEY')

TOKEN_API = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhcGktY29yZSIsImV4cCI6MjI5NzUxMzI4MywiaWF0IjoxNzc3NTI5MjgzLCJqdGkiOiIxZGNhMWUzMy0yODQ2LTQ5YmQtOGRjZS1hNTEzNjEwYzYwNGQiLCJJRCI6MTgxLCJGdWxsTmFtZSI6IlN1bmFudG8gSGlkYXlhdCIsIkVtYWlsIjoieGF3aW5lMzEyNEBwZXJ0b2suY29tIiwiVXNlclR5cGUiOiJwdWJsaWMifQ.Kp1HsE6r1jZ4l3bm_3R24dDgKYNE6F5e05nuK-8AVWk"
THEME_COLOR = 0x00FF00 

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

start_time = time.time()
active_snipers = {} 
scan_controller = {"stop": False} 
last_scanned_cid = 0 

DB_NAME = "nexus_overseer.db"
DB_DEEPSCAN = "deepscan_data.db"

# ==========================================================
# 💾 MEMORI PERMANEN UNTUK SYSTEM MODE
# ==========================================================
MODE_FILE = "nexus_mode.txt"

def load_system_mode():
    if os.path.exists(MODE_FILE):
        with open(MODE_FILE, "r") as f:
            saved_mode = f.read().strip().upper()
            if saved_mode in ["LIVE", "OFFLINE"]:
                return saved_mode
    return "LIVE" # Mode default jika bot baru pertama kali jalan

def save_system_mode(new_mode):
    with open(MODE_FILE, "w") as f:
        f.write(new_mode)

SYSTEM_MODE = load_system_mode()

def setup_legacy_db(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS submissions
                 (sid TEXT PRIMARY KEY, cid TEXT, uid TEXT, uname TEXT, 
                  score TEXT, penalty TEXT, code TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_snipers (cid TEXT PRIMARY KEY, channel_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contest_list
                 (cid INTEGER PRIMARY KEY, name TEXT, dt_start TEXT, hari TEXT, tanggal TEXT, jam TEXT,
                  cat_folder TEXT, class_folder TEXT, level_folder TEXT)''')
    conn.commit()
    conn.close()

def setup_deep_db(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("PRAGMA table_info(submissions)")
    columns = [col[1] for col in c.fetchall()]
    if columns and 'problem' not in columns:
        c.execute("DROP TABLE IF EXISTS submissions")

    c.execute('''CREATE TABLE IF NOT EXISTS submissions
                 (sid TEXT PRIMARY KEY, cid TEXT, uid TEXT, uname TEXT, 
                  score TEXT, penalty TEXT, code TEXT, 
                  problem TEXT, difficulty TEXT, status TEXT, 
                  time_submitted TEXT, type TEXT, accepted TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contest_list
                 (cid INTEGER PRIMARY KEY, name TEXT, dt_start TEXT, hari TEXT, tanggal TEXT, jam TEXT,
                  cat_folder TEXT, class_folder TEXT, level_folder TEXT)''')
    conn.commit()
    conn.close()

def init_db():
    setup_legacy_db(DB_NAME)      # Melindungi nexus_overseer.db
    setup_deep_db(DB_DEEPSCAN)    # Menyiapkan deepscan_data.db

init_db()

# ═══════════════════════════════════════════════════════════════
# CORE UTILITIES & PARSER
# ═══════════════════════════════════════════════════════════════

def parse_cluster_name(name: str):
    cat = "LAINNYA"
    cls = "UMUM"
    lv = "LV 1"
    
    cat_match = re.search(r"(?i)(PRAKTIKUM\s+\d+|REMEDIAL|KUIS\s+\d+)", name)
    if cat_match: cat = cat_match.group(1).upper()
    else: cat = name.upper()[:25] 
    
    cls_match = re.search(r"(?i)(KELAS\s+[A-Z])", name)
    if cls_match: cls = cls_match.group(1).upper()
    
    lv_match = re.search(r"(?i)(LV\s+\d+|LEVEL\s+\d+)", name)
    if lv_match: lv = lv_match.group(1).upper()
    
    return cat, cls, lv

def format_time(iso_str):
    try:
        dt = datetime.strptime(iso_str.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        ts = int(dt.timestamp())
        return f"<t:{ts}:F> (<t:{ts}:R>)"
    except: return "Unknown Time"

def get_difficulty(attempts):
    try:
        att = int(attempts)
        if att <= 2: return "🟢 **[EASY]**"
        if att <= 5: return "🟡 **[MEDIUM]**"
        return "🔴 **[HARD CORE]**"
    except: return "⚪ **[UNKNOWN]**"

def save_to_db(sid, cid, uid, uname, score, penalty, code, problem, difficulty, status, time_submitted, type_val, accepted, target_db):
    conn = sqlite3.connect(target_db)
    c = conn.cursor()
    
    # 🟢 LOGIKA ADAPTIF: Cek mau masuk ke brankas mana
    if target_db == DB_DEEPSCAN:
        # Jika ke Deepscan, simpan FULL 13 Kolom
        c.execute('''INSERT OR REPLACE INTO submissions 
                     (sid, cid, uid, uname, score, penalty, code, problem, difficulty, status, time_submitted, type, accepted) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (sid, cid, uid, uname, score, penalty, code, problem, difficulty, status, time_submitted, type_val, accepted))
    else:
        # Jika ke nexus_overseer.db lama, cukup simpan 7 Kolom intinya saja
        c.execute('''INSERT OR REPLACE INTO submissions 
                     (sid, cid, uid, uname, score, penalty, code) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                  (sid, cid, uid, uname, score, penalty, code))
                  
    conn.commit()
    conn.close()

# ==========================================================
# 👑 OWNER CLEARANCE (GANTI DENGAN ID DISCORD KAMU)
# ==========================================================
OWNER_ID = 623495365542281227 

def is_owner():
    async def predicate(ctx):
        if ctx.author.id != OWNER_ID:
            await ctx.send("⛔ **AKSES DITOLAK.** Kamu bukan Administrator NEXUS.", delete_after=5)
            return False
        return True
    return commands.check(predicate)

def ghost_mapping(new_code, current_sid, current_uid):
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME

    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    c.execute("SELECT sid, uname, code FROM submissions WHERE uid != ?", (current_uid,))
    records = c.fetchall()
    conn.close()

    matches = []
    for record in records:
        db_sid, db_uname, db_code = record
        sim = difflib.SequenceMatcher(None, new_code, db_code).ratio() * 100
        if sim > 85: 
            matches.append(f"`{db_uname}` (SID: {db_sid} - **{round(sim, 1)}%**)")
    return matches

async def sniper_loop(cid, channel):
    try:
        while True:
            await asyncio.sleep(60) 
    except asyncio.CancelledError:
        pass

@bot.event
async def on_ready():
    user_str = str(bot.user)
    print(f"\n[+] NEXUS v6.5 TARGET LOCK ONLINE: {user_str}")
    
    # ==========================================================
    # 🟢 AUTO-RESUME SNIPER (Anti-Amnesia saat bot Restart)
    # ==========================================================
    global active_snipers
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Baca buku catatan radar sebelum bot mati
        records = c.execute("SELECT cid, channel_id FROM active_snipers").fetchall()
        conn.close()
        
        restarted_count = 0
        for cid, channel_id in records:
            channel = bot.get_channel(channel_id)
            if channel:
                # Nyalakan kembali mesin radarnya!
                active_snipers[cid] = bot.loop.create_task(sniper_loop(cid, channel))
                restarted_count += 1
                
        if restarted_count > 0:
            print(f"📡 [RADAR SYSTEM] Auto-Resume aktif! Berhasil memulihkan {restarted_count} target Snipe.")
    except Exception as e:
        print(f"🔴 [SYSTEM] Gagal memulihkan memori Sniper: {e}")

# ==========================================================
# 📡 SISTEM PEREKAM LOG (Untuk menangkap print() ke Discord)
# ==========================================================
class LogCatcher:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.logs = deque(maxlen=20) 
        
    def write(self, text):
        self.original_stdout.write(text) 
        if text.strip():
            self.logs.append(text.strip()) 
            
    def flush(self):
        self.original_stdout.flush()

sys.stdout = LogCatcher(sys.stdout)

# ═══════════════════════════════════════════════════════════════
# INTERACTIVE UI (DENGAN TOMBOL NAVIGASI BALIK & BATAL)
# ═══════════════════════════════════════════════════════════════

class NexusActions(discord.ui.View):
    def __init__(self, cid, sid, uid):
        super().__init__(timeout=None)
        self.cid, self.sid, self.uid = cid, sid, uid

    @discord.ui.button(label="🧠 Analyze AI", style=discord.ButtonStyle.green)
    async def btn_analyze(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"⌛ `[SYSTEM]` Memicu audit AI untuk SID `{self.sid}`... (Data aman)", ephemeral=True)
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        bot.loop.create_task(ctx.invoke(bot.get_command('analyze'), cid=self.cid, sid=self.sid))

    @discord.ui.button(label="🕸️ Ghost Mapping", style=discord.ButtonStyle.blurple)
    async def btn_ghost(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        global SYSTEM_MODE
        db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME

        conn = sqlite3.connect(db_target)
        res = conn.cursor().execute("SELECT code FROM submissions WHERE sid=?", (self.sid,)).fetchone()
        conn.close()
        if not res: return await interaction.followup.send("❌ Kode sumber tidak ditemukan di Database.", ephemeral=True)
        matches = ghost_mapping(res[0], self.sid, self.uid)
        if matches: await interaction.followup.send("🚨 **GHOST NETWORK DETECTED!**\n" + "\n".join(matches[:5]), ephemeral=True)
        else: await interaction.followup.send("✅ **AMAN.** Tidak ada jaringan plagiarisme.", ephemeral=True)

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

class CustomLimitModal(discord.ui.Modal, title="Input Rentang Custom"):
    limit_input = discord.ui.TextInput(label="Jumlah data:", placeholder="Contoh: 15", style=discord.TextStyle.short, required=True, max_length=4)
    def __init__(self, target_cid, target_path, original_message):
        super().__init__()
        self.target_cid, self.target_path, self.original_message = target_cid, target_path, original_message

    async def on_submit(self, interaction: discord.Interaction):
        limit = self.limit_input.value
        if not limit.isdigit(): return await interaction.response.send_message("❌ Hanya angka!", ephemeral=True)
        await interaction.response.edit_message(content=f"🚀 **Menjalankan NEXUS Pipeline**\n> Target CID: `{self.target_cid}` | Limit: `{limit}`", embed=None, view=None)
        ctx = await bot.get_context(self.original_message)
        ctx.author = interaction.user
        bot.loop.create_task(ctx.invoke(bot.get_command('nexus'), start_cid=str(self.target_cid), limit=limit))

class NexusNavView(discord.ui.View):
    def __init__(self, previous_view=None, previous_embed=None):
        super().__init__(timeout=600)
        self.previous_view = previous_view
        self.previous_embed = previous_embed
        self.current_embed = None

        if self.previous_view is not None:
            btn_back = discord.ui.Button(label="⬅️ Balik", style=discord.ButtonStyle.secondary, row=4)
            btn_back.callback = self.go_back
            self.add_item(btn_back)

        btn_cancel = discord.ui.Button(label="❌ Batal", style=discord.ButtonStyle.danger, row=4)
        btn_cancel.callback = self.cancel_action
        self.add_item(btn_cancel)

    async def go_back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.previous_embed, view=self.previous_view)

    async def cancel_action(self, interaction: discord.Interaction):
        await interaction.message.delete()

class RangeSelect(discord.ui.Select):
    def __init__(self, target_cid, target_path):
        self.target_cid, self.target_path = target_cid, target_path
        options = [
            discord.SelectOption(label="Top 1 - 5", emoji="1️⃣", value="5"),
            discord.SelectOption(label="Top 1 - 15", emoji="2️⃣", value="15"),
            discord.SelectOption(label="Ketik Manual (Custom)", emoji="⌨️", value="custom"),
        ]
        super().__init__(placeholder="⚙️ Pilih rentang ekstraksi...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "custom":
            await interaction.response.send_modal(CustomLimitModal(self.target_cid, self.target_path, interaction.message))
        else:
            await interaction.response.edit_message(content=f"🚀 **Menjalankan NEXUS Pipeline**\n> Target CID: `{self.target_cid}` | Limit: `{val}`", embed=None, view=None)
            ctx = await bot.get_context(interaction.message)
            ctx.author = interaction.user
            bot.loop.create_task(ctx.invoke(bot.get_command('nexus'), start_cid=str(self.target_cid), limit=val))

class LevelSelect(discord.ui.Select):
    def __init__(self, levels_dict, path, parent_view):
        self.levels_dict, self.path, self.parent_view = levels_dict, path, parent_view
        options = []
        for lv in list(levels_dict.keys())[:25]:
            cid_val = str(levels_dict[lv][0]['cid'])
            jam_val = levels_dict[lv][0].get('jam', 'Unknown Time')
            desc_text = f"⏰ {jam_val} | CID: {cid_val}"
            options.append(discord.SelectOption(label=lv, description=desc_text[:100], emoji="📊", value=cid_val))
        
        is_other = "OTHER" in path.upper()
        ph = "📊 Pilih Data (Atau UMUM)..." if "UMUM" in levels_dict or is_other else "📂 Pilih Level Praktikum..."
        super().__init__(placeholder=ph, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        cid = self.values[0]
        lv_label = next(name for name, items in self.levels_dict.items() if str(items[0]['cid']) == cid)
        new_path = f"{self.path} ➔ {lv_label}"
        
        embed = discord.Embed(title="⚙️ KONFIGURASI", description=f"**Direktori Terpilih:**\n`{new_path}`\n\nSilakan pilih rentang data yang ingin ditarik.", color=0xFF9900)
        
        next_view = NexusNavView(previous_view=self.parent_view, previous_embed=self.parent_view.current_embed)
        next_view.current_embed = embed
        next_view.add_item(RangeSelect(cid, new_path))
        
        await interaction.response.edit_message(embed=embed, view=next_view)

class ClassSelect(discord.ui.Select):
    def __init__(self, classes_dict, path, parent_view):
        self.classes_dict, self.path, self.parent_view = classes_dict, path, parent_view
        
        is_other = "OTHER" in path.upper()
        emo = "📅" if is_other else "💻"
        ph = "📅 Pilih Tanggal Pelaksanaan..." if is_other else ("💻 Pilih Kelas (Atau UMUM)..." if "UMUM" in classes_dict else "💻 Pilih Kelas...")
        
        options = [discord.SelectOption(label=cls, emoji=emo, value=cls) for cls in list(classes_dict.keys())[:25]]
        super().__init__(placeholder=ph, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        selected_cls = self.values[0]
        levels_dict = self.classes_dict[selected_cls]
        new_path = f"{self.path} ➔ {selected_cls}"
        
        is_other = "OTHER" in self.path.upper()
        title_embed = f"📊 PILIH LEVEL" if is_other else f"📊 PILIH LEVEL: {selected_cls}"
        desc_embed = "Pilih level untuk melihat data:" if is_other else "Pilih tingkatan Level praktikum:"
        
        embed = discord.Embed(title=title_embed, description=desc_embed, color=0x00FF00)
        
        next_view = NexusNavView(previous_view=self.parent_view, previous_embed=self.parent_view.current_embed)
        next_view.current_embed = embed
        next_view.add_item(LevelSelect(levels_dict, new_path, next_view))
        
        await interaction.response.edit_message(embed=embed, view=next_view)

class DaySelect(discord.ui.Select):
    def __init__(self, days_dict, path, parent_view):
        self.days_dict, self.path, self.parent_view = days_dict, path, parent_view
        
        is_other = "OTHER" in path.upper()
        emo = "📁" if is_other else "📅"
        ph = "📁 Pilih Sub-Folder (Cluster)..." if is_other else "📅 Pilih Jadwal Hari..."
        
        options = []
        for day in list(days_dict.keys())[:25]:
            label_tampil = day.replace(", (Cluster)", "")
            options.append(discord.SelectOption(label=label_tampil, emoji=emo, value=day))
            
        super().__init__(placeholder=ph, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        selected_day = self.values[0]
        classes_dict = self.days_dict[selected_day]
        clean_day = selected_day.replace(', (Cluster)', '')
        new_path = f"{self.path} ➔ {clean_day}" 
        
        is_other = "OTHER" in self.path.upper()
        title_embed = "📅 PILIH TANGGAL" if is_other else "💻 PILIH KELAS"
        desc_embed = f"Folder Terpilih: **{clean_day}**" if is_other else f"Jadwal: **{selected_day}**"
        
        embed = discord.Embed(title=title_embed, description=desc_embed, color=THEME_COLOR)
        
        next_view = NexusNavView(previous_view=self.parent_view, previous_embed=self.parent_view.current_embed)
        next_view.current_embed = embed
        next_view.add_item(ClassSelect(classes_dict, new_path, next_view))
        
        await interaction.response.edit_message(embed=embed, view=next_view)

class CategorySelect(discord.ui.Select):
    def __init__(self, grouped_data, parent_view):
        self.grouped_data, self.parent_view = grouped_data, parent_view
        options = [discord.SelectOption(label=cat, emoji="📁", value=cat) for cat in list(grouped_data.keys())[:25]]
        super().__init__(placeholder="📁 Pilih Folder Utama...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        days_dict = self.grouped_data[cat]
        
        embed = discord.Embed(title=f"📅 JADWAL: {cat}", description="Pilih Hari Pelaksanaan:", color=THEME_COLOR)
        
        next_view = NexusNavView(previous_view=self.parent_view, previous_embed=self.parent_view.current_embed)
        next_view.current_embed = embed
        next_view.add_item(DaySelect(days_dict, cat, next_view))
        
        await interaction.response.edit_message(embed=embed, view=next_view)

# =====================================================================
# COMMAND BARU: !dashboard (INTERACTIVE CLASS LEADERBOARD)
# =====================================================================
class DashboardNavView(discord.ui.View):
    def __init__(self, ctx, embeds):
        super().__init__(timeout=300) # Aktif selama 5 menit
        self.ctx = ctx
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="⬅️ Mundur", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: 
            return await interaction.response.send_message("❌ Hanya komandan yang bisa memencet ini.", ephemeral=True)
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Maju ➡️", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: 
            return await interaction.response.send_message("❌ Hanya komandan yang bisa memencet ini.", ephemeral=True)
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="❌ Tutup", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        await interaction.message.delete()

@bot.command(aliases=['board', 'db'])
async def dashboard(ctx, cid: str):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    
    m = await ctx.send(f"🎛️ `[SYSTEM]` Memuat Panel Kontrol untuk CID `{cid}` dari `{db_target}`...")
    
    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    # Mengambil data diurutkan berdasarkan Nilai Tertinggi
    c.execute("""SELECT sid, uname, score, penalty, status, problem, time_submitted 
                 FROM submissions WHERE cid=? 
                 ORDER BY CAST(score AS INTEGER) DESC""", (str(cid),))
    records = c.fetchall()
    
    # Cek nama folder untuk judul
    c.execute("SELECT name FROM contest_list WHERE cid=?", (str(cid),))
    folder_name = c.fetchone()
    conn.close()
    
    if not records:
        return await m.edit(content=f"❌ **KOSONG:** Tidak ada data peserta yang ditemukan untuk CID `{cid}` di `{db_target}`.")
        
    contest_title = folder_name[0] if folder_name else f"Cluster {cid}"
    
    # Menghitung Statistik Cepat
    total_acc = sum(1 for r in records if r[4] and "Accepted" in r[4])
    total_wa = sum(1 for r in records if r[4] and "Wrong Answer" in r[4])
    total_other = len(records) - total_acc - total_wa
    
    # Memecah data menjadi beberapa halaman (10 peserta per halaman)
    items_per_page = 10
    pages = [records[i:i + items_per_page] for i in range(0, len(records), items_per_page)]
    embeds = []
    
    for page_num, page_data in enumerate(pages):
        embed = discord.Embed(title=f"🎛️ NEXUS DASHBOARD: {contest_title}", color=0x00FFFF)
        embed.description = (f"**Statistik Kelas:**\n"
                             f"👥 Total: `{len(records)} Orang` | 🟢 ACC: `{total_acc}` | 🔴 WA: `{total_wa}` | ⚪ Lainnya: `{total_other}`\n"
                             f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        for idx, row in enumerate(page_data):
            sid, uname, score, penalty, status, problem, time_sub = row
            
            # Menentukan Ikon Status
            if status and "Accepted" in status: icon = "🟢"
            elif status and "Wrong Answer" in status: icon = "🔴"
            else: icon = "⚪"
            
            # Membersihkan Tampilan Waktu & Nama
            clean_name = uname if uname and uname != "Unknown" else f"Peserta Rahasia ({sid})"
            clean_prob = problem[:25] + "..." if problem and len(problem) > 25 else problem
            
            try: waktu = time_sub.split("T")[1][:5] # Ambil Jam:Menit saja jika ISO format
            except: waktu = "Unknown"
            
            peringkat = (page_num * items_per_page) + idx + 1
            medali = "🥇" if peringkat == 1 else "🥈" if peringkat == 2 else "🥉" if peringkat == 3 else f"`#{peringkat}`"
            
            # Format Tampilan Peserta yang Rapi
            teks_peserta = (f"> **Score: `{score}`** | Pen: `{penalty}` | ⏱️ `{waktu}`\n"
                            f"> 📝 *{clean_prob}*\n"
                            f"> 🏷️ Status: {status}")
            
            embed.add_field(name=f"{medali} {icon} **{clean_name}**", value=teks_peserta, inline=False)
            
        embed.set_footer(text=f"Halaman {page_num + 1} dari {len(pages)} | Mode: {SYSTEM_MODE} | Ketik !nexus <cid> <limit> untuk sedot data")
        embeds.append(embed)
        
    # Kirim Embed dengan Tombol Navigasi
    view = DashboardNavView(ctx, embeds)
    await m.delete()
    await ctx.send(embed=embeds[0], view=view)

# ═══════════════════════════════════════════════════════════════
# COMMAND CENTER
# ═══════════════════════════════════════════════════════════════

@bot.command()
async def help(ctx):
    try: await ctx.message.delete()
    except: pass
    
    is_admin = (ctx.author.id == OWNER_ID)
    
    if is_admin:
        embed = discord.Embed(title="🛡️ QUANTUM OVERSEER COMMAND CENTER", description="Sistem Intelijen v6.5 — **Mode Administrator Aktif**", color=0xFF0000)
        
        embed.add_field(name="📌 Core Engines", value=(
            "**`!nexus <cid> <limit>`** • Ekstraksi Manual Spesifik\n"
            "**`!snipe <cids>`** • Tracking Multi-Cluster (Auto-Fetch)\n"
            "**`!analyze <cid> <sid>`** • AI Logic Analysis\n"
            "**`!diff <cid> <id1> <id2>`** • Deteksi Plagiarisme"
        ), inline=False)
        
        embed.add_field(name="🔧 Utilities & Recon", value=(
            "**`!rescan <start> <end>`** • Multi-Thread Recon\n"
            "**`!list`** • UI Hierarki & Target Lock\n"
            "**`!latest [start]`** • Cari Cluster ID Terbaru\n"
            "**`!status`** • Metrik & Status DB\n"
            "**`!clean`** • Bersihkan SQLite DB Submissions\n"
            "**`!dbclean`** • Bersihkan SQLite DB Folders\n"
            "**`!patch <start> <end>`** • Menambal yang kosong\n"
            "**`!deepscan <start> <end>`** • Deep Scan Data\n"
            "**`!deeppatch <start> <end>`** • Menambal DeepScan Kosong\n"
            "**`!audit <start> <end>`** • Mencari Tau DataBase Cacat\n"
            "**`!skynet <cid>`** • Mass Plagiarism Scanner\n"
            "**`!stats <cid>`** • Visual Analytics Engine\n"
            "**`!dashboard <cid>`** • Interactive Class Leaderboard\n"
            "**`!mode`** • Toggle System Mode\n"
        ), inline=False)

        embed.add_field(name="👑 Owner Secret Access", value=(
            "**`!admin`** • Dashboard Hardware & RAM\n"
            "**`!logs`** • Intip Console Log via DM\n"
            "**`!set_token <api/gemini> <key>`** • Hot-Swap Token\n"
            "**`!maintenance`** • Kunci Akses Publik\n"
            "**`!broadcast <pesan>`** • Kirim Pesan ke Radar Aktif\n"
            "**`!stop`** • Hentikan Semua Radar\n"
            "**`!delete <jumlah>`** • Pembersihan Chat Bot"
        ), inline=False)
        
        embed.set_footer(text="Akses Terverifikasi: Root Administrator")
        
    else:
        embed = discord.Embed(title="🛡️ QUANTUM OVERSEER COMMAND CENTER", description="Sistem Intelijen v6.5", color=THEME_COLOR)
        
        embed.add_field(name="📌 Core Engines", value=(
            "**`!nexus <cid> <limit>`** • Ekstraksi Manual Spesifik\n"
            "**`!snipe <cids>`** • Tracking Multi-Cluster (Auto-Fetch)\n"
            "**`!analyze <cid> <sid>`** • AI Logic Analysis\n"
            "**`!diff <cid> <id1> <id2>`** • Deteksi Plagiarisme"
        ), inline=False)
        
        embed.add_field(name="🔧 Utilities & Recon", value=(
            "**`!list`** • UI Hierarki & Target Lock\n"
            "**`!latest [start]`** • Cari Cluster ID Terbaru"
        ), inline=False)
        
        embed.set_footer(text="Nexus v6.5")

    await ctx.send(embed=embed)

@bot.command()
@is_owner()
async def mode(ctx):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    if SYSTEM_MODE == "OFFLINE":
        SYSTEM_MODE = "LIVE"
        save_system_mode("LIVE") # 🟢 Simpan ke ingatan permanen
        embed = discord.Embed(title="⚙️ SYSTEM MODE: ONLINE (LIVE)", description="**Database:** `nexus_overseer.db`\n**Aksi:** Nexus akan memaksa FFUF Live, dan `!list` akan membaca folder dari radar rescan.", color=0xFF0000)
    else:
        SYSTEM_MODE = "OFFLINE"
        save_system_mode("OFFLINE") # 🟢 Simpan ke ingatan permanen
        embed = discord.Embed(title="⚙️ SYSTEM MODE: OFFLINE (AUTO)", description="**Database:** `deepscan_data.db`\n**Aksi:** Nexus & UI akan membaca instan dari memori gudang deepscan.", color=0x00FF00)
        
    await ctx.send(embed=embed, delete_after=15)

@bot.command()
@is_owner()
async def logs(ctx):
    try: await ctx.message.delete()
    except: pass
    
    log_text = "\n".join(sys.stdout.logs)
    if not log_text:
        log_text = "Console bersih. Belum ada aktivitas."
        
    embed = discord.Embed(title="📜 LIVE CONSOLE LOGS", description=f"```bash\n{log_text}\n```", color=0x333333)
    embed.set_footer(text="Data log ini dikirim secara aman via DM.")
    
    try:
        await ctx.author.send(embed=embed) 
        await ctx.send("✅ `[SYSTEM]` Log console terbaru telah dikirim ke DM Anda, Tuan.", delete_after=5)
    except:
        await ctx.send("❌ Gagal mengirim DM. Pastikan DM kamu terbuka untuk server ini!", delete_after=5)

@bot.command()
@is_owner()
async def admin(ctx):
    try: await ctx.message.delete()
    except: pass
    
    m = await ctx.send("🔄 Mengumpulkan metrik sistem Replit...")
    
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_percent = psutil.cpu_percent(interval=0.5)
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    db_size = os.path.getsize(db_target) / (1024 * 1024) if os.path.exists(db_target) else 0
    
    active_tasks = len([t for t in asyncio.all_tasks() if not t.done()])
    
    embed = discord.Embed(title="👑 NEXUS COMMANDER DASHBOARD", color=0xFF0000)
    embed.add_field(name="💻 Replit Server Status", value=f"> **CPU Usage:** `{cpu_percent}%`\n> **RAM Usage:** `{mem_mb:.2f} MB`\n> **Bot Latency:** `{round(bot.latency * 1000)}ms`", inline=False)
    embed.add_field(name="🗄️ Database Health", value=f"> **Target DB:** `{db_target}`\n> **File Size:** `{db_size:.2f} MB`", inline=False)
    embed.add_field(name="⚙️ Asyncio Engine", value=f"> **Active Tasks:** `{active_tasks}` thread(s) berjalan", inline=False)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    
    await m.edit(content=None, embed=embed)

@bot.command()
@is_owner()
async def set_token(ctx, jenis: str, new_token: str):
    try: await ctx.message.delete()
    except: pass
    
    jenis = jenis.lower()
    sensor_token = new_token[:8] + "..." + new_token[-4:]

    if jenis == "api":
        global TOKEN_API
        TOKEN_API = new_token
        await ctx.author.send(f"🔑 **TOKEN CHRONICLES API DIPERBARUI!**\nToken baru: `{new_token}`")
        await ctx.send(f"✅ `[SYSTEM]` Token Chronicles API berhasil di-hot-swap. \n> Preview: `{sensor_token}`", delete_after=5)
        
    elif jenis == "gemini":
        global GEMINI_API_KEY
        GEMINI_API_KEY = new_token
        await ctx.author.send(f"🧠 **TOKEN GEMINI AI DIPERBARUI!**\nToken baru: `{new_token}`")
        await ctx.send(f"✅ `[SYSTEM]` Token Gemini AI berhasil di-hot-swap. \n> Preview: `{sensor_token}`", delete_after=5)
        
    else:
        await ctx.send("❌ Tipe tidak valid! Gunakan: `!set_token api <token>` atau `!set_token gemini <token>`", delete_after=8)

maintenance_mode = False

@bot.event
async def on_command_error(ctx, error):
    if maintenance_mode and ctx.author.id != OWNER_ID:
        return await ctx.send("🚧 **MAINTENANCE:** Bot sedang dalam perbaikan oleh Owner. Silakan coba lagi nanti.", delete_after=5)
    raise error

@bot.command()
@is_owner()
async def maintenance(ctx):
    global maintenance_mode
    maintenance_mode = not maintenance_mode
    status = "AKTIF" if maintenance_mode else "NON-AKTIF"
    await ctx.send(f"⚠️ `[SYSTEM]` Maintenance Mode sekarang **{status}**.")

@bot.command()
@is_owner()
async def broadcast(ctx, *, pesan: str):
    try: await ctx.message.delete()
    except: pass
    
    conn = sqlite3.connect(DB_NAME)
    active_channels = conn.cursor().execute("SELECT channel_id FROM active_snipers").fetchall()
    conn.close()
    
    count = 0
    for ch_id in active_channels:
        try:
            channel = bot.get_channel(ch_id[0])
            if channel:
                embed = discord.Embed(title="📢 PENGUMUMAN OWNER", description=pesan, color=0xFFA500)
                embed.set_footer(text="Pesan ini dikirim ke seluruh radar aktif.")
                await channel.send(embed=embed)
                count += 1
        except: continue
        
    await ctx.author.send(f"✅ Pesan broadcast berhasil terkirim ke `{count}` channel.")

@bot.command()
@is_owner()
async def deepscan(ctx, start_id: int = None, end_id: int = None):
    try: await ctx.message.delete()
    except: pass

    global scan_controller, last_scanned_cid
    scan_controller["stop"] = False 

    conn = sqlite3.connect(DB_DEEPSCAN)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scan_state (key TEXT PRIMARY KEY, value INTEGER)''')
    
    max_cid_query = c.execute("SELECT MAX(cid) FROM contest_list").fetchone()[0]
    max_cid = max_cid_query if max_cid_query else 0

    if start_id is None:
        start_id = max_cid + 1
        saved_end = c.execute("SELECT value FROM scan_state WHERE key='deep_target_end'").fetchone()
        
        if saved_end and saved_end[0] >= start_id:
            end_id = saved_end[0]
        else:
            end_id = start_id + 299 
            c.execute("INSERT OR REPLACE INTO scan_state (key, value) VALUES ('deep_target_end', ?)", (end_id,))
    else:
        if end_id is None: end_id = start_id + 299
        c.execute("INSERT OR REPLACE INTO scan_state (key, value) VALUES ('deep_target_end', ?)", (end_id,))
        
    conn.commit()
    conn.close()

    last_scanned_cid = start_id
    total_scans = end_id - start_id + 1

    msg = await ctx.send(f"🌌 `[DEEP SCAN]` Menyiapkan **Total Extraction**...\n> 🔄 **Mode:** Memulai dari CID `{start_id}` s/d `{end_id}`")
    
    nama_hari = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    nama_bulan = {1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'}
    
    found_count, processed_count, saved_submissions = 0, 0, 0
    last_edit_time = time.time()
    
    sem = asyncio.Semaphore(5) 
    bash_lock = asyncio.Lock()  
    db_lock = asyncio.Lock()
    headers = {"Authorization": f"Bearer {TOKEN_API}"}

    async def process_cid(cid, session):
        nonlocal found_count, processed_count, saved_submissions, last_edit_time
        global scan_controller, last_scanned_cid

        if scan_controller["stop"]:
            processed_count += 1
            return

        async with sem:
            url_score = f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}"
            try:
                async with session.get(url_score, headers=headers, timeout=5.0) as resp:
                    if resp.status == 400:
                        print(f"🟡 [-] CID {cid}: HTTP 400 Bad Request (Insta-Skip)")
                    elif resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        scoreboard = result.get("scoreboard", [])
                        problems = result.get("problems", [])
                        
                        sc_updated_at = result.get("scoreboard_updated_at", 0) 
                        
                        if len(scoreboard) == 0 and len(problems) == 0:
                            print(f"⚪ [-] CID {cid}: Kosong / Tidak ada partisipan (Insta-Skip)")
                        else:
                            async with bash_lock:
                                if scan_controller["stop"]: return

                                print(f"🔍 [*] CID {cid}: [DEEP SCAN] Mengekstrak SEMUA data partisipan...")
                                process = await asyncio.create_subprocess_exec(
                                    "bash", "nexus_core.sh", str(cid), "1000",
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await process.communicate()
                                output = stdout.decode().strip()
                                error_output = stderr.decode().strip()

                                data_saved = False
                                subs_in_this_cid = 0

                                for line in output.split('\n'):
                                    if line.startswith("NEXUS_DATA|"):
                                        p = line.split("|")
                                        if len(p) >= 18:
                                            try:
                                                raw_code = base64.b64decode(p[7] + "==").decode('utf-8', errors='ignore')
                                            except: 
                                                raw_code = "// Decode Error."
                                                
                                            try: diff_label = get_difficulty(p[13]) 
                                            except: diff_label = "Unknown"
                                            status_str = f"{p[15]} ({p[13]}/{p[14]})"
                                            
                                            async with db_lock:
                                                save_to_db(p[6], p[17], p[8], p[3], p[9], p[11], raw_code, p[2], diff_label, status_str, p[4], p[16], p[10], DB_DEEPSCAN)
                                            
                                            subs_in_this_cid += 1
                                            saved_submissions += 1

                                            if not data_saved:
                                                name = p[1].strip()
                                                iso_time = p[4] 
                                                
                                                try:
                                                    dt_first = datetime.strptime(iso_time[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=7)
                                                    waktu_mulai = dt_first - timedelta(minutes=15)
                                                    
                                                    if sc_updated_at > 0: waktu_selesai = datetime.utcfromtimestamp(sc_updated_at) + timedelta(hours=7) + timedelta(minutes=10)
                                                    else: waktu_selesai = dt_first + timedelta(hours=2)
                                                        
                                                    jam_indo = f"{waktu_mulai.strftime('%H:%M')} - {waktu_selesai.strftime('%H:%M')} WIB (Est)"
                                                    hari_indo = nama_hari[waktu_mulai.weekday()]
                                                    tanggal_indo = f"{waktu_mulai.day:02d} {nama_bulan[waktu_mulai.month]} {waktu_mulai.year}"
                                                    dt_str = waktu_mulai.strftime("%Y-%m-%d %H:%M:%S")
                                                except:
                                                    jam_indo, hari_indo, tanggal_indo, dt_str = "Unknown", "Unknown", "Unknown", "Unknown"

                                                if not re.search(r"(?i)(praktikum|remedia|kelas|lv|sesi|kuis|tugas)", name): 
                                                    cat = "📂 OTHER (LAINNYA)"
                                                    hari_folder = name.upper()[:25] 
                                                    tanggal_folder = "(Cluster)"    
                                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                                    lv = "UMUM"
                                                else:
                                                    cat, cls_folder, lv = parse_cluster_name(name)
                                                    hari_folder = hari_indo
                                                    tanggal_folder = tanggal_indo
                                                
                                                async with db_lock:
                                                    conn = sqlite3.connect(DB_DEEPSCAN, timeout=10)
                                                    c = conn.cursor()
                                                    c.execute('''INSERT OR REPLACE INTO contest_list 
                                                                 (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                              (cid, name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                                    conn.commit()
                                                    conn.close()
                                                    
                                                found_count += 1
                                                data_saved = True
                                                
                                if data_saved:
                                    print(f"🟢 [+] CID {cid}: [DEEP SCAN Selesai] Mengamankan {subs_in_this_cid} Source Code! Estimasi: {jam_indo}")
                                
                                if not data_saved:
                                    fallback_name = None
                                    try:
                                        url_any_sub = f"https://api.chronicles.sbs/core/v1/contest/submissions?contest_id={cid}&limit=1"
                                        async with session.get(url_any_sub, headers=headers, timeout=3.0) as r_sub:
                                            if r_sub.status == 200:
                                                d_sub = await r_sub.json()
                                                subs = d_sub.get("result", {}).get("submissions", [])
                                                if subs:
                                                    sid_any = subs[0].get("submission_id")
                                                    url_det = f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid_any}"
                                                    async with session.get(url_det, headers=headers, timeout=3.0) as r_det:
                                                        if r_det.status == 200:
                                                            d_det = await r_det.json()
                                                            fallback_name = d_det.get("result", {}).get("contest_name")
                                    except: pass

                                    if not fallback_name and problems: fallback_name = f"SOAL: {problems[0].get('title', 'Unknown')}"
                                    if not fallback_name and scoreboard: fallback_name = f"AKTIVITAS: {scoreboard[0].get('username', 'Peserta Rahasia')}"
                                    if not fallback_name: fallback_name = f"DATA KOSONG (CID {cid})"

                                    cat = "📂 OTHER (LAINNYA)"
                                    hari_folder = fallback_name.upper()[:25] 
                                    tanggal_folder = "(Cluster)"
                                    
                                    dt_now = datetime.now()
                                    hari_indo = nama_hari[dt_now.weekday()]
                                    tanggal_indo = f"{dt_now.day:02d} {nama_bulan[dt_now.month]} {dt_now.year}"
                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                    
                                    jam_indo = f"Selesai: {datetime.utcfromtimestamp(sc_updated_at).strftime('%H:%M')} WIB" if sc_updated_at > 0 else "Waktu Tidak Diketahui"
                                    dt_str = dt_now.strftime("%Y-%m-%d %H:%M:%S")
                                    lv = "UMUM"
                                    
                                    async with db_lock:
                                        conn = sqlite3.connect(DB_DEEPSCAN, timeout=10)
                                        c = conn.cursor()
                                        c.execute('''INSERT OR REPLACE INTO contest_list 
                                                     (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                  (cid, fallback_name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                        conn.commit()
                                        conn.close()
                                        
                                    found_count += 1
                                    print(f"🟠 [?] CID {cid}: [PATCHED] Diselamatkan Detektif -> {fallback_name}")
                                
                                await asyncio.sleep(1)

                    else:
                        print(f"🔴 [-] CID {cid}: HTTP Error {resp.status} (Skip)")
            except Exception as e:
                print(f"🔴 [!] CID {cid}: Timeout API / Jaringan Gagal -> {str(e)[:50]}")

            last_scanned_cid = max(last_scanned_cid, cid) 
            processed_count += 1
            
            if not scan_controller["stop"]:
                if time.time() - last_edit_time > 2.0 or processed_count == total_scans:
                    last_edit_time = time.time()
                    bar = "▓" * int(20 * processed_count // total_scans) + "░" * (20 - int(20 * processed_count // total_scans))
                    try: await msg.edit(content=f"🌌 `[DEEP SCAN]` **Menarik Total Data...**\n⏳ Progres: `[{bar}]` {processed_count}/{total_scans}\n> 🎯 Cluster: `{found_count}` | 💾 Total Kode: `{saved_submissions}`")
                    except: pass
            
            await asyncio.sleep(0.05)

    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_cid(cid, session) for cid in range(start_id, end_id + 1)]
        await asyncio.gather(*tasks)

    if scan_controller["stop"]:
        await msg.edit(content=f"🛑 **DEEP SCAN DIBATALKAN:**\n> 💾 Tersimpan: `{found_count}` Cluster & `{saved_submissions}` Kode sumber sebelum di-stop.\n> 📌 Angka Terakhir: `~{last_scanned_cid}`")
    else:
        await msg.edit(content=f"✅ **DEEP SCAN SELESAI:**\n> 💾 Total Cluster Valid: `{found_count}`\n> 💾 Total Kode C++ Tersimpan: `{saved_submissions}`\n> Database kini memiliki *Full Cache*. Penarikan via UI akan instan!")

@bot.command()
@is_owner()
async def deeppatch(ctx, start_id: int, end_id: int):
    try: await ctx.message.delete()
    except: pass

    conn = sqlite3.connect(DB_DEEPSCAN)
    c = conn.cursor()
    existing_records = c.execute("SELECT cid FROM contest_list WHERE cid BETWEEN ? AND ?", (start_id, end_id)).fetchall()
    conn.close()

    existing_cids = {row[0] for row in existing_records}
    missing_cids = [cid for cid in range(start_id, end_id + 1) if cid not in existing_cids]

    if not missing_cids:
        return await ctx.send(f"✅ `[DEEP PATCH]` **Gudang Sempurna!**\n> Tidak ada CID yang terlewat di rentang `{start_id}` hingga `{end_id}`.", delete_after=10)

    total_scans = len(missing_cids)
    
    global scan_controller
    scan_controller["stop"] = False 

    msg = await ctx.send(f"🩹 `[DEEP PATCH]` Menambal Lubang Gudang Data...\n> 🎯 Target: `{start_id}` s/d `{end_id}`\n> 🔍 Ditemukan: **{total_scans}** CID kosong yang perlu di-Deepscan.")
    
    nama_hari = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    nama_bulan = {1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'}
    
    found_clusters, saved_submissions, processed_count = 0, 0, 0
    last_edit_time = time.time()
    
    sem = asyncio.Semaphore(5) 
    bash_lock = asyncio.Lock()  
    db_lock = asyncio.Lock()
    headers = {"Authorization": f"Bearer {TOKEN_API}"}

    async def process_cid(cid, session):
        nonlocal found_clusters, saved_submissions, processed_count, last_edit_time
        global scan_controller

        if scan_controller["stop"]:
            processed_count += 1
            return

        async with sem:
            url_score = f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}"
            try:
                async with session.get(url_score, headers=headers, timeout=5.0) as resp:
                    if resp.status == 400:
                        print(f"🟡 [-] CID {cid}: HTTP 400 Bad Request (Insta-Skip)")
                    elif resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        scoreboard = result.get("scoreboard", [])
                        problems = result.get("problems", [])
                        
                        sc_updated_at = result.get("scoreboard_updated_at", 0) 
                        
                        if len(scoreboard) == 0 and len(problems) == 0:
                            print(f"⚪ [-] CID {cid}: Kosong / Tidak ada partisipan (Insta-Skip)")
                        else:
                            async with bash_lock:
                                if scan_controller["stop"]: return

                                print(f"🔍 [*] CID {cid}: [DEEP PATCH] Mengekstrak SEMUA data partisipan...")
                                process = await asyncio.create_subprocess_exec(
                                    "bash", "nexus_core.sh", str(cid), "1000",
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await process.communicate()
                                output = stdout.decode().strip()

                                data_saved = False
                                subs_in_this_cid = 0

                                for line in output.split('\n'):
                                    if line.startswith("NEXUS_DATA|"):
                                        p = line.split("|")
                                        if len(p) >= 18:
                                            try:
                                                raw_code = base64.b64decode(p[7] + "==").decode('utf-8', errors='ignore')
                                            except: 
                                                raw_code = "// Decode Error."
                                                
                                            try: diff_label = get_difficulty(p[13]) 
                                            except: diff_label = "Unknown"
                                            status_str = f"{p[15]} ({p[13]}/{p[14]})"
                                            
                                            async with db_lock:
                                                save_to_db(p[6], p[17], p[8], p[3], p[9], p[11], raw_code, p[2], diff_label, status_str, p[4], p[16], p[10], DB_DEEPSCAN)
                                                
                                            subs_in_this_cid += 1
                                            saved_submissions += 1

                                            if not data_saved:
                                                name = p[1].strip()
                                                iso_time = p[4] 
                                                
                                                try:
                                                    dt_first = datetime.strptime(iso_time[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=7)
                                                    waktu_mulai = dt_first - timedelta(minutes=15)
                                                    
                                                    if sc_updated_at > 0: waktu_selesai = datetime.utcfromtimestamp(sc_updated_at) + timedelta(hours=7) + timedelta(minutes=10)
                                                    else: waktu_selesai = dt_first + timedelta(hours=2)
                                                        
                                                    jam_indo = f"{waktu_mulai.strftime('%H:%M')} - {waktu_selesai.strftime('%H:%M')} WIB (Est)"
                                                    hari_indo = nama_hari[waktu_mulai.weekday()]
                                                    tanggal_indo = f"{waktu_mulai.day:02d} {nama_bulan[waktu_mulai.month]} {waktu_mulai.year}"
                                                    dt_str = waktu_mulai.strftime("%Y-%m-%d %H:%M:%S")
                                                except:
                                                    jam_indo, hari_indo, tanggal_indo, dt_str = "Unknown", "Unknown", "Unknown", "Unknown"

                                                if not re.search(r"(?i)(praktikum|remedia|kelas|lv|sesi|kuis|tugas)", name): 
                                                    cat = "📂 OTHER (LAINNYA)"
                                                    hari_folder = name.upper()[:25] 
                                                    tanggal_folder = "(Cluster)"    
                                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                                    lv = "UMUM"
                                                else:
                                                    cat, cls_folder, lv = parse_cluster_name(name)
                                                    hari_folder = hari_indo
                                                    tanggal_folder = tanggal_indo
                                                
                                                async with db_lock:
                                                    conn = sqlite3.connect(DB_DEEPSCAN, timeout=10)
                                                    c = conn.cursor()
                                                    c.execute('''INSERT OR REPLACE INTO contest_list 
                                                                 (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                              (cid, name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                                    conn.commit()
                                                    conn.close()
                                                    
                                                found_clusters += 1
                                                data_saved = True
                                                
                                if data_saved:
                                    print(f"🟢 [+] CID {cid}: [DEEP PATCH Selesai] Mengamankan {subs_in_this_cid} Kode!")
                                
                                if not data_saved:
                                    fallback_name = None
                                    try:
                                        url_any_sub = f"https://api.chronicles.sbs/core/v1/contest/submissions?contest_id={cid}&limit=1"
                                        async with session.get(url_any_sub, headers=headers, timeout=3.0) as r_sub:
                                            if r_sub.status == 200:
                                                d_sub = await r_sub.json()
                                                subs = d_sub.get("result", {}).get("submissions", [])
                                                if subs:
                                                    sid_any = subs[0].get("submission_id")
                                                    url_det = f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid_any}"
                                                    async with session.get(url_det, headers=headers, timeout=3.0) as r_det:
                                                        if r_det.status == 200:
                                                            d_det = await r_det.json()
                                                            fallback_name = d_det.get("result", {}).get("contest_name")
                                    except: pass

                                    if not fallback_name and problems: fallback_name = f"SOAL: {problems[0].get('title', 'Unknown')}"
                                    if not fallback_name and scoreboard: fallback_name = f"AKTIVITAS: {scoreboard[0].get('username', 'Peserta Rahasia')}"
                                    if not fallback_name: fallback_name = f"DATA KOSONG (CID {cid})"

                                    cat = "📂 OTHER (LAINNYA)"
                                    hari_folder = fallback_name.upper()[:25] 
                                    tanggal_folder = "(Cluster)"
                                    
                                    dt_now = datetime.now()
                                    hari_indo = nama_hari[dt_now.weekday()]
                                    tanggal_indo = f"{dt_now.day:02d} {nama_bulan[dt_now.month]} {dt_now.year}"
                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                    
                                    jam_indo = f"Selesai: {datetime.utcfromtimestamp(sc_updated_at).strftime('%H:%M')} WIB" if sc_updated_at > 0 else "Waktu Tidak Diketahui"
                                    dt_str = dt_now.strftime("%Y-%m-%d %H:%M:%S")
                                    lv = "UMUM"
                                    
                                    async with db_lock:
                                        conn = sqlite3.connect(DB_DEEPSCAN, timeout=10)
                                        c = conn.cursor()
                                        c.execute('''INSERT OR REPLACE INTO contest_list 
                                                     (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                  (cid, fallback_name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                        conn.commit()
                                        conn.close()
                                        
                                    found_clusters += 1
                                    print(f"🟠 [?] CID {cid}: [DEEP PATCHED] Detektif -> {fallback_name}")
                                
                                await asyncio.sleep(1)

                    else:
                        print(f"🔴 [-] CID {cid}: HTTP Error {resp.status} (Skip)")
            except Exception as e:
                print(f"🔴 [!] CID {cid}: Timeout API / Jaringan Gagal -> {str(e)[:50]}")

            processed_count += 1
            
            if not scan_controller["stop"]:
                if time.time() - last_edit_time > 2.0 or processed_count == total_scans:
                    last_edit_time = time.time()
                    bar = "▓" * int(20 * processed_count // total_scans) + "░" * (20 - int(20 * processed_count // total_scans))
                    try: await msg.edit(content=f"🩹 `[DEEP PATCH]` **Menambal Gudang Data...**\n⏳ Progres: `[{bar}]` {processed_count}/{total_scans}\n> 🎯 Ditambal: `{found_clusters}` Cluster | 💾 Kode Baru: `{saved_submissions}`")
                    except: pass
            
            await asyncio.sleep(0.05)

    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_cid(cid, session) for cid in missing_cids]
        await asyncio.gather(*tasks)

    if scan_controller["stop"]:
        await msg.edit(content=f"🛑 **DEEP PATCH DIBATALKAN:**\n> 💾 Tersimpan: `{found_clusters}` Cluster & `{saved_submissions}` Kode baru sebelum di-stop.")
    else:
        await msg.edit(content=f"✅ **DEEP PATCH SELESAI:**\n> 💾 Total Ditambal: `{found_clusters}` Cluster Valid\n> 💾 Total Kode C++ Baru: `{saved_submissions}`\n> Gudang Database kini sudah sinkron tanpa perlu mengulang!")

@bot.command()
@is_owner()
async def rescan(ctx, start_id: int = None, end_id: int = None):
    try: await ctx.message.delete()
    except: pass

    global scan_controller, last_scanned_cid
    scan_controller["stop"] = False 

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scan_state (key TEXT PRIMARY KEY, value INTEGER)''')
    
    max_cid_query = c.execute("SELECT MAX(cid) FROM contest_list").fetchone()[0]
    max_cid = max_cid_query if max_cid_query else 0

    if start_id is None:
        start_id = max_cid + 1
        saved_end = c.execute("SELECT value FROM scan_state WHERE key='target_end'").fetchone()
        
        if saved_end and saved_end[0] >= start_id:
            end_id = saved_end[0]
        else:
            end_id = start_id + 299 
            c.execute("INSERT OR REPLACE INTO scan_state (key, value) VALUES ('target_end', ?)", (end_id,))
    else:
        if end_id is None: end_id = start_id + 299
        c.execute("INSERT OR REPLACE INTO scan_state (key, value) VALUES ('target_end', ?)", (end_id,))
        
    conn.commit()
    conn.close()

    last_scanned_cid = start_id
    total_scans = end_id - start_id + 1

    msg = await ctx.send(f"📡 `[RADAR]` Menyiapkan **Stable Hybrid Scan**...\n> 🔄 **Mode:** Memulai dari CID `{start_id}` s/d `{end_id}`")
    
    nama_hari = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    nama_bulan = {1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'}
    
    found_count, processed_count = 0, 0
    
    sem = asyncio.Semaphore(15) 
    bash_lock = asyncio.Lock()  
    db_lock = asyncio.Lock()
    headers = {"Authorization": f"Bearer {TOKEN_API}"}

    async def process_cid(cid, session):
        nonlocal found_count, processed_count
        global scan_controller, last_scanned_cid

        if scan_controller["stop"]:
            processed_count += 1
            return

        async with sem:
            url_score = f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}"
            try:
                async with session.get(url_score, headers=headers, timeout=5.0) as resp:
                    if resp.status == 400:
                        print(f"🟡 [-] CID {cid}: HTTP 400 Bad Request (Insta-Skip)")
                    elif resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        scoreboard = result.get("scoreboard", [])
                        problems = result.get("problems", [])
                        
                        sc_updated_at = result.get("scoreboard_updated_at", 0) 
                        
                        if len(scoreboard) == 0 and len(problems) == 0:
                            print(f"⚪ [-] CID {cid}: Kosong / Tidak ada partisipan (Insta-Skip)")
                        else:
                            async with bash_lock:
                                if scan_controller["stop"]: return

                                print(f"🔍 [*] CID {cid}: [PROSES] Ada partisipan! Bash ffuf SEDANG mengekstrak data...")
                                process = await asyncio.create_subprocess_exec(
                                    "bash", "nexus_core.sh", str(cid), "1",
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await process.communicate()
                                output = stdout.decode().strip()
                                error_output = stderr.decode().strip()

                                data_saved = False
                                bash_reason = "Output kosong."
                                if error_output: bash_reason = f"System Error -> {error_output[:100]}"

                                for line in output.split('\n'):
                                    if line.startswith("NEXUS_EMPTY|") or line.startswith("NEXUS_NO_ACC|"):
                                        bash_reason = line.split("|")[1]
                                    elif line.startswith("NEXUS_DATA|"):
                                        p = line.split("|")
                                        if len(p) >= 18:
                                            name = p[1].strip()
                                            iso_time = p[4] 
                                            
                                            try:
                                                dt_first = datetime.strptime(iso_time[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=7)
                                                waktu_mulai = dt_first - timedelta(minutes=15)
                                                
                                                if sc_updated_at > 0: waktu_selesai = datetime.utcfromtimestamp(sc_updated_at) + timedelta(hours=7) + timedelta(minutes=10)
                                                else: waktu_selesai = dt_first + timedelta(hours=2)
                                                    
                                                jam_indo = f"{waktu_mulai.strftime('%H:%M')} - {waktu_selesai.strftime('%H:%M')} WIB (Est)"
                                                hari_indo = nama_hari[waktu_mulai.weekday()]
                                                tanggal_indo = f"{waktu_mulai.day:02d} {nama_bulan[waktu_mulai.month]} {waktu_mulai.year}"
                                                dt_str = waktu_mulai.strftime("%Y-%m-%d %H:%M:%S")
                                            except:
                                                jam_indo, hari_indo, tanggal_indo, dt_str = "Unknown", "Unknown", "Unknown", "Unknown"

                                            if not re.search(r"(?i)(praktikum|remedia|kelas|lv|sesi|kuis|tugas)", name): 
                                                cat = "📂 OTHER (LAINNYA)"
                                                hari_folder = name.upper()[:25] 
                                                tanggal_folder = "(Cluster)"    
                                                cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                                lv = "UMUM"
                                            else:
                                                cat, cls_folder, lv = parse_cluster_name(name)
                                                hari_folder = hari_indo
                                                tanggal_folder = tanggal_indo
                                            
                                            async with db_lock:
                                                conn = sqlite3.connect(DB_NAME, timeout=10)
                                                c = conn.cursor()
                                                c.execute('''INSERT OR REPLACE INTO contest_list 
                                                             (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                          (cid, name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                                conn.commit()
                                                conn.close()
                                                
                                            found_count += 1
                                            data_saved = True
                                            print(f"🟢 [+] CID {cid}: [SELESAI] Data SECURED & RAPI! -> {name} | Estimasi: {jam_indo}")
                                        break 
                                
                                if not data_saved:
                                    fallback_name = None
                                    try:
                                        url_any_sub = f"https://api.chronicles.sbs/core/v1/contest/submissions?contest_id={cid}&limit=1"
                                        async with session.get(url_any_sub, headers=headers, timeout=3.0) as r_sub:
                                            if r_sub.status == 200:
                                                d_sub = await r_sub.json()
                                                subs = d_sub.get("result", {}).get("submissions", [])
                                                if subs:
                                                    sid_any = subs[0].get("submission_id")
                                                    url_det = f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid_any}"
                                                    async with session.get(url_det, headers=headers, timeout=3.0) as r_det:
                                                        if r_det.status == 200:
                                                            d_det = await r_det.json()
                                                            fallback_name = d_det.get("result", {}).get("contest_name")
                                    except: pass

                                    if not fallback_name and problems: fallback_name = f"SOAL: {problems[0].get('title', 'Unknown')}"
                                    if not fallback_name and scoreboard: fallback_name = f"AKTIVITAS: {scoreboard[0].get('username', 'Peserta Rahasia')}"
                                    if not fallback_name: fallback_name = f"DATA KOSONG (CID {cid})"

                                    cat = "📂 OTHER (LAINNYA)"
                                    hari_folder = fallback_name.upper()[:25] 
                                    tanggal_folder = "(Cluster)"
                                    
                                    dt_now = datetime.now()
                                    hari_indo = nama_hari[dt_now.weekday()]
                                    tanggal_indo = f"{dt_now.day:02d} {nama_bulan[dt_now.month]} {dt_now.year}"
                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                    
                                    jam_indo = f"Selesai: {datetime.utcfromtimestamp(sc_updated_at).strftime('%H:%M')} WIB" if sc_updated_at > 0 else "Waktu Tidak Diketahui"
                                    dt_str = dt_now.strftime("%Y-%m-%d %H:%M:%S")
                                    lv = "UMUM"
                                    
                                    async with db_lock:
                                        conn = sqlite3.connect(DB_NAME, timeout=10)
                                        c = conn.cursor()
                                        c.execute('''INSERT OR REPLACE INTO contest_list 
                                                     (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                  (cid, fallback_name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                        conn.commit()
                                        conn.close()
                                        
                                    found_count += 1
                                    print(f"🟠 [?] CID {cid}: [SELESAI] Diselamatkan Detektif -> {fallback_name}")
                                
                                await asyncio.sleep(1)

                    else:
                        print(f"🔴 [-] CID {cid}: HTTP Error {resp.status} (Skip)")
            except Exception as e:
                print(f"🔴 [!] CID {cid}: Timeout API / Jaringan Gagal -> {str(e)[:50]}")

            last_scanned_cid = max(last_scanned_cid, cid) 
            processed_count += 1
            
            if not scan_controller["stop"]:
                if processed_count % 10 == 0 or processed_count == total_scans:
                    bar = "▓" * int(20 * processed_count // total_scans) + "░" * (20 - int(20 * processed_count // total_scans))
                    try: await msg.edit(content=f"📡 `[RADAR]` **Stable Hybrid Scan**\n⏳ Progres: `[{bar}]` {processed_count}/{total_scans}\n> 🎯 Diamankan: `{found_count}` Cluster.")
                    except: pass
            
            await asyncio.sleep(0.05)

    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_cid(cid, session) for cid in range(start_id, end_id + 1)]
        await asyncio.gather(*tasks)

    if scan_controller["stop"]:
        await msg.edit(content=f"🛑 **RESCAN DIBATALKAN:**\n> 💾 Tersimpan: `{found_count}` Cluster Valid sebelum di-stop.\n> 📌 Angka Terakhir: `~{last_scanned_cid}`")
    else:
        await msg.edit(content=f"✅ **RESCAN STABIL SELESAI:**\n> 💾 Total Tersimpan: `{found_count}` Cluster Valid\n> Ketik **`!list`** untuk membuka Hierarki Kategori.")

@bot.command()
@is_owner()
async def patch(ctx, start_id: int, end_id: int):
    try: await ctx.message.delete()
    except: pass

    global scan_controller, last_scanned_cid
    scan_controller["stop"] = False 

    conn = sqlite3.connect(DB_NAME)
    existing_records = conn.cursor().execute("SELECT cid FROM contest_list WHERE cid BETWEEN ? AND ?", (start_id, end_id)).fetchall()
    conn.close()
    
    existing_cids = {row[0] for row in existing_records}

    last_scanned_cid = start_id
    total_scans = end_id - start_id + 1

    msg = await ctx.send(f"🩹 `[PATCH ENGINE]` Menyiapkan Penambalan...\n> 🎯 **Target:** CID `{start_id}` s/d `{end_id}`")
    
    nama_hari = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    nama_bulan = {1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'}
    
    found_count, processed_count = 0, 0
    last_edit_time = time.time() 
    
    sem = asyncio.Semaphore(15) 
    bash_lock = asyncio.Lock()  
    db_lock = asyncio.Lock()
    headers = {"Authorization": f"Bearer {TOKEN_API}"}

    async def process_cid(cid, session):
        nonlocal found_count, processed_count, last_edit_time
        global scan_controller, last_scanned_cid

        if scan_controller["stop"]:
            processed_count += 1
            return

        if cid in existing_cids:
            print(f"🔵 [~] CID {cid}: Sudah tersimpan di DB (Skip Cepat)")
            processed_count += 1
            
            if not scan_controller["stop"]:
                if time.time() - last_edit_time > 2.0 or processed_count == total_scans:
                    last_edit_time = time.time()
                    bar = "▓" * int(20 * processed_count // total_scans) + "░" * (20 - int(20 * processed_count // total_scans))
                    try: await msg.edit(content=f"🩹 `[PATCH ENGINE]` **Menambal Database...**\n⏳ Progres: `[{bar}]` {processed_count}/{total_scans}\n> 🎯 Ditambal: `{found_count}` Cluster baru.")
                    except: pass
            
            await asyncio.sleep(0.01)
            return

        async with sem:
            url_score = f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}"
            try:
                async with session.get(url_score, headers=headers, timeout=5.0) as resp:
                    if resp.status == 400:
                        print(f"🟡 [-] CID {cid}: HTTP 400 Bad Request (Insta-Skip)")
                    elif resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        scoreboard = result.get("scoreboard", [])
                        problems = result.get("problems", [])
                        
                        sc_updated_at = result.get("scoreboard_updated_at", 0) 
                        
                        if len(scoreboard) == 0 and len(problems) == 0:
                            print(f"⚪ [-] CID {cid}: Kosong / Tidak ada partisipan (Insta-Skip)")
                        else:
                            async with bash_lock:
                                if scan_controller["stop"]: return

                                print(f"🔍 [*] CID {cid}: [PROSES] Ada partisipan! Bash ffuf SEDANG mengekstrak data...")
                                process = await asyncio.create_subprocess_exec(
                                    "bash", "nexus_core.sh", str(cid), "1",
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await process.communicate()
                                output = stdout.decode().strip()
                                error_output = stderr.decode().strip()

                                data_saved = False
                                bash_reason = "Output kosong."
                                if error_output: bash_reason = f"System Error -> {error_output[:100]}"

                                for line in output.split('\n'):
                                    if line.startswith("NEXUS_EMPTY|") or line.startswith("NEXUS_NO_ACC|"):
                                        bash_reason = line.split("|")[1]
                                    elif line.startswith("NEXUS_DATA|"):
                                        p = line.split("|")
                                        if len(p) >= 18:
                                            name = p[1].strip()
                                            iso_time = p[4] 
                                            
                                            try:
                                                dt_first = datetime.strptime(iso_time[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=7)
                                                waktu_mulai = dt_first - timedelta(minutes=15)
                                                
                                                if sc_updated_at > 0: waktu_selesai = datetime.utcfromtimestamp(sc_updated_at) + timedelta(hours=7) + timedelta(minutes=10)
                                                else: waktu_selesai = dt_first + timedelta(hours=2)
                                                    
                                                jam_indo = f"{waktu_mulai.strftime('%H:%M')} - {waktu_selesai.strftime('%H:%M')} WIB (Est)"
                                                hari_indo = nama_hari[waktu_mulai.weekday()]
                                                tanggal_indo = f"{waktu_mulai.day:02d} {nama_bulan[waktu_mulai.month]} {waktu_mulai.year}"
                                                dt_str = waktu_mulai.strftime("%Y-%m-%d %H:%M:%S")
                                            except:
                                                jam_indo, hari_indo, tanggal_indo, dt_str = "Unknown", "Unknown", "Unknown", "Unknown"

                                            if not re.search(r"(?i)(praktikum|remedia|kelas|lv|sesi|kuis|tugas)", name): 
                                                cat = "📂 OTHER (LAINNYA)"
                                                hari_folder = name.upper()[:25] 
                                                tanggal_folder = "(Cluster)"    
                                                cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                                lv = "UMUM"
                                            else:
                                                cat, cls_folder, lv = parse_cluster_name(name)
                                                hari_folder = hari_indo
                                                tanggal_folder = tanggal_indo
                                            
                                            async with db_lock:
                                                conn = sqlite3.connect(DB_NAME, timeout=10)
                                                c = conn.cursor()
                                                c.execute('''INSERT OR REPLACE INTO contest_list 
                                                             (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                          (cid, name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                                conn.commit()
                                                conn.close()
                                                
                                            found_count += 1
                                            data_saved = True
                                            print(f"🟢 [+] CID {cid}: [SELESAI] Data SECURED & RAPI! -> {name}")
                                        break 
                                
                                if not data_saved:
                                    fallback_name = None
                                    try:
                                        url_any_sub = f"https://api.chronicles.sbs/core/v1/contest/submissions?contest_id={cid}&limit=1"
                                        async with session.get(url_any_sub, headers=headers, timeout=3.0) as r_sub:
                                            if r_sub.status == 200:
                                                d_sub = await r_sub.json()
                                                subs = d_sub.get("result", {}).get("submissions", [])
                                                if subs:
                                                    sid_any = subs[0].get("submission_id")
                                                    url_det = f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid_any}"
                                                    async with session.get(url_det, headers=headers, timeout=3.0) as r_det:
                                                        if r_det.status == 200:
                                                            d_det = await r_det.json()
                                                            fallback_name = d_det.get("result", {}).get("contest_name")
                                    except: pass

                                    if not fallback_name and problems: fallback_name = f"SOAL: {problems[0].get('title', 'Unknown')}"
                                    if not fallback_name and scoreboard: fallback_name = f"AKTIVITAS: {scoreboard[0].get('username', 'Peserta Rahasia')}"
                                    if not fallback_name: fallback_name = f"DATA KOSONG (CID {cid})"

                                    cat = "📂 OTHER (LAINNYA)"
                                    hari_folder = fallback_name.upper()[:25] 
                                    tanggal_folder = "(Cluster)"
                                    
                                    dt_now = datetime.now()
                                    hari_indo = nama_hari[dt_now.weekday()]
                                    tanggal_indo = f"{dt_now.day:02d} {nama_bulan[dt_now.month]} {dt_now.year}"
                                    cls_folder = f"{hari_indo}, {tanggal_indo}" 
                                    
                                    jam_indo = f"Selesai: {datetime.utcfromtimestamp(sc_updated_at).strftime('%H:%M')} WIB" if sc_updated_at > 0 else "Waktu Tidak Diketahui"
                                    dt_str = dt_now.strftime("%Y-%m-%d %H:%M:%S")
                                    lv = "UMUM"
                                    
                                    async with db_lock:
                                        conn = sqlite3.connect(DB_NAME, timeout=10)
                                        c = conn.cursor()
                                        c.execute('''INSERT OR REPLACE INTO contest_list 
                                                     (cid, name, dt_start, hari, tanggal, jam, cat_folder, class_folder, level_folder) 
                                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                                  (cid, fallback_name, dt_str, hari_folder, tanggal_folder, jam_indo, cat, cls_folder, lv))
                                        conn.commit()
                                        conn.close()
                                        
                                    found_count += 1
                                    print(f"🟠 [?] CID {cid}: [PATCHED] Diselamatkan Detektif -> {fallback_name}")
                                
                                await asyncio.sleep(1)

                    else:
                        print(f"🔴 [-] CID {cid}: HTTP Error {resp.status} (Skip)")
            except Exception as e:
                print(f"🔴 [!] CID {cid}: Timeout API / Jaringan Gagal -> {str(e)[:50]}")

            last_scanned_cid = max(last_scanned_cid, cid) 
            processed_count += 1
            
            if not scan_controller["stop"]:
                if time.time() - last_edit_time > 2.0 or processed_count == total_scans:
                    last_edit_time = time.time()
                    bar = "▓" * int(20 * processed_count // total_scans) + "░" * (20 - int(20 * processed_count // total_scans))
                    try: await msg.edit(content=f"🩹 `[PATCH ENGINE]` **Menambal Database...**\n⏳ Progres: `[{bar}]` {processed_count}/{total_scans}\n> 🎯 Ditambal: `{found_count}` Cluster baru.")
                    except: pass
            
            await asyncio.sleep(0.05)

    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_cid(cid, session) for cid in range(start_id, end_id + 1)]
        await asyncio.gather(*tasks)

    if scan_controller["stop"]:
        await msg.edit(content=f"🛑 **PATCH DIBATALKAN:**\n> 💾 Tersimpan: `{found_count}` Data baru berhasil ditambal.")
    else:
        await msg.edit(content=f"✅ **PATCH SELESAI:**\n> 💾 Total Ditambal: `{found_count}` Cluster baru")

@bot.command(name="list")
async def folder_list(ctx):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    
    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    records = c.execute("SELECT cid, name, hari, tanggal, jam, cat_folder, class_folder, level_folder FROM contest_list ORDER BY dt_start ASC").fetchall()
    conn.close()

    if not records: 
        status_mode = "DEEPSCAN (Offline)" if SYSTEM_MODE == "OFFLINE" else "RESCAN (Online)"
        return await ctx.send(f"❌ **DATABASE KOSONG.** Harap jalankan scanning untuk mode **{status_mode}** terlebih dahulu.")

    grouped = {}
    for cid, name, hari, tgl, jam, cat, cls, lv in records:
        day_key = f"{hari}, {tgl}"
        if cat not in grouped: grouped[cat] = {}
        if day_key not in grouped[cat]: grouped[cat][day_key] = {}
        if cls not in grouped[cat][day_key]: grouped[cat][day_key][cls] = {}
        if lv not in grouped[cat][day_key][cls]: grouped[cat][day_key][cls][lv] = []
        
        grouped[cat][day_key][cls][lv].append({"cid": cid, "name": name, "jam": jam})

    status_judul = "[OFFLINE DB]" if SYSTEM_MODE == "OFFLINE" else "[ONLINE DB]"
    embed = discord.Embed(title=f"📂 NEXUS DIRECTORY EXPLORER {status_judul}", description=f"Membaca dari: `{db_target}`\nJelajahi folder praktikum secara bertingkat.", color=0x00d2ff)
    
    view = NexusNavView()
    view.current_embed = embed
    view.add_item(CategorySelect(grouped, view))
    
    await ctx.send(embed=embed, view=view)


# ═══════════════════════════════════════════════════════════════
# NEXUS ENGINE
# ═══════════════════════════════════════════════════════════════

@bot.command()
async def nexus(ctx, start_cid: str, limit: str):
    try: await ctx.message.delete()
    except: pass
    if not start_cid.isdigit() or not limit.isdigit(): return

    target_limit = int(limit)
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME

    # ==========================================================
    # 🟢 SMART CACHE (Sekarang Membaca 12 Kolom dari Database)
    # ==========================================================
    conn = sqlite3.connect(db_target)
    existing_submissions = conn.cursor().execute(
        "SELECT sid, uid, uname, score, penalty, code, problem, difficulty, status, time_submitted, type, accepted FROM submissions WHERE cid = ? ORDER BY CAST(score AS INTEGER) DESC", 
        (start_cid,)
    ).fetchall()
    conn.close()

    is_cache_sufficient = len(existing_submissions) >= target_limit or (target_limit >= 1000 and len(existing_submissions) > 5)

    if is_cache_sufficient and SYSTEM_MODE == "OFFLINE":
        amount_to_fetch = min(target_limit, len(existing_submissions))
        await ctx.send(f"⚡ **INSTANT CACHE HIT!**\n> Data ditarik dari `{db_target}`. Menampilkan `{amount_to_fetch}` baris...")
        
        for idx, row in enumerate(existing_submissions[:target_limit], 1):
            sid, uid, uname, score, penalty, raw_code, problem, diff_label, status_str, time_val, type_val, acc_val = row
            
            display_code = raw_code.replace("```", "'''")
            if len(display_code) > 3800: display_code = display_code[:3800] + "\n\n// ... [KODE MELEBIHI 3800 KARAKTER]"
            
            n = chr(10)
            t = chr(96) * 3 
            desc_teks = f"**📄 Source Code:**{n}{t}cpp{n}{display_code}{n}{t}"
            embed = discord.Embed(title="🎯 DATA SECURED (CACHED)", description=desc_teks, color=0x00FF00)
            
            task_info = (f"📌 **Problem**: `{problem}`\n🆔 **Submission ID**: `{sid}`\n"
                         f"📊 **Difficulty**: {diff_label}\n📝 **Status**: `{status_str}`")
            embed.add_field(name="📋 Task Information", value=task_info, inline=False)
            
            try: submitted_time = format_time(time_val)
            except: submitted_time = time_val
            embed.add_field(name="⏰ Submitted", value=submitted_time, inline=False)
            
            meta_display = (f"🌐 **Contest ID**: `{start_cid}` | 🏆 **Type**: `{type_val}`\n👤 **User ID**: `{uid}` | 🏷️ **Username**: **{uname}**\n"
                            f"📊 **Score**: `{score}` | ✅ **Accepted**: `{acc_val}`")
            embed.add_field(name="📑 Technical Metadata", value=meta_display, inline=False)
            embed.set_footer(text=f"Cached Entry #{idx} • Mode: {SYSTEM_MODE}")
            
            view = NexusActions(cid=start_cid, sid=sid, uid=uid)
            await ctx.send(embed=embed, view=view)
            await asyncio.sleep(0.5) 
            
        await ctx.send(f"✅ **EKSTRAKSI INSTAN SELESAI.**")
        return 

    # ==========================================================
    # 🔴 LIVE FFUF SCRAPING 
    # ==========================================================
    await ctx.send(f"🚀 **OVERSEER ENGINE INITIATED**\n> Mode: LIVE Scraping FFUF\n> Target CID: **{start_cid}** | Limit: **{limit}**")
    
    process = await asyncio.create_subprocess_exec(
        "bash", "nexus_core.sh", start_cid, limit,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    found_count = 0
    while True:
        line = await process.stdout.readline()
        if not line: break
        output = line.decode().strip()

        if output.startswith("NEXUS_EMPTY|"): await ctx.send(f"⚪ `[EMPTY]` {output.split('|')[1]}")
        elif output.startswith("NEXUS_NO_ACC|"): await ctx.send(f"🟡 `[NO ACCEPTED]` {output.split('|')[1]}")
        elif output.startswith("NEXUS_TOP|"):
            p = output.split("|")
            if len(p) >= 5: 
                embed_top = discord.Embed(title=f"🏆 FIRST BLOOD - CLUSTER {p[1]}", color=0xFFD700)
                embed_top.description = f"**{p[2]}** adalah Peringkat #1 di Cluster ini!\n> **Score**: `{p[3]}` | **Penalty**: `{p[4]}`"
                await ctx.send(embed=embed_top)
        elif output.startswith("NEXUS_DATA|"):
            p = output.split("|")
            if len(p) >= 18:
                found_count += 1
                try:
                    raw_code = base64.b64decode(p[7] + "==").decode('utf-8', errors='ignore')
                    raw_code = raw_code.replace("```", "'''") 
                    if len(raw_code) > 3800: raw_code = raw_code[:3800] + "\n\n// ... [KODE MELEBIHI 3800 KARAKTER]"
                except: raw_code = "// Decode Error."

                try: diff_label = get_difficulty(p[13]) 
                except: diff_label = "Unknown"
                status_str = f"{p[15]} ({p[13]}/{p[14]})"
                
                # 🟢 SIMPAN KE DATABASE YANG SEDANG AKTIF DENGAN 13 DATA LENGKAP
                save_to_db(p[6], p[17], p[8], p[3], p[9], p[11], raw_code, p[2], diff_label, status_str, p[4], p[16], p[10], db_target)
                
                n = chr(10)
                t = chr(96) * 3 
                desc_teks = f"**📄 Source Code:**{n}{t}cpp{n}{raw_code}{n}{t}"
                
                embed = discord.Embed(title="🎯 DATA SECURED (LIVE)", description=desc_teks, color=THEME_COLOR)
                task_info = (f"📌 **Problem**: `{p[2]}`\n🆔 **Submission ID**: `{p[6]}`\n"
                             f"📊 **Difficulty**: {diff_label}\n📝 **Status**: `{status_str}`")
                embed.add_field(name="📋 Task Information", value=task_info, inline=False)
                
                try: time_submitted = format_time(p[4])
                except: time_submitted = p[4]
                embed.add_field(name="⏰ Submitted", value=time_submitted, inline=False)
                
                meta_display = (f"🌐 **Contest ID**: `{p[17]}` | 🏆 **Type**: `{p[16]}`\n👤 **User ID**: `{p[8]}` | 🏷️ **Username**: **{p[3]}**\n"
                                f"📊 **Score**: `{p[9]}` | ✅ **Accepted**: `{p[10]}`")
                embed.add_field(name="📑 Technical Metadata", value=meta_display, inline=False)
                embed.set_footer(text=f"• Mode: Online Scraping FFUF")
                embed.set_footer(text=f"Audit Entry #{found_count} • Cluster Name: {p[1]}")
                
                view = NexusActions(cid=start_cid, sid=p[6], uid=p[8])
                await ctx.send(embed=embed, view=view)

    await process.wait()

    if found_count == 0: await ctx.send(f"❌ **SCAN COMPLETE:** Tidak ada data yang diamankan.")

@bot.command()
async def nexusdiscord(ctx, start_cid: str, limit: str):
    try: await ctx.message.delete()
    except: pass
    if not start_cid.isdigit() or not limit.isdigit(): return

    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME

    await ctx.send(f"🚀 **NEXUS ENGINE INITIATED**\n> Eksekusi Tunggal CID: **{start_cid}** (Limit: {limit})")
    
    status_msg = await ctx.send("⏳ `[SYSTEM]` Menghubungi server dan mengekstrak data...")
    
    process = await asyncio.create_subprocess_exec(
        "bash", "nexus_core.sh", start_cid, limit,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    found_count = 0
    while True:
        line = await process.stdout.readline()
        if not line: break
        output = line.decode().strip()

        if output.startswith("NEXUS_EMPTY|"): 
            await ctx.send(f"⚪ `[EMPTY]` {output.split('|')[1]}")
        elif output.startswith("NEXUS_NO_ACC|"): 
            await ctx.send(f"🟡 `[NO ACCEPTED]` {output.split('|')[1]}")
        elif output.startswith("NEXUS_TOP|"):
            p = output.split("|")
            if len(p) >= 5:
                embed_top = discord.Embed(title=f"🏆 FIRST BLOOD - CLUSTER {p[1]}", color=0xFFD700)
                embed_top.description = f"**{p[2]}** adalah Peringkat #1 di Cluster ini!\n> **Score**: `{p[3]}` | **Penalty**: `{p[4]}`"
                await ctx.send(embed=embed_top)
        elif output.startswith("NEXUS_DATA|"):
            p = output.split("|")
            
            if len(p) >= 18:
                found_count += 1
                
                try: await status_msg.edit(content=f"🔄 `[SYSTEM]` Mengunduh dan memproses data ke-**{found_count}**...")
                except: pass

                try:
                    raw_code = base64.b64decode(p[7] + "==").decode('utf-8', errors='ignore')
                    raw_code = raw_code.replace("```", "'''") 
                    if len(raw_code) > 3800: raw_code = raw_code[:3800] + "\n\n// ... [KODE MELEBIHI BATAS]"
                except: raw_code = "// Decode Error."

                try: diff_label = get_difficulty(p[13])
                except: diff_label = "Unknown"
                status_str = f"{p[15]} ({p[13]}/{p[14]})"

                # 🟢 PERBAIKAN: Menyimpan dengan 13 Parameter
                save_to_db(p[6], p[17], p[8], p[3], p[9], p[11], raw_code, p[2], diff_label, status_str, p[4], p[16], p[10], db_target)
                
                n = chr(10)
                t = chr(96) * 3 
                code_text = str(raw_code)
                desc_teks = f"**📄 Source Code:**{n}{t}cpp{n}{code_text}{n}{t}"
                
                embed = discord.Embed(title="🎯 DATA SECURED", description=desc_teks, color=THEME_COLOR)
                task_info = (f"📌 **Problem**: `{p[2]}`\n🆔 **Submission ID**: `{p[6]}`\n"
                             f"📊 **Difficulty**: {diff_label}\n📝 **Status**: `{status_str}`")
                embed.add_field(name="📋 Task Information", value=task_info, inline=False)
                
                try: submitted_time = format_time(p[4])
                except: submitted_time = p[4]
                embed.add_field(name="⏰ Submitted", value=submitted_time, inline=False)
                
                meta_display = (f"🌐 **Contest ID**: `{p[17]}` | 🏆 **Type**: `{p[16]}`\n👤 **User ID**: `{p[8]}` | 🏷️ **Username**: **{p[3]}**\n"
                                f"📊 **Score**: `{p[9]}` | ✅ **Accepted**: `{p[10]}`")
                embed.add_field(name="📑 Technical Metadata", value=meta_display, inline=False)
                embed.set_footer(text=f"Audit Entry #{found_count} • Target CID Tunggal: {p[17]} • DB: {db_target}")
                
                view = NexusActions(cid=start_cid, sid=p[6], uid=p[8])
                await ctx.send(embed=embed, view=view)

    if found_count > 0:
        try: await status_msg.edit(content=f"✅ `[SYSTEM]` Eksekusi selesai. Berhasil menarik **{found_count}** data ke `{db_target}`.")
        except: pass
    else:
        try: await status_msg.edit(content=f"❌ `[SYSTEM]` Tidak ada data yang berhasil diamankan di CID {start_cid}.")
        except: pass

    await process.wait()

@bot.command()
async def snipe(ctx, clusters: str):
    try: await ctx.message.delete()
    except: pass
    cids = []
    if "-" in clusters:
        start, end = map(int, clusters.split("-"))
        cids = [str(i) for i in range(start, end + 1)]
    elif "," in clusters: cids = clusters.split(",")
    else: cids = [clusters]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    for cid in cids:
        if cid in active_snipers:
            active_snipers[cid].cancel()
            del active_snipers[cid]
            c.execute("DELETE FROM active_snipers WHERE cid=?", (cid,))
            await ctx.send(f"🛑 **RADAR MATI:** Cluster `{cid}` dihentikan.")
        else:
            c.execute("INSERT OR REPLACE INTO active_snipers (cid, channel_id) VALUES (?, ?)", (cid, ctx.channel.id))
            active_snipers[cid] = bot.loop.create_task(sniper_loop(cid, ctx.channel))
            await ctx.send(f"🎯 **RADAR AKTIF:** Cluster `{cid}` dipantau.")
    
    conn.commit()
    conn.close()

@bot.command()
async def analyze(ctx, cid: str, sid: str):
    if ctx.message.author != bot.user:
        try: await ctx.message.delete()
        except: pass
    if not gemini_api_key: return

    proses = await ctx.send(f"🧠 **AI AUDIT:** Mengambil data...")
    try:
        headers = {"Authorization": f"Bearer {TOKEN_API}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid}", headers=headers) as resp:
                res = await resp.json()
                
        code = base64.b64decode(res['result']['source_code'] + "==").decode('utf-8', errors='ignore')
        prompt = (f"Jelaskan logika utama dari kode C++ ini dengan JELAS dan PADAT . "
                  f"Abaikan penjelasan header/include. Fokus pada algoritma penyelesaian soal '{res['result']['problem_title']}'. "
                  f"Berikan 2 contoh Input & Output singkat di akhir. Kode: {code}")
        
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as r_resp:
                r = await r_resp.json()
                
        if 'candidates' in r: ai_text = r['candidates'][0]['content']['parts'][0]['text']
        else: ai_text = "⚠️ Gagal dianalisis."

        embed = discord.Embed(title=f"🧠 AI ANALYSIS: {res['result']['problem_title']}", description=ai_text[:4000], color=THEME_COLOR)
        await ctx.send(embed=embed)
        await proses.delete()
    except Exception as e: await proses.edit(content=f"❌ **ERROR:** {str(e)}")

# =====================================================================
# COMMAND BARU: !skynet (MASS PLAGIARISM SCANNER)
# =====================================================================
@bot.command()
@is_owner()
async def skynet(ctx, cid: str):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    
    m = await ctx.send(f"🕸️ `[SKYNET]` Mengaktifkan Mass Plagiarism Scanner untuk CID `{cid}`...\n*(Menyilangkan ribuan algoritma, mohon tunggu sebentar)*")
    
    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    c.execute("SELECT sid, uname, code FROM submissions WHERE cid=?", (str(cid),))
    records = c.fetchall()
    conn.close()
    
    if len(records) < 2:
        return await m.edit(content="❌ Tidak cukup data untuk dibandingkan (minimal butuh 2 peserta).")
    
    # Filter kode yang kosong atau error
    valid_records = [r for r in records if r[2] and r[2] != "// Decode Error." and len(r[2]) > 20]
    
    results = []
    # Mengkombinasikan semua orang dengan semua orang (O(N^2) Algoritma)
    pairs = list(itertools.combinations(valid_records, 2))
    
    for (sid1, uname1, code1), (sid2, uname2, code2) in pairs:
        sim = difflib.SequenceMatcher(None, code1, code2).ratio() * 100
        if sim >= 80.0: # Hanya pantau yang kemiripannya di atas 80% (Batas Kritis)
            results.append((sim, uname1, uname2, sid1, sid2))
    
    # Urutkan dari yang paling menjiplak (100%) ke bawah
    results.sort(reverse=True, key=lambda x: x[0])
    top_results = results[:10] # Ambil Top 10 Kasus Terparah
    
    if not top_results:
        return await m.edit(content=f"✅ **SKYNET BERSIH:** Tidak ditemukan kemiripan mencolok (di atas 80%) di CID `{cid}`.")
    
    desc = ""
    for i, (sim, u1, u2, s1, s2) in enumerate(top_results, 1):
        desc += f"**#{i}** | Kemiripan: **{sim:.1f}%**\n👤 `{u1}` ⚔️ `{u2}`\n*(SID: {s1} & {s2})*\n\n"
        
    embed = discord.Embed(title=f"🚨 SKYNET PLAGIARISM REPORT (CID: {cid})", description=desc, color=0xFF0000)
    embed.set_footer(text="Gunakan !diff <cid> <sid1> <sid2> untuk melihat perbandingan kodenya.")
    await m.edit(content=None, embed=embed)

# =====================================================================
# COMMAND BARU: !stats (TEXT-BASED VISUAL ANALYTICS - ANTI CRASH)
# =====================================================================
@bot.command()
async def stats(ctx, cid: str):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    
    m = await ctx.send(f"📊 `[ANALYTICS]` Memproses visualisasi data untuk CID `{cid}`...")
    
    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    c.execute("SELECT score, status FROM submissions WHERE cid=?", (str(cid),))
    records = c.fetchall()
    conn.close()
    
    if not records:
        return await m.edit(content="❌ Data kosong. Tidak ada yang bisa divisualisasikan.")
    
    total_data = len(records)
    
    # Menghitung Status
    status_counts = {"Accepted": 0, "Wrong Answer": 0, "Other/Error": 0}
    for _, status in records:
        if status and "Accepted" in status:
            status_counts["Accepted"] += 1
        elif status and "Wrong Answer" in status:
            status_counts["Wrong Answer"] += 1
        else:
            status_counts["Other/Error"] += 1
            
    # Membuat Grafik Batang Karakter (ASCII Bar Chart)
    # Kita pakai total 15 karakter blok untuk bar maksimal (100%)
    def make_bar(count, total):
        if total == 0: return "░" * 15
        percentage = count / total
        fill_length = int(15 * percentage)
        return "█" * fill_length + "░" * (15 - fill_length)

    bar_acc = make_bar(status_counts["Accepted"], total_data)
    bar_wa = make_bar(status_counts["Wrong Answer"], total_data)
    bar_other = make_bar(status_counts["Other/Error"], total_data)
    
    # Menghitung Persentase
    pct_acc = (status_counts["Accepted"] / total_data) * 100 if total_data > 0 else 0
    pct_wa = (status_counts["Wrong Answer"] / total_data) * 100 if total_data > 0 else 0
    pct_other = (status_counts["Other/Error"] / total_data) * 100 if total_data > 0 else 0

    # Menyusun Tampilan Chart ala Terminal Cyberpunk
    chart_display = (
        f"🟢 **Accepted**\n"
        f"`[{bar_acc}]` **{pct_acc:.1f}%** ({status_counts['Accepted']}/{total_data})\n\n"
        f"🔴 **Wrong Answer**\n"
        f"`[{bar_wa}]` **{pct_wa:.1f}%** ({status_counts['Wrong Answer']}/{total_data})\n\n"
        f"🟡 **Other/Error**\n"
        f"`[{bar_other}]` **{pct_other:.1f}%** ({status_counts['Other/Error']}/{total_data})"
    )
    
    embed = discord.Embed(
        title=f"📈 SUBMISSION ANALYTICS (CID: {cid})", 
        description=f"**Metrik Performa Kelas:**\n\n{chart_display}", 
        color=0x00d2ff
    )
    embed.set_footer(text=f"Total Partisipan: {total_data} • Database: {db_target} • Mode: {SYSTEM_MODE}")
    
    await m.delete()
    await ctx.send(embed=embed)

@bot.command()
async def diff(ctx, cid: str, sid1: str, sid2: str):
    if ctx.message.author != bot.user:
        try: await ctx.message.delete()
        except: pass
    st = await ctx.send("🕵️ **DIFF ENGINE:** Membandingkan...")
    headers = {"Authorization": f"Bearer {TOKEN_API}"}
    try:
        def get_c(sid):
            r = requests.get(f"https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id={cid}&submission_id={sid}", headers=headers).json()
            return base64.b64decode(r['result']['source_code'] + "==").decode('utf-8', errors='ignore')
        sim = round(difflib.SequenceMatcher(None, get_c(sid1), get_c(sid2)).ratio() * 100, 2)
        await ctx.send(embed=discord.Embed(title="🕵️ PLAGIARISM CHECK", description=f"Kemiripan: **{sim}%**", color=THEME_COLOR))
        await st.delete()
    except: await st.edit(content="❌ **ERROR.**")

# =====================================================================
# COMMAND BARU: !audit (SMART AUDIT + BISA DI-STOP PAKSA)
# =====================================================================
@bot.command()
@is_owner()
async def audit(ctx, start_id: int, end_id: int):
    try: await ctx.message.delete()
    except: pass

    global SYSTEM_MODE, scan_controller
    scan_controller["stop"] = False # 🟢 Reset rem darurat
    
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME

    m = await ctx.send(f"🧠 `[SMART AUDIT]` Memindai integritas CID `{start_id}` s/d `{end_id}` di `{db_target}`...\n*(Mengabaikan selisih peserta zonk. Fokus pada data cacat/kosong. Pantau Console!)*")

    conn = sqlite3.connect(db_target)
    c = conn.cursor()
    c.execute("SELECT cid, name FROM contest_list WHERE cid BETWEEN ? AND ?", (start_id, end_id))
    contests = c.fetchall()
    conn.close()

    if not contests:
        return await m.edit(content="❌ Tidak ada data folder di rentang tersebut untuk diaudit.")

    headers = {"Authorization": f"Bearer {TOKEN_API}"}
    sem = asyncio.Semaphore(10)
    
    to_repair = [] 

    async def check_cid(cid, name, session):
        if scan_controller["stop"]: return # 🟢 Cek rem darurat saat diagnosa
        
        async with sem:
            conn = sqlite3.connect(db_target)
            c = conn.cursor()
            
            c.execute("SELECT COUNT(*) FROM submissions WHERE cid=?", (str(cid),))
            db_count = c.fetchone()[0]

            c.execute("""SELECT sid, code, problem, time_submitted, uname, status 
                         FROM submissions WHERE cid=? AND (
                             uid IS NULL OR uid = '' OR
                             uname IS NULL OR uname = '' OR uname = 'Unknown' OR
                             score IS NULL OR score = '' OR
                             penalty IS NULL OR penalty = '' OR
                             code IS NULL OR code = '' OR code = '// Decode Error.' OR
                             problem IS NULL OR problem = '' OR problem = 'Unknown' OR
                             difficulty IS NULL OR difficulty = '' OR difficulty = 'Unknown' OR
                             status IS NULL OR status = '' OR status = 'Unknown' OR
                             time_submitted IS NULL OR time_submitted = '' OR time_submitted = 'Unknown' OR
                             type IS NULL OR type = '' OR type = 'Unknown' OR
                             accepted IS NULL OR accepted = ''
                         )""", (str(cid),))
            corrupt_rows = c.fetchall()
            conn.close()
            
            corrupt_count = len(corrupt_rows)
            api_count = 0 
            
            url = f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}"
            try:
                async with session.get(url, headers=headers, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        scoreboard = data.get("result", {}).get("scoreboard", [])
                        api_count = len(scoreboard)
            except Exception as e:
                print(f"🟡 [AUDIT] CID {cid}: Gagal mengecek ke server API ({str(e)[:30]})")

            reasons = set()
            
            if db_count == 0 and api_count > 0:
                reasons.add(f"Kosong Total (Server punya {api_count} partisipan)")
            if corrupt_count > 0:
                reasons.add(f"{corrupt_count} Baris Cacat/Null/Decode Error")
            
            if reasons:
                reason_str = " | ".join(reasons)
                print(f"🔴 [AUDIT] CID {cid} ({name[:15]}): DETEKSI -> {reason_str}")
                to_repair.append((cid, name, reason_str))
            else:
                if db_count > 0 or (db_count == 0 and api_count == 0):
                    print(f"🟢 [AUDIT] CID {cid} ({name[:15]}): AMAN (Lolos Uji Integritas)")

    async with aiohttp.ClientSession() as session:
        tasks = [check_cid(cid, name, session) for cid, name in contests]
        await asyncio.gather(*tasks)

    if scan_controller["stop"]:
        return await m.edit(content="🛑 **AUDIT DIBATALKAN OLEH SYSTEM KILL SWITCH.**")

    if not to_repair:
        return await m.edit(content=f"✅ **AUDIT BERSIH ({len(contests)} Cluster):**\nSistem mengabaikan selisih data wajar (peserta tanpa *Accepted*). 100% data tersimpan dalam kondisi sehat.")

    await m.edit(content=f"⚠️ `[AUDIT ENGINE]` Ditemukan **{len(to_repair)}** CID yang benar-benar cacat.\n🔨 **Memulai proses Smart Auto-Repair...**")
    
    repair_results = []
    for cid, name, reason in to_repair:
        if scan_controller["stop"]: # 🟢 Cek rem darurat saat proses repair
            print("🛑 [AUDIT] Auto-Repair dihentikan paksa!")
            repair_results.append("🛑 **PROSES AUTO-REPAIR DIHENTIKAN PAKSA.**")
            break

        print(f"🛠️ [REPAIR] Menambal ulang CID {cid} ...")
        process = await asyncio.create_subprocess_exec(
            "bash", "nexus_core.sh", str(cid), "1000",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode().strip()
        
        saved_count = 0
        for line in output.split('\n'):
            if line.startswith("NEXUS_DATA|"):
                p = line.split("|")
                if len(p) >= 18:
                    try: raw_code = base64.b64decode(p[7] + "==").decode('utf-8', errors='ignore')
                    except: raw_code = "// Decode Error."
                    try: diff_label = get_difficulty(p[13]) 
                    except: diff_label = "Unknown"
                    status_str = f"{p[15]} ({p[13]}/{p[14]})"
                    
                    save_to_db(p[6], p[17], p[8], p[3], p[9], p[11], raw_code, p[2], diff_label, status_str, p[4], p[16], p[10], db_target)
                    saved_count += 1
        
        if saved_count > 0:
            print(f"✅ [REPAIR] CID {cid} Berhasil Dipulihkan! ({saved_count} valid submissions)")
            repair_results.append(f"✅ **CID {cid}** - {saved_count} diperbaiki. *(Diagnosis: {reason})*")
        else:
            print(f"⚪ [REPAIR] CID {cid} Tetap Kosong (Valid: Peserta memang zonk/tanpa Accepted).")
            repair_results.append(f"⚪ **CID {cid}** - Dibiarkan kosong *(Valid: Tidak ada jawaban Accepted dari peserta).*")
        
        await asyncio.sleep(0.5)

    report_text = "\n".join(repair_results[:15])
    if len(repair_results) > 15: report_text += f"\n\n*...dan {len(repair_results) - 15} CID lainnya.*"
    
    status_title = "🛑 LAPORAN AUTO-REPAIR (DIBATALKAN)" if scan_controller["stop"] else "🔨 LAPORAN SMART AUTO-REPAIR"
    embed = discord.Embed(title=status_title, description=report_text, color=0xFF0000 if scan_controller["stop"] else 0x00FF00)
    embed.set_footer(text=f"Total Cluster diaudit: {len(contests)} | Diproses: {len(to_repair)}")
    await m.edit(content=f"🎉 **SMART AUDIT SELESAI/TERHENTI!** Data cacat telah diobati, false positive diabaikan.", embed=embed)

@bot.command()
@is_owner()
async def clean(ctx):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    # 🟢 SAFETY LOCK: Blokir jika sedang di mode OFFLINE
    if SYSTEM_MODE == "OFFLINE":
        return await ctx.send("❌ **AKSES DITOLAK:** Perintah `!clean` dikunci. Hanya bisa digunakan pada mode **ONLINE (FFUF)** untuk melindungi data Deepscan Anda.", delete_after=8)
    
    # Jika lolos (berarti mode LIVE), maka hapus DB_NAME
    db_target = DB_NAME
    
    conn = sqlite3.connect(db_target)
    conn.cursor().execute("DELETE FROM submissions")
    conn.commit()
    conn.close()
    await ctx.send(f"🧹 **DATABASE CLEANED:** Data Submissions di `{db_target}` dilenyapkan.", delete_after=5)

@bot.command()
@is_owner()
async def dbclean(ctx):
    try: await ctx.message.delete()
    except: pass
    
    global SYSTEM_MODE
    # 🟢 SAFETY LOCK: Blokir jika sedang di mode OFFLINE
    if SYSTEM_MODE == "OFFLINE":
        return await ctx.send("❌ **AKSES DITOLAK:** Perintah `!dbclean` dikunci. Hanya bisa digunakan pada mode **ONLINE (FFUF)** untuk melindungi data Deepscan Anda.", delete_after=8)
    
    # Jika lolos (berarti mode LIVE), maka hapus DB_NAME
    db_target = DB_NAME
    
    conn = sqlite3.connect(db_target)
    conn.cursor().execute("DELETE FROM contest_list")
    conn.commit()
    conn.close()
    await ctx.send(f"🧹 **DATABASE CLEANED:** Data Folder SQLite di `{db_target}` dilenyapkan.", delete_after=5)

@bot.command()
@is_owner()
async def status(ctx):
    lat, upt = round(bot.latency * 1000), int(time.time() - start_time)
    h, m = divmod(upt // 60, 60)
    
    global SYSTEM_MODE
    db_target = DB_DEEPSCAN if SYSTEM_MODE == "OFFLINE" else DB_NAME
    
    conn = sqlite3.connect(db_target)
    try:
        db_count = conn.cursor().execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    except: db_count = 0
    
    try:
        idx_count = conn.cursor().execute("SELECT COUNT(*) FROM contest_list").fetchone()[0]
    except: idx_count = 0
    conn.close()
    
    embed = discord.Embed(title="📊 SYSTEM STATUS", description=f"Ping: `{lat}ms` | Uptime: `{h}j {m}m`\nDatabase Aktif: `{db_target}`\n🗄️ **Submissions:** `{db_count}`\n📁 **Folders:** `{idx_count}`", color=0x00d2ff)
    await ctx.send(embed=embed)

@bot.command()
async def latest(ctx, start: int = 340):
    m = await ctx.send("📡 `[RADAR] Memindai...`")
    headers = {"Authorization": f"Bearer {TOKEN_API}"}
    h_v = start
    for cid in range(start, start + 30):
        try:
            r = requests.get(f"https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id={cid}", headers=headers).json()
            if r.get("result"): h_v = cid
        except: break
    await m.edit(content=f"🎯 **RADAR SCAN:** ID Cluster Terbaru: **{h_v}**")

@bot.command()
@is_owner()
async def delete(ctx, amount: int):
    try: await ctx.message.delete()
    except: pass
    deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == bot.user or m.content.startswith('!'))
    msg = await ctx.send(f"🧹 **PURGED:** {len(deleted)} messages.")
    await msg.delete(delay=3)

@bot.command()
@is_owner()
async def stop(ctx):
    try: await ctx.message.delete()
    except: pass
    
    global scan_controller, active_snipers
    
    # 1. Matikan semua operasi Looping (Deepscan, Patch, Audit, Rescan)
    scan_controller["stop"] = True
    
    # 2. Matikan operasi Radar Sniper
    sniper_count = len(active_snipers)
    for task in active_snipers.values(): 
        task.cancel()
    active_snipers.clear()
    
    # Hapus jejak radar dari database agar tidak jalan saat restart
    conn = sqlite3.connect(DB_NAME)
    conn.cursor().execute("DELETE FROM active_snipers")
    conn.commit()
    conn.close()
    
    # 3. Tampilkan Laporan Canggih ke Discord
    embed = discord.Embed(title="🛑 GLOBAL KILL SWITCH ACTIVATED", description="Semua operasi latar belakang telah diputus secara paksa oleh sistem keamanan.", color=0xFF0000)
    embed.add_field(name="📡 Radar Sniper", value=f"`{sniper_count}` target radar berhasil dimatikan.", inline=False)
    embed.add_field(name="⚙️ Heavy Engines", value="`!deepscan`, `!patch`, `!rescan`, dan `!audit` telah dihentikan secara instan.", inline=False)
    embed.set_footer(text="Nexus System Standby. Aman terkendali.")
    
    await ctx.send(embed=embed, delete_after=15)

keep_alive()
if token_rahasia: bot.run(token_rahasia)
