import logging
import sqlite3
import asyncio
import time
import os
import random
import html
import tempfile
import shutil
from datetime import datetime
from typing import List, Dict

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile
)
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.enums import ChatMemberStatus
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram import exceptions
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from dotenv import load_dotenv

# .env faylidan konfiguratsiyani yuklash
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "6607605946"))
PORT = int(os.getenv("PORT", 10000))

# Token tekshiruvi
if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN topilmadi!")
    exit(1)

print(f"✅ Token: {TOKEN[:10]}...")
print(f"✅ Admin: {ADMIN_ID}")
print(f"✅ Port: {PORT}")

# Bot va Dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==================== WEB SERVER ====================
async def handle_health_check(request):
    return web.Response(text="🤖 Bot is running perfectly!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    app.router.add_get('/health', handle_health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, host='0.0.0.0', port=PORT)
    await site.start()
    print(f"🌐 Web server started on port {PORT}")

async def main():
    # Log sozlamalari
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Botni yaratish
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    
    try:
        logging.info("Bot starting...")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Bot error: {e}")
    finally:
        await bot.session.close()


# Botni ishga tushirish (Global obyekt)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# User states dictionary
user_state = {}

# Database initialization
def init_db():
    """
    Ma'lumotlar bazasini ishga tushirish va kerakli jadvallarni yaratish.
    Agar jadvallar allaqachon mavjud bo'lsa, ularni qayta yaratmaydi.
    """
    DB_NAME = 'anime_bot.db'
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [table[0] for table in cursor.fetchall()]

        if 'db_version' not in existing_tables:
            cursor.execute('''
                CREATE TABLE db_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("INSERT INTO db_version (version) VALUES (1)")
            logging.info("'db_version' jadvali yaratildi")
        
        if 'user_subscriptions' not in existing_tables:
            cursor.execute('''
                CREATE TABLE user_subscriptions (
                    user_id INTEGER PRIMARY KEY,
                    subscribed_channels TEXT,
                    last_check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'user_subscriptions' jadvali yaratildi")
        if 'post_templates' not in existing_tables:
            cursor.execute('''
        CREATE TABLE post_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER UNIQUE NOT NULL,
            template_name TEXT UNIQUE NOT NULL,
            template_content TEXT NOT NULL,
            is_default BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Standart shablonni qo'shish (template_id = 1)
            default_template = "<blockquote>\n<b>- {title}</b>  \n<b>- QISM - {episode_number}</b>\n</blockquote>"
            cursor.execute('''
        INSERT INTO post_templates (template_id, template_name, template_content, is_default) 
        VALUES (?, ?, ?, ?)
    ''', (1, "Default", default_template, True))  # template_id = 1
            logging.info("'post_templates' jadvali yaratildi va standart shablon qo'shildi")
        if 'anime' not in existing_tables:
            cursor.execute('''
                CREATE TABLE anime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    country TEXT,
                    language TEXT,
                    year INTEGER,
                    genre TEXT,
                    description TEXT,
                    image TEXT,
                    video TEXT,
                    is_private BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'anime' jadvali yaratildi")
        else:
            cursor.execute("PRAGMA table_info(anime)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'is_private' not in columns:
                cursor.execute("ALTER TABLE anime ADD COLUMN is_private BOOLEAN DEFAULT FALSE")
                logging.info("'anime' jadvaliga is_private maydoni qo'shildi")

        if 'episodes' not in existing_tables:
            cursor.execute('''
                CREATE TABLE episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anime_code TEXT NOT NULL,
                    episode_number INTEGER NOT NULL,
                    video_file_id TEXT NOT NULL,
                    is_private BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (anime_code) REFERENCES anime(code) ON DELETE CASCADE,
                    UNIQUE(anime_code, episode_number)
                )
            ''')
            logging.info("'episodes' jadvali yaratildi")
        else:
            cursor.execute("PRAGMA table_info(episodes)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'is_private' not in columns:
                cursor.execute("ALTER TABLE episodes ADD COLUMN is_private BOOLEAN DEFAULT FALSE")
                logging.info("'episodes' jadvaliga is_private maydoni qo'shildi")

        if 'stickers' not in existing_tables:
            cursor.execute('''
                CREATE TABLE stickers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sticker_file_id TEXT UNIQUE NOT NULL,
                    used_for TEXT NOT NULL DEFAULT 'welcome',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'stickers' jadvali yaratildi")
        
        if 'ongoing_anime' not in existing_tables:
            cursor.execute('''
                CREATE TABLE ongoing_anime (
                    anime_code TEXT PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (anime_code) REFERENCES anime(code) ON DELETE CASCADE
                )
            ''')
            logging.info("'ongoing_anime' jadvali yaratildi")

        if 'admins' not in existing_tables:
            cursor.execute('''
                CREATE TABLE admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (added_by) REFERENCES admins(user_id)
                )
            ''')
            cursor.execute("INSERT OR IGNORE INTO admins (user_id, username, added_by) VALUES (?, ?, ?)", 
                          (ADMIN_ID, "owner", ADMIN_ID))
            logging.info("'admins' jadvali yaratildi")

        if 'channels' not in existing_tables:
            cursor.execute('''
                CREATE TABLE channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_type TEXT CHECK(channel_type IN ('mandatory', 'post', 'additional_mandatory', 'group')),
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'channels' jadvali yaratildi")

        if 'favorites' not in existing_tables:
            cursor.execute('''
                CREATE TABLE favorites (
                    user_id INTEGER,
                    anime_code TEXT,
                    PRIMARY KEY (user_id, anime_code),
                    FOREIGN KEY (anime_code) REFERENCES anime(code) ON DELETE CASCADE
                )
            ''')
            logging.info("'favorites' jadvali yaratildi")

        if 'subscribers' not in existing_tables:
            cursor.execute('''
                CREATE TABLE subscribers (
                    user_id INTEGER PRIMARY KEY,
                    notifications BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'subscribers' jadvali yaratildi")

        if 'user_redirects' not in existing_tables:
            cursor.execute('''
                CREATE TABLE user_redirects (
                    user_id INTEGER PRIMARY KEY,
                    redirect_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'user_redirects' jadvali yaratildi")

        if 'questions' not in existing_tables:
            cursor.execute('''
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'questions' jadvali yaratildi")

        if 'quiz_participants' not in existing_tables:
            cursor.execute('''
                CREATE TABLE quiz_participants (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    correct_answers INTEGER DEFAULT 0,
                    total_answers INTEGER DEFAULT 0,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'quiz_participants' jadvali yaratildi")

        if 'chatbot_responses' not in existing_tables:
            cursor.execute('''
                CREATE TABLE chatbot_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logging.info("'chatbot_responses' jadvali yaratildi")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anime_code ON anime(code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_anime_code ON episodes(anime_code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_question ON questions(question)")
        # init_db() funksiyasi ichida, post_templates jadvalini yaratish qismidan keyin:
        cursor.execute("PRAGMA table_info(post_templates)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'font_style' not in columns:
         cursor.execute("ALTER TABLE post_templates ADD COLUMN font_style TEXT DEFAULT 'default'")
        logging.info("'post_templates' jadvaliga font_style maydoni qo'shildi")
        conn.commit()
        logging.info("Ma'lumotlar bazasi muvaffaqiyatli ishga tushirildi")
    except sqlite3.Error as e:
        logging.error(f"Ma'lumotlar bazasi xatosi: {e}")
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        logging.error(f"Kutilmagan xato: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

try:
        
    init_db()
except Exception as e:
    logging.critical(f"Failed to initialize database: {e}")
    raise SystemExit("Database initialization failed")

# ==================== HELPER FUNCTIONS ====================
from aiohttp import web
import json

# API uchun oddiy handlerlar
async def api_get_anime_list(request):
    """Barcha animelarni JSON sifatida qaytaradi"""
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT code, title, genre, image, video FROM anime ORDER BY created_at DESC")
    animes = cursor.fetchall()
    conn.close()

    anime_list = []
    for anime in animes:
        anime_list.append({
            'code': anime[0],
            'title': anime[1],
            'genre': anime[2],
            'image': anime[3],
            'video': anime[4]
        })

    return web.json_response(anime_list)

async def api_get_anime_episodes(request):
    """Berilgan anime kodi uchun epizodlarni JSON sifatida qaytaradi"""
    anime_code = request.match_info.get('anime_code')
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT episode_number, video_file_id FROM episodes WHERE anime_code = ? ORDER BY episode_number", (anime_code,))
    episodes = cursor.fetchall()
    conn.close()

    episode_list = []
    for ep in episodes:
        episode_list.append({
            'episode_number': ep[0],
            'video_file_id': ep[1]
        })

    return web.json_response(episode_list)

async def api_get_html_post_image(request):
    """HTML post uchun rasm generatsiya qiladi va URL qaytaradi"""
    try:
        anime_code = request.query.get('anime_code')
        episode_num = int(request.query.get('episode_num', 1)) # Default 1-qism
        desc = request.query.get('desc', 'Tavsif yo\'q')

        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT title, genre, image FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        conn.close()

        if not anime:
            return web.json_response({'error': 'Anime topilmadi'}, status=404)

        title, genre, image_file_id = anime

        if not image_file_id:
            return web.json_response({'error': 'Rasm topilmadi'}, status=404)

        # Rasmni generatsiya qilish
        bot_username = (await bot.get_me()).username
        image_path = await generate_html_post_image_pillow(
            title=title,
            desc=desc,
            genre=genre,
            file_id=image_file_id,
            bot_username=bot_username,
            anime_code=anime_code,
            episode_num=episode_num
        )

        # Bu yerda rasm faylini veb-server uchun statik URL ga saqlash kerak.
        # Oddiy yechim sifatida, rasmni vaqtinchalik papkaga saqlab, URL qaytarish.
        # E'tibor bering: Bu yechim faqat test uchun, ishlab chiqarishda statik fayllar serveri kerak.
        static_url = f"/static/{os.path.basename(image_path)}"
        # image_path ni server statik papkasiga ko'chirish kerak, lekin bu misolda oddiy qoldirilgan.

        return web.json_response({'image_url': static_url})

    except Exception as e:
        logging.error(f"HTML rasm generatsiyasi xatosi: {e}")
        return web.json_response({'error': str(e)}, status=500)

# Statik fayllar uchun oddiy handler (generate_html_post_image_pillow uchun)
async def handle_static_file(request):
    filename = request.match_info.get('filename')
    filepath = os.path.join(tempfile.gettempdir(), filename) # Vaqtinchalik papka
    if os.path.exists(filepath):
        return web.FileResponse(filepath)
    else:
        return web.Response(status=404)

# Veb ilovani sozlash
app = web.Application()
app.router.add_get('/api/anime', api_get_anime_list)
app.router.add_get('/api/anime/{anime_code}/episodes', api_get_anime_episodes)
app.router.add_get('/api/html_post_image', api_get_html_post_image)
app.router.add_get('/static/{filename}', handle_static_file)

# Bot va veb-serverni birgalikda ishga tushirish
async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8080) # Portni o'zgartirishingiz mumkin
    await site.start()
    print("Veb server http://localhost:8080 da ishga tushdi")

# Asosiy main() funksiyasini yangilash
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    try:
        # Veb serverni ishga tushirish
        await start_web_server()
        # Botni ishga tushirish
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Bot ishga tushirishda xatolik: {e}")
    finally:
        await bot.session.close()
async def is_owner(user_id: int) -> bool:
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM admins WHERE user_id = ? AND added_by = user_id", (user_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

async def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

async def validate_database(db_path: str) -> dict:
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        required_tables = {'anime', 'episodes', 'ongoing_anime', 'admins', 'channels'}
        missing_tables = required_tables - tables
        if missing_tables:
            return {
                "valid": False,
                "message": f"Quyidagi jadvallar topilmadi: {', '.join(missing_tables)}"
            }
        try:
            cursor.execute("SELECT code, title FROM anime LIMIT 1")
            cursor.execute("SELECT anime_code, episode_number FROM episodes LIMIT 1")
            cursor.execute("SELECT anime_code FROM ongoing_anime LIMIT 1")
            cursor.execute("SELECT user_id FROM admins LIMIT 1")
            cursor.execute("SELECT channel_id FROM channels LIMIT 1")
        except sqlite3.Error as e:
            return {
                "valid": False,
                "message": f"Jadval strukturasida xatolik: {str(e)}"
            }
        counts = {}
        cursor.execute("SELECT COUNT(*) FROM anime")
        counts['anime_count'] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM episodes")
        counts['episodes_count'] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ongoing_anime")
        counts['ongoing_count'] = cursor.fetchone()[0]
        counts['valid'] = True
        return counts
    except Exception as e:
        return {
            "valid": False,
            "message": f"Bazani tekshirishda xatolik: {str(e)}"
        }
    finally:
        if conn:
            conn.close()

async def check_admin(user_id: int, message=None, call=None, require_owner=False):
    if require_owner:
        if not await is_owner(user_id):
            if message:
                await message.answer("❌ Bu amalni faqat bot egasi bajarishi mumkin!")
            if call:
                await call.answer("❌ Bu amalni faqat bot egasi bajarishi mumkin!", show_alert=True)
            return False
        return True
    if not await is_admin(user_id):
        if message:
            await message.answer("❌ Siz admin emassiz!")
        if call:
            await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return False
    return True

# ==================== MUHIM TATAT: check_subscription funksiyasi qo'shildi ====================
async def check_subscription(user_id: int, show_message: bool = False, message: types.Message = None) -> bool:
    """Har doim Telegram API orqali real-time tekshirish — user_subscriptions jadvalidan foydalanilmaydi"""
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT channel_id 
            FROM channels 
            WHERE channel_type IN ('mandatory', 'additional_mandatory')
        """)
        channels = cursor.fetchall()
        conn.close()
        if not channels:
            return True
        for channel_id, in channels:
            try:
                member = await bot.get_chat_member(channel_id, user_id)
                if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                    if show_message and message:
                        await show_subscription_required(message)
                    return False
            except Exception:
                if show_message and message:
                    await show_subscription_required(message)
                return False
        return True
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik: {e}")
        return False

async def check_subscription_with_redirect(user_id: int, redirect_data: str = None, message: types.Message = None, call: types.CallbackQuery = None) -> bool:
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT channel_id, channel_name 
            FROM channels 
            WHERE channel_type IN ('mandatory', 'additional_mandatory')
            ORDER BY channel_type
        """)
        channels = cursor.fetchall()
        if not channels:
            conn.close()
            return True
        not_subscribed = []
        for channel_id, channel_name in channels:
            try:
                member = await bot.get_chat_member(channel_id, user_id)
                if member.status not in [
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.CREATOR
                ]:
                    not_subscribed.append((channel_id, channel_name))
            except Exception as e:
                logging.error(f"Kanal a'zoligini tekshirishda xato: {e}")
                not_subscribed.append((channel_id, channel_name))
        if redirect_data:
            cursor.execute("""
                INSERT OR REPLACE INTO user_redirects 
                (user_id, redirect_data, created_at) 
                VALUES (?, ?, ?)
            """, (user_id, redirect_data, datetime.now()))
            conn.commit()
        conn.close()
        if not_subscribed:
            if message:
                await show_subscription_required(message, not_subscribed, redirect_data)
            elif call:
                await show_subscription_required(call.message, not_subscribed, redirect_data)
            return False
        return True
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik: {e}")
        return False

async def show_subscription_required(message: types.Message, not_subscribed_channels: list = None, redirect_data: str = None):
    try:
        if not_subscribed_channels is None:
            conn = sqlite3.connect('anime_bot.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel_id, channel_name 
                FROM channels 
                WHERE channel_type IN ('mandatory', 'additional_mandatory')
                ORDER BY channel_type
            """)
            all_channels = cursor.fetchall()
            conn.close()
            not_subscribed_channels = []
            for channel_id, channel_name in all_channels:
                try:
                    member = await bot.get_chat_member(channel_id, message.from_user.id)
                    if member.status not in [
                        ChatMemberStatus.MEMBER,
                        ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.CREATOR
                    ]:
                        not_subscribed_channels.append((channel_id, channel_name))
                except Exception as e:
                    logging.error(f"Kanal a'zoligini tekshirishda xato: {e}")
                    not_subscribed_channels.append((channel_id, channel_name))
        # Agar barcha kanallarga obuna bo'lsa — animeni ochamiz
        if not not_subscribed_channels:
            if redirect_data and redirect_data.startswith("watch_"):
                anime_code = redirect_data.replace("watch_", "")
                await show_episodes_menu(message, anime_code, page=0)
            elif redirect_data and redirect_data.startswith("episode_"):
                parts = redirect_data.split('_')
                if len(parts) == 3:
                    anime_code = parts[1]
                    episode_num = int(parts[2])
                    await handle_episode_request_direct(message.from_user.id, anime_code, episode_num, message)
            else:
                # Oddiy xabar — hech qanday menyusiz
                await message.answer("✅ Obuna bo'ldingiz! Endi anime tomosha qilishingiz mumkin.")
            return
        # Faqat obuna bo'lmagan kanallar uchun tugmalar
        buttons = []
        for channel_id, channel_name in not_subscribed_channels:
            try:
                chat = await bot.get_chat(channel_id)
                if chat.username:
                    invite_link = f"https://t.me/{chat.username}"
                else:
                    invite_link = await chat.export_invite_link()
                buttons.append([InlineKeyboardButton(
                    text=f"❌ {chat.title} kanaliga obuna bo'lish",
                    url=invite_link
                )])
            except Exception as e:
                logging.error(f"Kanal linkini olishda xato: {e}")
                continue
        # Redirect ma'lumotini saqlash
        if redirect_data:
            conn = sqlite3.connect('anime_bot.db')
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_redirects 
                (user_id, redirect_data) 
                VALUES (?, ?)
            """, (message.from_user.id, redirect_data))
            conn.commit()
            conn.close()
        # "Obunani tekshirish" tugmasi
        buttons.append([InlineKeyboardButton(
            text="🔄 Obunani tekshirish",
            callback_data="check_subscription_redirect"
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            "⚠️ Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'lishingiz kerak:",
            reply_markup=keyboard
        )
    except Exception as e:
        logging.error(f"Obuna ko'rsatishda xatolik: {e}")
        await message.answer("Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")
async def check_subscription_callback_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    is_subscribed = await check_subscription(user_id, True, callback_query.message)
    if is_subscribed:
        await callback_query.message.delete()
        # show_main_menu o'rniga oddiy xabar
        await callback_query.message.answer("✅ Obuna bo'ldingiz! Botdan foydalanishingiz mumkin.")
    else:
        await callback_query.answer("Hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True)
async def search_and_send_anime(message: types.Message, search_term: str):
    """Anime qidirish va barcha qismlarni yuborish"""
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        # Kod bo'yicha qidirish
        cursor.execute("SELECT code, title FROM anime WHERE code = ?", (search_term,))
        anime = cursor.fetchone()
        
        # Nom bo'yicha qidirish
        if not anime:
            cursor.execute("SELECT code, title FROM anime WHERE LOWER(title) LIKE LOWER(?)", 
                          (f'%{search_term}%',))
            anime = cursor.fetchone()
        
        if not anime:
            await message.answer("❌ Bunday anime topilmadi. Iltimos, boshqa nom yoki kod kiriting.")
            return
            
        anime_code, anime_title = anime
        await message.answer(f"✅ {anime_title} animeni topdim! Barcha qismlar yuklanmoqda...")
        await show_episodes_menu(message, anime_code)
        
    except Exception as e:
        await message.answer(f"❌ Qidirishda xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()
# ==================== USER HANDLERS ====================

@dp.message(Command("start"))
async def user_start(message: types.Message, command: CommandObject):
    # 1. Avval obunani tekshiramiz
    if not await check_subscription(message.from_user.id):
        await show_subscription_required(message)
        return
    
    # 2. Agar /startda anime argumentlari berilgan bo'lsa - AVVAL TEKSHIRISH
    if command.args:
        if command.args.startswith("watch_"):
            anime_code = command.args.replace("watch_", "")
            await show_episodes_menu(message, anime_code)
            return
        elif command.args.startswith("episode_"):
            # ✅ SERIAL POST UCHUN YANGI QISIM
            parts = command.args.split('_')
            if len(parts) == 3:
                anime_code = parts[1]
                try:
                    episode_num = int(parts[2])
                    await handle_episode_request_direct(message.from_user.id, anime_code, episode_num, message)
                    return
                except ValueError:
                    pass  # Noto'g'ri format
    
    # 3. Shaxsiylashtirilgan xabar (faqat oddiy /start uchun)
    user_name = message.from_user.full_name
    welcome_text = f"🤝 Voy, {user_name}! Nihoyat keldingiz! Biz kutib o‘tirgan edik.\n\n"
    welcome_text += "💎 Bizning maxfiy kanalda eng yaxshi postlar va yangiliklar sizni kutmoqda. "
    welcome_text += "Tugmani bosishingiz bilan sirlar olamiga yo‘l o‘chilasiz!"
 

    # 4. Kanal tugmasi
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT channel_id, channel_name FROM channels WHERE channel_type = 'post' LIMIT 1")
        channel = cursor.fetchone()
        if channel:
            channel_id, channel_name = channel
            try:
                chat = await bot.get_chat(channel_id)
                channel_title = chat.title
                if chat.username:
                    channel_link = f"https://t.me/{chat.username}"
                else:
                    channel_link = await chat.export_invite_link()
            except:
                channel_title = channel_name or "Bizning kanal"
                channel_link = f"https://t.me/{channel_id}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"📢 {channel_title} kanaliga o'tish",
                    url=channel_link
                )]
            ])
            
            await message.answer(welcome_text, reply_markup=keyboard)
        else:
            await message.answer(welcome_text)
            
    except Exception as e:
        logging.error(f"Start handler xatosi: {e}")
        await message.answer(welcome_text)
    finally:
        conn.close()

# Anime qidirish uchun handler - ENG AVVAL QAYTA ISHLASH KERAK BO'LGAN XABARLAR

# ==================== ANIME QIDIRISH HANDLERI ====================



# ==================== GURUHLARDA ISHLASH ====================

@dp.message(F.text & F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: types.Message):
    """
    Guruhlarda faqat botga murojaat qilinganda ishlaydi
    """
    # Agar xabar botga murojaat qilmasa, e'tibor bermaymiz
    bot_username = (await bot.get_me()).username
    if not message.text or f"@{bot_username}" not in message.text:
        return
    
    # Botga murojaat qilingan qismini olib tashlaymiz
    search_term = message.text.replace(f"@{bot_username}", "").strip()
    
    if len(search_term) < 2:
        await message.reply("❌ Qidiruv uchun kamida 2 ta belgi kiriting.")
        return
    
    # Qidiruvni boshlash
    await search_and_send_all_episodes(message, search_term)

# ==================== YANGI: VIDEO YUBORISH FUNKSIYASI (TUGMASIZ) ====================

async def handle_episode_request_direct(user_id: int, anime_code: str, episode_num: int, message: types.Message):
    """Qismni yuborish - hech qanday tugmasiz, faqat video"""
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        
        # Anime nomini olish
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            return
            
        # Epizodni olish
        cursor.execute("""
            SELECT video_file_id 
            FROM episodes 
            WHERE anime_code = ? AND episode_number = ?
        """, (anime_code, episode_num))
        episode = cursor.fetchone()
        if not episode:
            return
            
        video_file_id = episode[0]
        
        # FAQAT VIDEO YUBORISH, HECH QANDAY TUGMA
        await message.answer_video(
            video=video_file_id,
            caption=f"🎬 {anime[0]} - {episode_num}-qism"
        )
        
    except Exception as e:
        logging.error(f"Video yuborishda xatolik: {str(e)}")
    finally:
        conn.close()

async def search_and_send_all_episodes(message: types.Message, search_term: str):
    """Anime qidirish va BARCHA qismlarni ketma-ket yuborish"""
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        # Debug
        logging.info(f"Qidiruv boshlandi: {search_term}")
        
        # 1. Kod bo'yicha aniq qidirish
        cursor.execute("SELECT code, title FROM anime WHERE code = ?", (search_term,))
        anime = cursor.fetchone()
        
        # 2. Agar kod bo'yicha topilmasa, nom bo'yicha qidirish
        if not anime:
            cursor.execute("SELECT code, title FROM anime WHERE LOWER(title) LIKE LOWER(?)", 
                          (f'%{search_term}%',))
            anime = cursor.fetchone()
        
        if not anime:
            await message.answer("❌ Bunday anime topilmadi. Iltimos, boshqa nom yoki kod kiriting.")
            return
            
        anime_code, anime_title = anime
        logging.info(f"Anime topildi: {anime_title} ({anime_code})")
        
        # 3. Barcha qismlarni olish
        cursor.execute("""
            SELECT episode_number 
            FROM episodes 
            WHERE anime_code = ?
            ORDER BY episode_number
        """, (anime_code,))
        episodes = cursor.fetchall()
        
        if not episodes:
            await message.answer("❌ Bu anime uchun hali qismlar qo'shilmagan!")
            return
        
        total_episodes = len(episodes)
        await message.answer(f"✅ **{anime_title}** animeni topdim! \n📺 {total_episodes} ta qism yuklanmoqda...")
        
        # 4. Barcha qismlarni ketma-ket yuborish
        sent_count = 0
        for ep in episodes:
            episode_num = ep[0]
            try:
                await handle_episode_request_direct(message.from_user.id, anime_code, episode_num, message)
                sent_count += 1
                
                # Har 3 qismdan keyin kichik kutish (spamdan qochish)
                if sent_count % 3 == 0:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                logging.error(f"{episode_num}-qism yuborishda xatolik: {str(e)}")
                continue
        
        # 5. Yakuniy xabar
        if sent_count > 0:
            await message.answer(f"✅ **{anime_title}**\n🎉 Barcha {sent_count} ta qism yuklandi!")
        else:
            await message.answer("❌ Hech qanday qism yuborilmadi. Iltimos, keyinroq urinib ko'ring.")
        
    except Exception as e:
        logging.error(f"Qidirishda xatolik: {str(e)}")
        await message.answer(f"❌ Qidirishda xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()
async def search_and_send_anime(message: types.Message, search_term: str):
    """Anime qidirish va barcha qismlarni yuborish"""
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        # Debug
        logging.info(f"Qidiruv boshlandi: {search_term}")
        
        # 1. Kod bo'yicha aniq qidirish
        cursor.execute("SELECT code, title FROM anime WHERE code = ?", (search_term,))
        anime = cursor.fetchone()
        
        # 2. Agar kod bo'yicha topilmasa, nom bo'yicha qidirish
        if not anime:
            cursor.execute("SELECT code, title FROM anime WHERE LOWER(title) LIKE LOWER(?)", 
                          (f'%{search_term}%',))
            anime = cursor.fetchone()
        
        if not anime:
            await message.answer("❌ Bunday anime topilmadi. Iltimos, boshqa nom yoki kod kiriting.")
            return
            
        anime_code, anime_title = anime
        logging.info(f"Anime topildi: {anime_title} ({anime_code})")
        
        await message.answer(f"✅ **{anime_title}** animeni topdim! Barcha qismlar yuklanmoqda...")
        await show_episodes_menu(message, anime_code)
        
    except Exception as e:
        logging.error(f"Qidirishda xatolik: {str(e)}")
        await message.answer(f"❌ Qidirishda xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()


@dp.callback_query(lambda call: call.data == "check_subscription_redirect")
async def check_subscription_redirect_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    try:
        is_subscribed = await check_subscription_with_redirect(user_id)
        if is_subscribed:
            try:
                await callback_query.message.delete()
            except:
                pass
            await process_redirect(user_id, call=callback_query)
        else:
            await callback_query.answer("Hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True)
    except Exception as e:
        logging.error(f"Obuna tekshirish callbackida xatolik: {e}")
        await callback_query.answer("Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.", show_alert=True)

@dp.callback_query(lambda call: call.data.startswith("watch_"))
async def handle_watch_request(call: types.CallbackQuery):
    anime_code = call.data.replace("watch_", "")
    is_subscribed = await check_subscription_with_redirect(
        call.from_user.id, 
        f"watch_{anime_code}", 
        call=call
    )
    if not is_subscribed:
        return
    await call.answer()
    await show_episodes_menu(call.message, anime_code, page=0)

# ==================== ANIME FUNCTIONS ====================

async def send_media_post(message: types.Message, media_type: str, media_file: str, anime_data: dict, is_channel: bool = False):
    caption = f"""
╭──────────────────────
├‣ <b>Nomi:</b> {anime_data['title']}
├‣ <b>Qism:</b> {anime_data['episodes_count']} ta
├‣ <b>Tili:</b> {anime_data['language']}
├‣ <b>Davlati:</b> {anime_data['country']}
├‣ <b>Janrlari:</b> {anime_data['genre']}
╰──────────────────────

    """
    if is_channel:
        bot_username = (await bot.get_me()).username
        buttons = [
            [InlineKeyboardButton(
                text="✨Tomosha Qilish✨", 
                url=f"https://t.me/{bot_username}?start=watch_{anime_data['code']}"
            )]
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="✨Tomosha Qilish✨", callback_data=f"watch_{anime_data['code']}")],
            [InlineKeyboardButton(text="⭐️ Sevimlilarga Qo'shish", callback_data=f"add_fav_{anime_data['code']}")]
        ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
        resize_keyboard=True
    )
    try:
        if media_type == 'photo':
            await message.answer_photo(
                photo=media_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        elif media_type == 'video':
            await message.answer_video(
                video=media_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Media post yuborishda xatolik: {e}")
        await message.answer("❌ Post yuborishda xatolik yuz berdi.")

async def show_anime_details(message: types.Message, anime_code: str):
    conn = None
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, country, language, year, genre, image, video 
            FROM anime WHERE code = ?
        """, (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            await message.answer("❌ Bunday kodli anime topilmadi.")
            return
        title, country, language, year, genre, image, video = anime
        cursor.execute("SELECT COUNT(*) FROM episodes WHERE anime_code = ?", (anime_code,))
        episodes_count = cursor.fetchone()[0]
        buttons = [
            [InlineKeyboardButton(text="📺 Barcha Qismlarni Ko'rish", callback_data=f"watch_{anime_code}")],
            [InlineKeyboardButton(text="⭐️ Sevimlilarga Qo'shish", callback_data=f"add_fav_{anime_code}")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        if video:
            await message.answer_video(
                video=video,
                caption=f"🎬 {title}\n🌍 {country} | 🇺🇿 {language}\n📅 {year} | 🎞 {genre}\n📺 {episodes_count} qism",
                reply_markup=keyboard
            )
        elif image:
            await message.answer_photo(
                photo=image,
                caption=f"🎬 {title}\n🌍 {country} | 🇺🇿 {language}\n📅 {year} | 🎞 {genre}\n📺 {episodes_count} qism",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                f"🎬 {title}\n🌍 {country} | 🇺🇿 {language}\n📅 {year} | 🎞 {genre}\n📺 {episodes_count} qism",
                reply_markup=keyboard
            )
    except Exception as e:
        logging.error(f"Anime details error: {str(e)}")
        await message.answer("❌ Anime ma'lumotlarini yuklashda xatolik yuz berdi.")
    finally:
        if conn:
            conn.close()

async def send_text_post(message: types.Message, anime_data: dict):
    caption = f"""
╭──────────────────────
├‣ <b>Nomi:</b> {anime_data['title']}
├‣ <b>Qism:</b> {anime_data['episodes_count']} ta
├‣ <b>Tili:</b> {anime_data['language']}
├‣ <b>Davlati:</b> {anime_data['country']}
├‣ <b>Janrlari:</b> {anime_data['genre']}
╰──────────────────────
🔢 <b>Kodi:</b> {anime_data['code']}
    """
    buttons = [
        [InlineKeyboardButton(text="✨Tomosha Qilish✨", callback_data=f"watch_{anime_data['code']}")],
        [InlineKeyboardButton(text="⭐️ Sevimlilarga Qo'shish", callback_data=f"add_fav_{anime_data['code']}")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def process_redirect(user_id: int, message: types.Message = None, call: types.CallbackQuery = None):
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT redirect_data FROM user_redirects WHERE user_id = ?", (user_id,))
        redirect_data = cursor.fetchone()
        if not redirect_data:
            conn.close()
            # show_main_menu o'rniga oddiy xabar
            await (message if message else call.message).answer("✅ Obuna bo'ldingiz! Botdan foydalanishingiz mumkin.")
            return
        redirect_data = redirect_data[0]
        if redirect_data.startswith("watch_"):
            anime_code = redirect_data.replace("watch_", "")
            await show_episodes_menu(message if message else call.message, anime_code, page=0)
        elif redirect_data.startswith("episode_"):
            parts = redirect_data.split('_')
            if len(parts) == 3:
                anime_code = parts[1]
                episode_num = int(parts[2])
                await handle_episode_request_direct(user_id, anime_code, episode_num, message if message else call.message)
        cursor.execute("DELETE FROM user_redirects WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Redirect qayta ishlashda xatolik: {e}")
        await (message if message else call.message).answer("✅ Obuna bo'ldingiz! Botdan foydalanishingiz mumkin.")

async def handle_episode_request_direct(user_id: int, anime_code: str, episode_num: int, message: types.Message):
    """Qismni yuborish - hech qanday tugmasiz"""
    try:
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            return
            
        cursor.execute("""
            SELECT video_file_id 
            FROM episodes 
            WHERE anime_code = ? AND episode_number = ?
        """, (anime_code, episode_num))
        episode = cursor.fetchone()
        if not episode:
            return
            
        video_file_id = episode[0]
        
        # FAQAT VIDEO YUBORISH, HECH QANDAY TUGMA
        await message.answer_video(
            video=video_file_id,
            caption=f"🎬 {anime[0]} - {episode_num}-qism"
        )
    except Exception as e:
        logging.error(f"Video yuborishda xatolik: {str(e)}")
    finally:
        conn.close()


async def show_episodes_menu(message: types.Message, anime_code: str):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime_title = cursor.fetchone()[0]
        cursor.execute("""
            SELECT episode_number 
            FROM episodes 
            WHERE anime_code = ?
            ORDER BY episode_number
        """, (anime_code,))
        episodes = cursor.fetchall()
        
        if not episodes:
            await message.answer("❌ Bu anime uchun hali qismlar qo'shilmagan!")
            return
        
        await message.answer(f"🎬 **{anime_title}**\n📺 Qismlar yuklanmoqda...")
        
        # Barcha qismlarni ketma-ket yuborish
        for ep in episodes:
            episode_num = ep[0]
            await handle_episode_request_direct(message.from_user.id, anime_code, episode_num, message)
            await asyncio.sleep(0.3)  # Spamdan qochish uchun kutish
            
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data.startswith("episodes_page_"))
async def episodes_page_callback(call: types.CallbackQuery):
    try:
        parts = call.data.split('_')
        anime_code = parts[2]
        page = int(parts[3])
        await call.answer()
        await show_episodes_menu(call.message, anime_code, page)
    except Exception as e:
        await call.answer("❌ Xatolik yuz berdi", show_alert=True)
class ManagePostTemplate(StatesGroup):
    waiting_for_content = State()     # Shablon mazmunini kiritish
    waiting_for_name = State()        # Shablon nomini kiritish
    waiting_for_confirmation = State() # Tasdiqlash
    asking_font_choice = State()      # Shrift tanlash so'rovi
    formatting_content = State()      # Formatlash rejimi (agar kerak bo'lsa)
@dp.callback_query(lambda call: call.data == "confirm_add_template", StateFilter(ManagePostTemplate.waiting_for_confirmation))
async def confirm_add_template(call: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    template_name = user_data['template_name']
    template_content = user_data['template_content']
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(template_id) FROM post_templates")
        max_id = cursor.fetchone()[0]
        new_template_id = (max_id or 0) + 1
        cursor.execute('''
            INSERT INTO post_templates (template_id, template_name, template_content) 
            VALUES (?, ?, ?)
        ''', (new_template_id, template_name, template_content))
        conn.commit()
        await call.message.edit_text(f"✅ `{template_name}` shabloni (ID: {new_template_id}) muvaffaqiyatli qo'shildi!", parse_mode="HTML")

        # YANGI QO'SHILGAN QISM: Shrift tanlashni so'rash
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, shrift tanlamoqchiman", callback_data="choose_font_style"),
                InlineKeyboardButton(text="❌ Yo'q, kerak emas", callback_data="skip_font_choice")
            ]
        ])
        await state.update_data(template_id=new_template_id)  # template_id ni saqlab qo'yamiz
        await state.set_state(ManagePostTemplate.asking_font_choice)
        await call.message.answer(
            "🎨 Shablon uchun maxsus shrift uslubini tanlamoqchimisiz?",
            reply_markup=keyboard
        )

    except sqlite3.IntegrityError:
        await call.message.edit_text("❌ Bu nomdagi shablon allaqachon mavjud. Iltimos, boshqa nom kiriting.")
    except Exception as e:
        await call.message.edit_text(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()
    await call.answer()
@dp.callback_query(lambda call: call.data == "choose_font_style", StateFilter(ManagePostTemplate.asking_font_choice))
async def choose_font_style(call: types.CallbackQuery, state: FSMContext):
    # Faqat qalin va kursiv stil variantlari
    font_styles = {
        "bold": "Qalin (Bold)",
        "italic": "Kursiv (Italic)",
        "bold_italic": "Qalin + Kursiv",
        "default": "Standart"
    }

    buttons = []
    for style_key, style_name in font_styles.items():
        buttons.append([InlineKeyboardButton(text=style_name, callback_data=f"select_font_{style_key}")])

    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="skip_font_choice")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await call.message.edit_text("🎨 Quyidagi matn uslublaridan birini tanlang:", reply_markup=keyboard)
    await call.answer()
@dp.callback_query(lambda call: call.data.startswith("select_font_"), StateFilter(ManagePostTemplate.asking_font_choice))
async def save_font_style(call: types.CallbackQuery, state: FSMContext):
    font_style = call.data.replace("select_font_", "")
    # Faqat ruxsat etilgan uslublar
    allowed_styles = {"bold", "italic", "bold_italic", "default"}
    if font_style not in allowed_styles:
        await call.message.edit_text("❌ Noto'g'ri uslub tanlandi.")
        await state.clear()
        return

    user_data = await state.get_data()
    template_id = user_data['template_id']

    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE post_templates SET font_style = ? WHERE template_id = ?", (font_style, template_id))
        conn.commit()
        await call.message.edit_text(f"✅ Shablon uchun uslub muvaffaqiyatli o'rnatildi: `{font_style}`", parse_mode="HTML")
    except Exception as e:
        await call.message.edit_text(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        await state.clear()
        conn.close()
    await call.answer()
@dp.callback_query(lambda call: call.data == "skip_font_choice", StateFilter(ManagePostTemplate.asking_font_choice))
async def skip_font_choice(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("✅ Shablon saqlandi. Shrift uslubi o'rnatilmadi.")
    await call.answer()
@dp.message(lambda message: message.text == "📋 Post Shablonlari")
async def manage_post_templates(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi Shablon Qo'shish", callback_data="start_add_template")],
        [InlineKeyboardButton(text="🗑 Shablonni O'chirish", callback_data="remove_template")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_features")]
    ])
    await message.answer("📋 Post Shablonlari Boshqaruvi:", reply_markup=keyboard)

@dp.callback_query(lambda call: call.data == "start_add_template")
async def start_add_template(call: types.CallbackQuery, state: FSMContext):
    if not await check_admin(call.from_user.id, call=call):
        return
    await state.set_state(ManagePostTemplate.waiting_for_content)
    await call.message.answer(
        "📝 Yangi post shablonining mazmunini yuboring.\n"
        "Shablon {title} va {episode_number} o'rniga qo'yiladigan joylarni o'z ichiga olishi kerak.\n"
        "Misol: <code><b>{title}</b> - {episode_number}-qism</code>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
            resize_keyboard=True
        )
    )
    await call.answer()
@dp.message(ManagePostTemplate.waiting_for_content)
async def get_template_content(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await cancel_post_action(message, state)
        return
    await state.update_data(template_content=message.text)
    await state.set_state(ManagePostTemplate.waiting_for_name)
    await message.answer(
        "🔤 Shablon uchun noyob nom kiriting:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
            resize_keyboard=True
        )
    )
@dp.message(ManagePostTemplate.waiting_for_name)
async def get_template_name(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        # cancel_post_action funksiyasi mavjudligiga ishonch hosil qiling
        await cancel_post_action(message, state)
        return
    
    template_name = message.text.strip()
    if len(template_name) < 2:
        await message.answer("❌ Shablon nomi juda qisqa. Iltimos, 2 ta belgidan ko'p bo'lgan nom kiriting.")
        return
    
    user_data = await state.get_data()
    template_content = user_data['template_content']
    
    # Tasdiqlash tugmasini ko'rsatish
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_add_template"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_add_template")
        ]
    ])
    
    await state.update_data(template_name=template_name)
    await state.set_state(ManagePostTemplate.waiting_for_confirmation)
    
    # String qatorini to'g'ri formatda yozing
    await message.answer(
        f"📋 Shablonni tasdiqlang:\n"
        f"<b>Nomi:</b> {template_name}\n"
        f"<b>Mazmuni:</b> \n"
        f"<code>{template_content}</code>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
@dp.callback_query(lambda call: call.data == "confirm_add_template", StateFilter(ManagePostTemplate.waiting_for_confirmation))
async def confirm_add_template(call: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    template_name = user_data['template_name']
    template_content = user_data['template_content']
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        # Eng katta template_id ni olish va yangi ID ni hisoblash
        cursor.execute("SELECT MAX(template_id) FROM post_templates")
        max_id = cursor.fetchone()[0]
        new_template_id = (max_id or 0) + 1
        cursor.execute('''
            INSERT INTO post_templates (template_id, template_name, template_content) 
            VALUES (?, ?, ?)
        ''', (new_template_id, template_name, template_content))
        conn.commit()
        await call.message.edit_text(f"✅ `{template_name}` shabloni (ID: {new_template_id}) muvaffaqiyatli qo'shildi!", parse_mode="HTML")
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: post_templates.template_name" in str(e):
            await call.message.edit_text("❌ Bu nomdagi shablon allaqachon mavjud. Iltimos, boshqa nom kiriting.")
        else:
            await call.message.edit_text(f"❌ Ma'lumotlar bazasi xatosi: {str(e)}")
    except Exception as e:
        await call.message.edit_text(f"❌ Kutilmagan xatolik: {str(e)}")
    finally:
        await state.clear()
        conn.close()
    await call.answer()
@dp.callback_query(lambda call: call.data == "cancel_add_template", StateFilter(ManagePostTemplate.waiting_for_confirmation))
async def cancel_add_template(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Shablon qo'shish bekor qilindi.")
    await call.answer()


@dp.callback_query(lambda call: call.data == "back_to_main_from_episodes")
async def back_to_main_from_episodes(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except:
        pass
    # show_main_menu o'rniga oddiy xabar
    await call.message.answer("✅ Bosh menyuga qaytdingiz.")
    await call.answer()

@dp.callback_query(lambda call: call.data.startswith("episode_"))
async def handle_episode_request(call: types.CallbackQuery):
    """Episode callback - faqat video yuborish, tugmasiz"""
    try:
        parts = call.data.split('_')
        if len(parts) != 3:
            await call.answer("❌ Noto'g'ri format!", show_alert=True)
            return
            
        anime_code = parts[1]
        try:
            episode_num = int(parts[2])
        except ValueError:
            await call.answer("❌ Noto'g'ri epizod raqami!", show_alert=True)
            return
            
        # Obunani tekshirish
        is_subscribed = await check_subscription_with_redirect(
            call.from_user.id, 
            f"episode_{anime_code}_{episode_num}", 
            call=call
        )
        if not is_subscribed:
            return
            
        await call.answer("⏳ Yuklanmoqda...")
        
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            await call.answer("❌ Anime topilmadi!", show_alert=True)
            return
            
        cursor.execute("""
            SELECT video_file_id 
            FROM episodes 
            WHERE anime_code = ? AND episode_number = ?
        """, (anime_code, episode_num))
        episode = cursor.fetchone()
        if not episode:
            await call.answer(f"❌ {episode_num}-qism topilmadi!", show_alert=True)
            return
            
        video_file_id = episode[0]
        
        # ESKI: Tugmalar bilan yuborish
        # YANGI: FAQAT VIDEO YUBORISH, HECH QANDAY TUGMA
        try:
            await call.message.delete()
        except Exception:
            pass
            
        # Tugmasiz video yuborish
        await bot.send_video(
            chat_id=call.from_user.id,
            video=video_file_id,
            caption=f"🎬 {anime[0]} - {episode_num}-qism"
            # reply_markup o'chirildi - hech qanday tugma yo'q
        )
        
    except Exception as e:
        logging.error(f"Xatolik: {str(e)}")
        await call.answer("❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.", show_alert=True)
    finally:
        if 'conn' in locals():
            conn.close()

@dp.callback_query(lambda call: call.data == "back_to_main_from_episode")
async def back_to_main_from_episode(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except:
        pass
    # show_main_menu o'rniga oddiy xabar
    await call.message.answer("✅ Bosh menyuga qaytdingiz.")
    await call.answer()

# ==================== ADMIN PANEL ====================

@dp.message(Command("admin"))
async def admin_login(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
 [KeyboardButton(text="🎥 Anime Sozlash"), KeyboardButton(text="📢 Kanal Sozlash")],
            [KeyboardButton(text="📝 Post Tayyorlash"), KeyboardButton(text="🎞 Serial Post Qilish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Obunachilar")],
            [KeyboardButton(text="👨‍💻 Adminlar"), KeyboardButton(text="⚙️ Qo'shimcha Funksiyalar")],
            
            [KeyboardButton(text="🔙 Bosh Menyu")]
        ],
        resize_keyboard=True
    )
    await message.answer("👨‍💻 Admin Panelga xush kelibsiz!", reply_markup=keyboard)

@dp.message(lambda message: message.text == "⚙️ Qo'shimcha Funksiyalar")
async def additional_features(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Sticker Sozlash")],
            [KeyboardButton(text="📋 Post Shablonlari")],  # YANGI QO'SHILGAN QATOR
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await message.answer("⚙️ Qo'shimcha funksiyalar:", reply_markup=keyboard)

@dp.message(lambda message: message.text == "🖼 Sticker Sozlash")
async def sticker_settings(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Welcome Sticker Qo'shish", callback_data="add_welcome_sticker")],
        [InlineKeyboardButton(text="🗑 Sticker O'chirish", callback_data="remove_sticker")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_features")]
    ])
    await message.answer("🖼 Welcome Sticker Sozlamalari:", reply_markup=keyboard)

@dp.callback_query(lambda call: call.data == "add_welcome_sticker")
async def add_welcome_sticker_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    user_state[call.from_user.id] = {"state": "waiting_welcome_sticker"}
    await call.message.answer("🖼 Welcome uchun sticker yuboring:")

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_welcome_sticker")
async def save_welcome_sticker(message: types.Message):
    if not message.sticker:
        await message.answer("❌ Iltimos, faqat sticker yuboring!")
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM stickers WHERE used_for = 'welcome'")
        cursor.execute(
            "INSERT INTO stickers (sticker_file_id, used_for) VALUES (?, ?)",
            (message.sticker.file_id, 'welcome')
        )
        conn.commit()
        await message.answer("✅ Welcome sticker muvaffaqiyatli qo'shildi!")
        await message.answer_sticker(message.sticker.file_id)
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        if message.from_user.id in user_state:
            del user_state[message.from_user.id]
        conn.close()

@dp.callback_query(lambda call: call.data == "remove_sticker")
async def remove_sticker_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, sticker_file_id FROM stickers WHERE used_for = 'welcome'")
        sticker = cursor.fetchone()
        if not sticker:
            await call.answer("ℹ️ Welcome sticker mavjud emas", show_alert=True)
            return
        sticker_id, file_id = sticker
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_remove_sticker_{sticker_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sticker_settings")
            ]
        ])
        await call.message.answer_sticker(file_id)
        await call.message.answer(
            "⚠️ Bu stickerni o'chirishni tasdiqlaysizmi?",
            reply_markup=keyboard
        )
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data.startswith("confirm_remove_sticker_"))
async def remove_sticker_confirm(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    sticker_id = call.data.replace("confirm_remove_sticker_", "")
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM stickers WHERE id = ?", (sticker_id,))
        conn.commit()
        await call.answer("✅ Sticker muvaffaqiyatli o'chirildi!", show_alert=True)
        await sticker_settings(call)
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data == "back_to_features")
async def back_to_features(call: types.CallbackQuery):
    await additional_features(call.message)

@dp.message(lambda message: message.text == "🎥 Anime Sozlash")
async def anime_settings(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Anime Qo'shish")],
            [KeyboardButton(text="✏️ Anime Tahrirlash")],
            [KeyboardButton(text="🗑 Anime O'chirish")],
            [KeyboardButton(text="🎞 Qism Qo'shish"), KeyboardButton(text="🗑 Qism O'chirish")],
            [KeyboardButton(text="📺 Ongoing Anime")],
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await message.answer("🎥 Anime Sozlamalari:", reply_markup=keyboard)

class DatabaseBackup(StatesGroup):
    waiting_selection = State()
    waiting_backup_file = State()





@dp.message(lambda message: message.text == "🗑 Qism O'chirish")
async def delete_episode_start(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    user_state[message.from_user.id] = {"state": "waiting_anime_code_for_episode_delete"}
    await message.answer("🔢 Qism o'chirish uchun anime kodini yuboring:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_code_for_episode_delete")
async def show_episodes_for_deletion(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_action(message)
        return
    anime_code = message.text.strip()
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            await message.answer("❌ Bunday kodli anime topilmadi!")
            return
        cursor.execute("""
            SELECT episode_number 
            FROM episodes 
            WHERE anime_code = ?
            ORDER BY episode_number
        """, (anime_code,))
        episodes = cursor.fetchall()
        if not episodes:
            await message.answer("❌ Bu anime uchun hech qanday qism topilmadi!")
            return
        buttons = []
        row = []
        for ep in episodes:
            row.append(InlineKeyboardButton(
                text=f"{ep[0]}-qism",
                callback_data=f"delete_ep_{anime_code}_{ep[0]}"
            ))
            if len(row) >= 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(
            text="🔙 Bekor qilish",
            callback_data="cancel_episode_deletion"
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"🎬 {anime[0]}\n"
            f"🗑 O'chirish uchun qismni tanlang:",
            reply_markup=keyboard
        )
        user_state[message.from_user.id] = {
            "state": "waiting_episode_to_delete",
            "anime_code": anime_code,
            "anime_title": anime[0]
        }
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data.startswith("delete_ep_"))
async def confirm_episode_deletion(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    parts = call.data.split('_')
    anime_code = parts[2]
    episode_num = parts[3]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Ha, o'chirish",
                callback_data=f"confirm_delete_ep_{anime_code}_{episode_num}"
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="cancel_episode_deletion"
            )
        ]
    ])
    await call.message.edit_text(
        f"⚠️ {anime_code} kodli animening {episode_num}-qismini o'chirishni tasdiqlaysizmi?",
        reply_markup=keyboard
    )
    await call.answer()

@dp.callback_query(lambda call: call.data.startswith("confirm_delete_ep_"))
async def delete_episode_final(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    parts = call.data.split('_')
    anime_code = parts[3]
    episode_num = parts[4]
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 1 FROM episodes 
            WHERE anime_code = ? AND episode_number = ?
        """, (anime_code, episode_num))
        if not cursor.fetchone():
            await call.answer("❌ Bu qism allaqachon o'chirilgan!", show_alert=True)
            return
        cursor.execute("""
            DELETE FROM episodes 
            WHERE anime_code = ? AND episode_number = ?
        """, (anime_code, episode_num))
        conn.commit()
        await call.answer(f"✅ {episode_num}-qism muvaffaqiyatli o'chirildi!", show_alert=True)
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🗑 Qism O'chirish")],
                [KeyboardButton(text="🔙 Admin Panel")]
            ],
            resize_keyboard=True
        )
        await call.message.answer(
            f"🎬 {anime_code} kodli animening {episode_num}-qismi o'chirildi!",
            reply_markup=keyboard
        )
    except Exception as e:
        await call.answer(f"❌ Xatolik yuz berdi: {str(e)}", show_alert=True)
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data == "cancel_episode_deletion")
async def cancel_episode_deletion(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    if call.from_user.id in user_state:
        del user_state[call.from_user.id]
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑 Qism O'chirish")],
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await call.message.answer(
        "❌ Qism o'chirish bekor qilindi.",
        reply_markup=keyboard
    )
    await call.answer()

async def cancel_action(message: types.Message):
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎥 Anime Sozlash")],
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "❌ Amal bekor qilindi.",
        reply_markup=keyboard
    )



@dp.message(lambda message: message.text == "🔙 Admin Panel")
async def back_to_admin_panel(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
           [KeyboardButton(text="🎥 Anime Sozlash"), KeyboardButton(text="📢 Kanal Sozlash")],
            [KeyboardButton(text="📝 Post Tayyorlash"), KeyboardButton(text="🎞 Serial Post Qilish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Obunachilar")],
            [KeyboardButton(text="👨‍💻 Adminlar"), KeyboardButton(text="❓ Savollar")],
            [KeyboardButton(text="⚙️ Qo'shimcha Funksiyalar")],
            [KeyboardButton(text="🔙 Bosh Menyu")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "👨‍💻 Admin Panelga xush kelibsiz!",
        reply_markup=keyboard
    )

@dp.message(lambda message: message.text == "➕ Anime Qo'shish")
async def add_anime_menu(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    user_state[message.from_user.id] = {"state": "waiting_anime_title"}
    await message.answer("🎬 Anime nomini yuboring:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_title")
async def get_anime_title(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    user_state[message.from_user.id] = {
        "state": "waiting_anime_country",
        "title": message.text
    }
    await message.answer("🌍 Davlatini kiriting:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_country")
async def get_anime_country(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    user_state[message.from_user.id].update({
        "state": "waiting_anime_language",
        "country": message.text
    })
    await message.answer("🇺🇿 Tilini kiriting:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_language")
async def get_anime_language(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    user_state[message.from_user.id].update({
        "state": "waiting_anime_year",
        "language": message.text
    })
    await message.answer("📆 Yilini kiriting (masalan: 2023):",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_year")
async def get_anime_year(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri yil formatida. Qayta kiriting:",
                           reply_markup=ReplyKeyboardMarkup(
                               keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                               resize_keyboard=True
                           ))
        return
    user_state[message.from_user.id].update({
        "state": "waiting_anime_genre",
        "year": int(message.text)
    })
    await message.answer("🎞 Janrini kiriting (masalan: Action, Drama):",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_genre")
async def get_anime_genre(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    user_state[message.from_user.id].update({
        "state": "waiting_anime_description",
        "genre": message.text
    })
    await message.answer("📝 Anime haqida qisqacha tavsif yozing:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_description")
async def get_anime_description(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_anime_addition(message)
        return
    user_state[message.from_user.id].update({
        "state": "waiting_anime_image",
        "description": message.text
    })
    await message.answer("🖼 Anime uchun rasm (PNG/JPG) yoki qisqa video (MP4) yuboring:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(
    lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_image" 
    and (message.photo or message.video)
)
async def get_anime_media(message: types.Message):
    media_file_id = None
    media_type = None
    if message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = 'photo'
    elif message.video:
        media_file_id = message.video.file_id
        media_type = 'video'
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM anime")
        anime_code = str(cursor.fetchone()[0] + 1)
        cursor.execute('''INSERT INTO anime (
            code, title, country, language, year, genre, description, image, video
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            anime_code, 
            user_state[message.from_user.id]["title"],
            user_state[message.from_user.id]["country"],
            user_state[message.from_user.id]["language"],
            user_state[message.from_user.id]["year"],
            user_state[message.from_user.id]["genre"],
            user_state[message.from_user.id]["description"],
            media_file_id if media_type == 'photo' else None,
            media_file_id if media_type == 'video' else None
        ))
        conn.commit()
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎥 Anime Sozlash")],
                [KeyboardButton(text="🔙 Admin Panel")]
            ],
            resize_keyboard=True
        )
        if media_type == 'photo':
            await message.answer_photo(
                media_file_id,
                caption=f"✅ Anime muvaffaqiyatli qo'shildi!\n"
                       f"🎬 Nomi: {user_state[message.from_user.id]['title']}\n"
                       f"🌍 Davlati: {user_state[message.from_user.id]['country']}\n"
                       f"🇺🇿 Tili: {user_state[message.from_user.id]['language']}\n"
                       f"📆 Yili: {user_state[message.from_user.id]['year']}\n"
                       f"🎞 Janri: {user_state[message.from_user.id]['genre']}\n"
                       f"🔢 Anime kodi: {anime_code}",
                reply_markup=keyboard
            )
        else:
            await message.answer_video(
                media_file_id,
                caption=f"✅ Anime muvaffaqiyatli qo'shildi!\n"
                       f"🎬 Nomi: {user_state[message.from_user.id]['title']}\n"
                       f"🌍 Davlati: {user_state[message.from_user.id]['country']}\n"
                       f"🇺🇿 Tili: {user_state[message.from_user.id]['language']}\n"
                       f"📆 Yili: {user_state[message.from_user.id]['year']}\n"
                       f"🎞 Janri: {user_state[message.from_user.id]['genre']}\n"
                       f"🔢 Anime kodi: {anime_code}",
                reply_markup=keyboard
            )
        del user_state[message.from_user.id]
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

async def cancel_anime_addition(message: types.Message):
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Anime Qo'shish")],
            [KeyboardButton(text="✏️ Anime Tahrirlash")],
            [KeyboardButton(text="🗑 Anime O'chirish")],
            [KeyboardButton(text="🎞 Qism Qo'shish")],
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "❌ Anime qo'shish bekor qilindi.",
        reply_markup=keyboard
    )

# ==================== EDIT ANIME (SQL Injection tuzatilgan) ====================
ALLOWED_FIELDS = {'title', 'country', 'language', 'year', 'genre', 'description', 'image'}

@dp.message(lambda message: message.text == "✏️ Anime Tahrirlash")
async def edit_anime_menu(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    user_state[message.from_user.id] = {"state": "waiting_anime_code_for_edit"}
    await message.answer("✏️ Tahrirlash uchun anime kodini yuboring:")

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_code_for_edit")
async def get_anime_for_edit(message: types.Message):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM anime WHERE code = ?", (message.text,))
    anime = cursor.fetchone()
    if anime:
        user_state[message.from_user.id] = {
            "state": "editing_anime",
            "anime_code": message.text
        }
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Nomi", callback_data="edit_title")],
            [InlineKeyboardButton(text="🌍 Davlati", callback_data="edit_country")],
            [InlineKeyboardButton(text="🇺🇿 Tili", callback_data="edit_language")],
            [InlineKeyboardButton(text="📆 Yili", callback_data="edit_year")],
            [InlineKeyboardButton(text="🎞 Janri", callback_data="edit_genre")],
            [InlineKeyboardButton(text="📝 Tavsif", callback_data="edit_description")],
            [InlineKeyboardButton(text="🖼 Rasm", callback_data="edit_image")]
        ])
        await message.answer("Qaysi maydonni tahrirlamoqchisiz?", reply_markup=keyboard)
    else:
        await message.answer("❌ Bunday kodli anime topilmadi")
    conn.close()

@dp.callback_query(lambda call: call.data.startswith("edit_"))
async def edit_anime_field(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    field = call.data.replace("edit_", "")
    if field not in ALLOWED_FIELDS:
        await call.message.answer("❌ Noto'g'ri maydon nomi!")
        return
    user_state[call.from_user.id]["editing_field"] = field
    await call.message.answer(f"Yangi {field} qiymatini yuboring:")
    await call.answer()

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("editing_field"))
async def save_edited_field(message: types.Message):
    user_data = user_state[message.from_user.id]
    field = user_data["editing_field"]
    anime_code = user_data["anime_code"]
    if field not in ALLOWED_FIELDS:
        await message.answer("❌ Noto'g'ri maydon nomi!")
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        if field == "image":
            if not message.photo:
                await message.answer("❌ Iltimos, rasm yuboring!")
                return
            new_value = message.photo[-1].file_id
        else:
            new_value = message.text
        cursor.execute(f"UPDATE anime SET {field} = ? WHERE code = ?", (new_value, anime_code))
        conn.commit()
        await message.answer(f"✅ Anime {field} muvaffaqiyatli yangilandi!")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        if "editing_field" in user_state[message.from_user.id]:
            del user_state[message.from_user.id]["editing_field"]
        conn.close()

@dp.message(lambda message: message.text == "🗑 Anime O'chirish")
async def delete_anime_menu(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    user_state[message.from_user.id] = {"state": "waiting_anime_code_for_delete"}
    await message.answer("🗑 O'chirish uchun anime kodini yuboring:")

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_code_for_delete")
async def delete_anime(message: types.Message):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM episodes WHERE anime_code = ?", (message.text,))
        cursor.execute("DELETE FROM anime WHERE code = ?", (message.text,))
        cursor.execute("DELETE FROM favorites WHERE anime_code = ?", (message.text,))
        conn.commit()
        await message.answer("✅ Anime va uning barcha qismlari muvaffaqiyatli o'chirildi!")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        del user_state[message.from_user.id]
        conn.close()

# ==================== EPISODE FUNCTIONS ====================

@dp.message(lambda message: message.text == "🔙 Bekor qilish")
async def cancel_episode_adding(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
          [KeyboardButton(text="🎥 Anime Sozlash"), KeyboardButton(text="📢 Kanal Sozlash")],
            [KeyboardButton(text="📝 Post Tayyorlash"), KeyboardButton(text="🎞 Serial Post Qilish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Obunachilar")],
            [KeyboardButton(text="👨‍💻 Adminlar"), KeyboardButton(text="⚙️ Qo'shimcha Funksiyalar")],
            
            [KeyboardButton(text="🔙 Bosh Menyu")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "Qism qo'shish bekor qilindi.\nAdmin panelga qaytildi:",
        reply_markup=keyboard
    )

@dp.message(lambda message: message.text == "🏠 Bosh Menyu")
async def main_menu(message: types.Message):
    await message.answer("Bosh menyu:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[
                               [KeyboardButton(text="🎞 Qism Qo'shish")],
                               [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="⚙️ Sozlamalar")]
                           ],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: message.text == "🎞 Qism Qo'shish")
async def add_episode_menu(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        await main_menu(message)
        return
    user_state[message.from_user.id] = {"state": "waiting_anime_code_for_episode"}
    await message.answer("🎞 Qism qo'shish uchun anime kodini yuboring:",
                       reply_markup=ReplyKeyboardMarkup(
                           keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                           resize_keyboard=True
                       ))

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_anime_code_for_episode")
async def get_anime_for_episode(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_episode_adding(message)
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM anime WHERE code = ?", (message.text,))
    anime = cursor.fetchone()
    if anime:
        user_state[message.from_user.id] = {
            "state": "waiting_episode_video",
            "anime_code": message.text,
            "anime_title": anime[0]
        }
        cursor.execute("SELECT MAX(episode_number) FROM episodes WHERE anime_code = ?", (message.text,))
        last_episode = cursor.fetchone()[0] or 0
        await message.answer(
            f"🎬 {anime[0]}\n"
            f"📹 {last_episode + 1}-qism videosini yuboring (MP4 formatida):",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                resize_keyboard=True
            ))
    else:
        await message.answer("❌ Bunday kodli anime topilmadi. Qayta urinib ko'ring:")
    conn.close()

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_episode_video")
async def handle_episode_video_or_cancel(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_episode_adding(message)
        return
    if message.video:
        video = message.video
        file_id = video.file_id
        conn = sqlite3.connect('anime_bot.db')
        cursor = conn.cursor()
        try:
            anime_code = user_state[message.from_user.id]["anime_code"]
            anime_title = user_state[message.from_user.id]["anime_title"]
            cursor.execute("SELECT MAX(episode_number) FROM episodes WHERE anime_code = ?", (anime_code,))
            last_episode = cursor.fetchone()[0] or 0
            new_episode_number = last_episode + 1
            cursor.execute('''INSERT INTO episodes (anime_code, episode_number, video_file_id) 
                              VALUES (?, ?, ?)''',
                           (anime_code, new_episode_number, file_id))
            conn.commit()
            await notify_subscribers(anime_code, new_episode_number)
            await message.answer(
                f"✅ {anime_title} animega {new_episode_number}-qism muvaffaqiyatli qo'shildi!\n"
                f"📹 {new_episode_number + 1}-qism videosini yuboring (agar qo'shmoqchi bo'lsangiz)\n"
                f"Aks holda 🔙 Bekor qilish tugmasini bosing",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                    resize_keyboard=True
                ))
        except Exception as e:
            await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
        finally:
            conn.close()
    else:
        await message.answer("Iltimos, faqat video yuboring yoki 🔙 Bekor qilish tugmasini bosing")

async def notify_subscribers(anime_code: str, episode_number: int):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            return
        anime_title = anime[0]
        cursor.execute("SELECT user_id FROM subscribers WHERE notifications = TRUE")
        subscribers = cursor.fetchall()
        for (user_id,) in subscribers:
            try:
                bot_username = (await bot.get_me()).username
                watch_url = f"https://t.me/{bot_username}?start=watch_{anime_code}"
                message_text = f"""
🎬 <b>Yangi qism qo'shildi!</b>
📺 <b>{anime_title}</b>
🔢 <b>Qism:</b> {episode_number}
▶️ Tomosha qilish uchun quyidagi tugmani bosing:
                """
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="▶️ Tomosha Qilish",
                        url=watch_url
                    )]
                ])
                await bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.1)
            except exceptions.TelegramAPIError as e:
                if "bot was blocked" in str(e).lower():
                    cursor.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
                    conn.commit()
                logging.error(f"Xabar yuborishda xatolik (user_id={user_id}): {e}")
            except Exception as e:
                logging.error(f"Xabar yuborishda kutilmagan xatolik (user_id={user_id}): {e}")
    except Exception as e:
        logging.error(f"notify_subscribers xatosi: {e}")
    finally:
        conn.close()

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_multiple_episodes" and message.video)
async def get_multiple_episodes_video(message: types.Message):
    video = message.video
    file_id = video.file_id
    user_data = user_state[message.from_user.id]
    user_data["qism_fayllari"].append(file_id)
    user_data["qolgan_qismlar"] -= 1
    if user_data["qolgan_qismlar"] > 0:
        user_data["hozirgi_qism"] += 1
        await message.answer(
            f"✅ {user_data['hozirgi_qism']-1}-qism qabul qilindi.\n"
            f"Qoldi: {user_data['qolgan_qismlar']} ta\n"
            f"{user_data['hozirgi_qism']}-qism videosini yuboring:"
        )
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        anime_code = user_data["anime_code"]
        anime_title = user_data["anime_title"]
        cursor.execute("SELECT COUNT(*) FROM episodes WHERE anime_code = ?", (anime_code,))
        boshlangich_qism = cursor.fetchone()[0] + 1
        for i, file_id in enumerate(user_data["qism_fayllari"]):
            qism_raqami = boshlangich_qism + i
            cursor.execute('''INSERT INTO episodes (anime_code, episode_number, video_file_id) 
                              VALUES (?, ?, ?)''',
                           (anime_code, qism_raqami, file_id))
            await notify_subscribers(anime_code, qism_raqami)
        conn.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎞 Yana Qism Qo'shish", callback_data=f"add_episode_{anime_code}")],
            [InlineKeyboardButton(text="➕ Bir nechta qism qo'shish", callback_data=f"add_multiple_{anime_code}")],
            [InlineKeyboardButton(text="🔙 Admin Panel", callback_data="back_to_admin")]
        ])
        await message.answer(
            f"✅ {anime_title} animega {len(user_data['qism_fayllari'])} ta yangi qism muvaffaqiyatli qo'shildi!\n"
            f"Qo'shilgan qismlar: {boshlangich_qism}-{boshlangich_qism + len(user_data['qism_fayllari']) - 1}",
            reply_markup=keyboard
        )
        del user_state[message.from_user.id]
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

@dp.callback_query(lambda c: c.data.startswith("add_episode_"))
async def add_another_episode(callback: types.CallbackQuery):
    anime_code = callback.data.replace("add_episode_", "")
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
    anime = cursor.fetchone()
    if anime:
        user_state[callback.from_user.id] = {
            "state": "waiting_episode_video",
            "anime_code": anime_code,
            "anime_title": anime[0],
            "rejim": "bitta"
        }
        await callback.message.answer(f"🎬 {anime[0]}\n📹 Yangi qism videosini yuboring (MP4 formatida):",
                            reply_markup=ReplyKeyboardMarkup(
                                keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                                resize_keyboard=True
                            ))
    else:
        await callback.message.answer("❌ Bunday kodli anime topilmadi.")
    conn.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("add_multiple_"))
async def add_multiple_episodes(callback: types.CallbackQuery):
    anime_code = callback.data.replace("add_multiple_", "")
    await callback.message.answer(
        f"📝 Qancha qism qo'shmoqchisiz?\n"
        f"Anime kodi: <code>{anime_code}</code>\n"
        f"Quyidagi formatda yuboring:\n"
        f"<code>{anime_code}:qismlar_soni</code>\n"
        f"Masalan: <code>{anime_code}:3</code>",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
            resize_keyboard=True
        )
    )
    user_state[callback.from_user.id] = {
        "state": "waiting_episode_count",
        "anime_code": anime_code
    }
    await callback.answer()

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_episode_count")
async def process_episode_count(message: types.Message):
    if message.text == "🔙 Bekor qilish":
        await cancel_post_action(message)
        return
    anime_code = user_state[message.from_user.id]["anime_code"]
    if ":" in message.text:
        parts = message.text.split(":")
        if len(parts) == 2 and parts[1].isdigit() and parts[0] == anime_code:
            qismlar_soni = int(parts[1])
            conn = sqlite3.connect('anime_bot.db')
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
            anime = cursor.fetchone()
            if anime:
                user_state[message.from_user.id] = {
                    "state": "waiting_multiple_episodes",
                    "anime_code": anime_code,
                    "anime_title": anime[0],
                    "qolgan_qismlar": qismlar_soni,
                    "hozirgi_qism": 1,
                    "qism_fayllari": []
                }
                await message.answer(
                    f"🎬 {anime[0]}\n"
                    f"📹 {qismlar_soni} ta qism qo'shish rejimi\n"
                    f"1-qism videosini yuboring (MP4 formatida):",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                        resize_keyboard=True
                    )
                )
                conn.close()
                return
    await message.answer("❌ Noto'g'ri format. Iltimos, quyidagi formatda yuboring:\n"
                        f"<code>{anime_code}:qismlar_soni</code>\n"
                        f"Masalan: <code>{anime_code}:5</code>")

# ==================== CHANNEL SETTINGS ====================

@dp.message(lambda message: message.text == "📢 Kanal Sozlash")
async def channel_settings(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Majburiy Obuna Kanal", callback_data="mandatory_channel_menu")],
        [InlineKeyboardButton(text="📢 Post Kanal", callback_data="post_channel_menu")],
        [InlineKeyboardButton(text="🔙 Admin Panel", callback_data="back_to_admin")]
    ])
    await message.answer("📢 Kanal Sozlash", reply_markup=keyboard)

@dp.callback_query(lambda call: call.data == "post_channel_menu")
async def post_channel_menu(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels WHERE channel_type = 'post'")
    channel = cursor.fetchone()
    conn.close()
    text = "📢 Post kanal: " + (f"{channel[1]} (ID: {channel[0]})" if channel else "❌ O'rnatilmagan")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Post Kanal Qo'shish", callback_data="add_post_channel")],
        [InlineKeyboardButton(text="➖ Post Kanal O'chirish", callback_data="remove_post_channel")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_channels")]
    ])
    await call.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(lambda call: call.data == "add_post_channel")
async def add_post_channel_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    user_state[call.from_user.id] = {"state": "waiting_post_channel"}
    await call.message.edit_text(
        "Yangi post kanalini quyidagi formatlardan birida yuboring:\n"
        "• @channel_username\n"
        "• https://t.me/channel\n"
        "• -100123456789 (private kanal ID)\n"
        "Bot kanalda admin bo'lishi shart!"
    )

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_post_channel")
async def process_post_channel(message: types.Message):
    raw_input = message.text.strip()
    try:
        if raw_input.startswith(("https://t.me/", "t.me/")):
            channel_id = "@" + raw_input.split("/")[-1]
        elif raw_input.startswith("-100") and raw_input[4:].isdigit():
            channel_id = raw_input
        elif raw_input.startswith("@"):
            channel_id = raw_input
        else:
            raise ValueError("Noto'g'ri format")
        chat = await bot.get_chat(channel_id)
        bot_member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            raise ValueError("Bot kanalda admin emas")
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO channels (channel_type, channel_id, channel_name)
                VALUES ('post', ?, ?)
            """, (channel_id, chat.title))
            conn.commit()
        await message.answer(
            f"✅ Post kanal qo'shildi!\n"
            f"📢 Nomi: {chat.title}\n"
            f"🆔 ID: {channel_id}"
        )
        await post_channel_menu(await bot.send_message(message.from_user.id, "Post kanal menyusi:"))
    except ValueError as e:
        await message.answer(f"❌ {str(e)}\nQayta urinib ko'ring:")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {str(e)}")
    finally:
        if 'state' in user_state.get(message.from_user.id, {}):
            del user_state[message.from_user.id]["state"]

@dp.callback_query(lambda call: call.data == "remove_post_channel")
async def remove_post_channel(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    with sqlite3.connect('anime_bot.db') as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE channel_type = 'post'")
        conn.commit()
    await call.answer("✅ Post kanal o'chirildi!", show_alert=True)
    await post_channel_menu(call)

@dp.callback_query(lambda call: call.data == "back_to_channels")
async def back_to_channels_menu(call: types.CallbackQuery):
    await channel_settings(await bot.send_message(call.from_user.id, "Kanal sozlamalari:"))

@dp.callback_query(lambda call: call.data == "mandatory_channel_menu")
async def mandatory_channel_menu(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel_id, channel_name, channel_type 
                FROM channels 
                WHERE channel_type IN ('mandatory', 'additional_mandatory')
                ORDER BY 
                    CASE WHEN channel_type = 'mandatory' THEN 1 ELSE 2 END,
                    id
            """)
            channels = cursor.fetchall()
        text = "🔔 Majburiy obuna kanallari:\n"
        if channels:
            for idx, (db_id, channel_id, channel_name, channel_type) in enumerate(channels, 1):
                text += f"{idx}. {channel_name or channel_id} ({'Asosiy' if channel_type == 'mandatory' else 'Qoʻshimcha'})\n"
        else:
            text += "ℹ️ Hozircha kanallar qo'shilmagan"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Asosiy kanal qo'shish", callback_data="add_main_mandatory")],
            [InlineKeyboardButton(text="➕ Qo'shimcha kanal qo'shish", callback_data="add_additional_mandatory")],
            [InlineKeyboardButton(text="➖ Kanal o'chirish", callback_data="remove_mandatory_channel")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_channels")]
        ])
        await call.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)

@dp.callback_query(lambda call: call.data == "add_main_mandatory")
async def add_main_mandatory_channel(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    user_state[call.from_user.id] = {
        "state": "waiting_main_mandatory_channel",
        "channel_type": "mandatory"
    }
    await call.message.answer(
        "Asosiy majburiy kanalni yuboring (faqat 1 ta bo'lishi mumkin):\n"
        "Format: @username yoki https://t.me/... yoki -100...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="mandatory_channel_menu")]
        ])
    )

@dp.callback_query(lambda call: call.data == "add_additional_mandatory")
async def add_additional_mandatory_channel(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    user_state[call.from_user.id] = {
        "state": "waiting_additional_mandatory_channel",
        "channel_type": "additional_mandatory"
    }
    await call.message.answer(
        "Qo'shimcha majburiy kanalni yuboring (cheksiz sonida qo'shishingiz mumkin):\n"
        "Format: @username yoki https://t.me/... yoki -100...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="mandatory_channel_menu")]
        ])
    )

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") in 
            ["waiting_main_mandatory_channel", "waiting_additional_mandatory_channel"])
async def process_new_mandatory_channel(message: types.Message):
    user_data = user_state[message.from_user.id]
    channel_type = user_data["channel_type"]
    try:
        raw_input = message.text.strip()
        if raw_input.startswith(("https://t.me/", "t.me/")):
            channel_id = "@" + raw_input.split("/")[-1]
        elif raw_input.startswith("-100") and raw_input[4:].isdigit():
            channel_id = raw_input
        elif raw_input.startswith("@"):
            channel_id = raw_input
        else:
            raise ValueError("Noto'g'ri format")
        chat = await bot.get_chat(channel_id)
        bot_member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            raise ValueError("Bot kanalda admin emas")
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            if channel_type == "mandatory":
                cursor.execute("DELETE FROM channels WHERE channel_type = 'mandatory'")
            cursor.execute("""
                INSERT INTO channels (channel_type, channel_id, channel_name)
                VALUES (?, ?, ?)
            """, (channel_type, channel_id, chat.title))
            conn.commit()
        await message.answer(
            f"✅ {'Asosiy' if channel_type == 'mandatory' else 'Qoʻshimcha'} kanal qo'shildi!\n"
            f"📢 Nomi: {chat.title}\n"
            f"🆔 ID: {channel_id}"
        )
        del user_state[message.from_user.id]
        await mandatory_channel_menu(await bot.send_message(message.from_user.id, "Kanal menyusi:"))
    except ValueError as e:
        await message.answer(f"❌ {str(e)}\nQayta urinib ko'ring:")
    except exceptions.TelegramAPIError as e:
        await message.answer(f"❌ Telegram xatosi: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {str(e)}")
    finally:
        user_state.pop(message.from_user.id, None)

@dp.callback_query(lambda call: call.data == "remove_mandatory_channel")
async def remove_mandatory_channel_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel_id, channel_name, channel_type 
                FROM channels 
                WHERE channel_type IN ('mandatory', 'additional_mandatory')
                ORDER BY id
            """)
            channels = cursor.fetchall()
        if not channels:
            return await call.answer("ℹ️ O'chirish uchun kanal mavjud emas", show_alert=True)
        buttons = []
        for idx, (db_id, cid, name, ctype) in enumerate(channels, 1):
            channel_type = "Asosiy" if ctype == 'mandatory' else "Qo'shimcha"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{idx}. {name or cid} ({channel_type})",
                    callback_data=f"remove_channel_{db_id}"
                )
            ])
        buttons.append([
            InlineKeyboardButton(text="🗑 Barchasini O'chirish", callback_data="remove_all_channels"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="mandatory_channel_menu")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(
            "O'chirish uchun kanalni tanlang:\n" +
            "\n".join([f"{idx}. {name or cid} ({'Asosiy' if ctype == 'mandatory' else 'Qoʻshimcha'})" 
                      for idx, (_, cid, name, ctype) in enumerate(channels, 1)]),
            reply_markup=keyboard
        )
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)

@dp.callback_query(lambda call: call.data == "remove_all_channels")
async def remove_all_channels_confirm(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="confirm_remove_all"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="remove_mandatory_channel")
        ]
    ])
    await call.message.edit_text(
        "⚠️ Barcha majburiy kanallarni o'chirishni tasdiqlaysizmi?\n"
        "Bu amalni qaytarib bo'lmaydi!",
        reply_markup=keyboard
    )

@dp.callback_query(lambda call: call.data == "confirm_remove_all")
async def remove_all_channels(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE channel_type IN ('mandatory', 'additional_mandatory')")
            conn.commit()
        await call.answer("✅ Barcha majburiy kanallar o'chirildi!", show_alert=True)
        await mandatory_channel_menu(call)
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)

@dp.callback_query(lambda call: call.data.startswith("remove_channel_"))
async def remove_mandatory_channel_confirm(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    channel_db_id = call.data.replace("remove_channel_", "")
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel_id, channel_name, channel_type 
                FROM channels 
                WHERE id = ?
            """, (channel_db_id,))
            channel = cursor.fetchone()
            if not channel:
                return await call.answer("❌ Kanal topilmadi!", show_alert=True)
            channel_id, channel_name, channel_type = channel
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_remove_{channel_db_id}"),
                    InlineKeyboardButton(text="❌ Bekor qilish", callback_data="remove_mandatory_channel")
                ]
            ])
            await call.message.edit_text(
                f"⚠️ Kanalni o'chirishni tasdiqlaysizmi?\n"
                f"📢 Nomi: {channel_name or 'Nomsiz'}\n"
                f"🆔 ID: {channel_id}\n"
                f"📌 Turi: {'Asosiy' if channel_type == 'mandatory' else 'Qoʻshimcha'}",
                reply_markup=keyboard
            )
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)

@dp.callback_query(lambda call: call.data.startswith("confirm_remove_"))
async def remove_channel_final(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    channel_db_id = call.data.replace("confirm_remove_", "")
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id, channel_name, channel_type FROM channels WHERE id = ?", (channel_db_id,))
            channel = cursor.fetchone()
            if not channel:
                return await call.answer("❌ Kanal topilmadi!", show_alert=True)
            channel_id, channel_name, channel_type = channel
            cursor.execute("DELETE FROM channels WHERE id = ?", (channel_db_id,))
            conn.commit()
            await call.answer(
                f"✅ Kanal o'chirildi: {channel_name or channel_id}",
                show_alert=True
            )
            await mandatory_channel_menu(call)
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)

@dp.message(lambda message: message.text == "👨‍💻 Adminlar")
async def manage_admins(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin Qo'shish", callback_data="add_admin")],
        [InlineKeyboardButton(text="🗑 Admin O'chirish", callback_data="remove_admin")],
        [InlineKeyboardButton(text="📋 Adminlar Ro'yxati", callback_data="list_admins")],
        [InlineKeyboardButton(text="📦 Bazani Ko'chirish", callback_data="transfer_db")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_admin")]
    ])
    await message.answer("👨‍💻 Adminlar boshqaruvi", reply_markup=keyboard)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TransferDB(StatesGroup):
    waiting_target_bot = State()
    waiting_db_file = State()
    waiting_confirmation = State()

@dp.callback_query(F.data == "transfer_db")
async def transfer_db_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="📤 Bazani Yuklab Olish", callback_data="download_db"),
        InlineKeyboardButton(text="📥 Bazani Yuklash", callback_data="upload_db"),
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="manage_admins")
    )
    builder.adjust(1)
    await call.message.edit_text(
        "📦 Bazani boshqa botga ko'chirish:\n"
        "1. 📤 Yuklab olish - hozirgi bazani fayl sifatida yuklab olish\n"
        "2. 📥 Yuklash - boshqa botdan yuklangan bazani qabul qilish",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "download_db")
async def download_database(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    temp_dir = tempfile.mkdtemp()
    try:
        db_path = 'anime_bot.db'
        if not os.path.exists(db_path):
            await call.answer("❌ Baza fayli topilmadi!", show_alert=True)
            return
        temp_db_path = os.path.join(temp_dir, "anime_bot.db")
        shutil.copy2(db_path, temp_db_path)
        with open(temp_db_path, 'rb') as db_file:
            await bot.send_document(
                chat_id=call.from_user.id,
                document=BufferedInputFile(
                    db_file.read(),
                    filename="anime_bot.db"
                ),
                caption="📦 Bot bazasi fayli"
            )
        await call.answer("✅ Bazani yuklab olish muvaffaqiyatli yakunlandi!", show_alert=True)
    except Exception as e:
        logger.error(f"Database download error: {e}")
        await call.answer(f"❌ Xatolik yuz berdi: {str(e)}", show_alert=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@dp.callback_query(F.data == "upload_db")
async def upload_db_start(call: types.CallbackQuery, state: FSMContext):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    await state.set_state(TransferDB.waiting_db_file)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="cancel_db_upload"))
    await call.message.edit_text(
        "📥 Bazani yuklash:\n"
        "1. SQLite formatidagi baza faylini yuboring\n"
        "2. Fayl .db yoki .sqlite kengaytmasiga ega bo'lishi kerak\n"
        "3. Yuklash jarayoni avtomatik boshlanadi\n"
        "⚠️ Diqqat: Bu mavjud bazani to'liq almashtirishi mumkin!",
        reply_markup=builder.as_markup()
    )

@dp.message(TransferDB.waiting_target_bot)
async def get_target_bot(message: types.Message, state: FSMContext):
    target_bot = message.text.strip()
    is_token = ":" in target_bot and len(target_bot.split(":")) == 2
    is_username = target_bot.startswith("@") and len(target_bot) > 1
    if not (is_token or is_username):
        await message.answer(
            "❌ Noto'g'ri format! Bot tokeni yoki username ni to'g'ri kiriting:\n"
            "Misol: <code>1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11</code> yoki <code>@bot_username</code>",
            parse_mode="HTML"
        )
        return
    await state.update_data(target_bot=target_bot)
    await state.set_state(TransferDB.waiting_db_file)
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🔙 Bekor qilish"))
    await message.answer(
        "📎 Endi yuklamoqchi bo'lgan bazani fayl sifatida yuboring (anime_bot.db)",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

@dp.message(TransferDB.waiting_db_file, F.document)
async def process_db_file(message: types.Message, state: FSMContext):
    if not message.document or message.document.file_name != "anime_bot.db":
        await message.answer("❌ Iltimos, anime_bot.db faylini yuboring!")
        return
    temp_dir = tempfile.mkdtemp()
    temp_db_path = os.path.join(temp_dir, "anime_bot.db")
    try:
        file = await bot.get_file(message.document.file_id)
        await bot.download_file(file.file_path, temp_db_path)
        validation_result = await validate_database(temp_db_path)
        if not validation_result["valid"]:
            raise ValueError(validation_result["message"])
        await state.update_data(
            temp_db_path=temp_db_path,
            temp_dir=temp_dir,
            anime_count=validation_result["anime_count"],
            episodes_count=validation_result["episodes_count"],
            ongoing_count=validation_result["ongoing_count"]
        )
        builder = InlineKeyboardBuilder()
        builder.add(
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data="confirm_db_transfer"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data="cancel_db_transfer")
        )
        await message.answer(
            f"📦 Bazani qabul qilish:\n"
            f"• Anime lar soni: {validation_result['anime_count']} ta\n"
            f"• Epizodlar soni: {validation_result['episodes_count']} ta\n"
            f"• Davom etayotganlar: {validation_result['ongoing_count']} ta\n"
            f"⚠️ Diqqat:\n"
            f"• Eski animelar saqlanib qoladi\n"
            f"• Yangi animelar qo'shiladi\n"
            f"• Bir xil kodli animelar yangilanmaydi\n"
            f"Bazani qabul qilishni tasdiqlaysizmi?",
            reply_markup=builder.as_markup()
        )
        await state.set_state(TransferDB.waiting_confirmation)
    except Exception as e:
        logger.error(f"Database processing error: {e}")
        await message.answer(f"❌ Xatolik: {str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        await state.clear()

async def validate_database(db_path: str) -> dict:
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        required_tables = {'anime', 'episodes', 'ongoing_anime'}
        missing_tables = required_tables - tables
        if missing_tables:
            return {
                "valid": False,
                "message": f"Quyidagi jadvallar topilmadi: {', '.join(missing_tables)}"
            }
        try:
            cursor.execute("SELECT code, title FROM anime LIMIT 1")
            cursor.execute("SELECT anime_code, episode_number FROM episodes LIMIT 1")
            cursor.execute("SELECT anime_code FROM ongoing_anime LIMIT 1")
        except sqlite3.Error as e:
            return {
                "valid": False,
                "message": f"Jadval strukturasida xatolik: {str(e)}"
            }
        cursor.execute("SELECT COUNT(*) FROM anime")
        anime_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM episodes")
        episodes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ongoing_anime")
        ongoing_count = cursor.fetchone()[0]
        return {
            "valid": True,
            "anime_count": anime_count,
            "episodes_count": episodes_count,
            "ongoing_count": ongoing_count
        }
    except Exception as e:
        return {
            "valid": False,
            "message": f"Bazani tekshirishda xatolik: {str(e)}"
        }
    finally:
        if conn:
            conn.close()

@dp.callback_query(F.data == "confirm_db_transfer", StateFilter(TransferDB.waiting_confirmation))
async def confirm_db_transfer(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    temp_db_path = data.get('temp_db_path')
    temp_dir = data.get('temp_dir')
    if not temp_db_path or not os.path.exists(temp_db_path):
        await call.message.answer("❌ Vaqtinchalik baza fayli topilmadi.")
        await state.clear()
        return
    transferred = {'anime': 0, 'episodes': 0, 'ongoing': 0}
    skipped = {'anime': 0, 'episodes': 0, 'ongoing': 0}
    conflicts_resolved = 0
    added_anime = []
    conflict_anime = []
    try:
        with sqlite3.connect('anime_bot.db') as main_conn, sqlite3.connect(temp_db_path) as temp_conn:
            main_conn.execute("PRAGMA foreign_keys = ON")
            main_conn.execute("PRAGMA journal_mode = WAL")
            main_cursor = main_conn.cursor()
            temp_cursor = temp_conn.cursor()
            main_cursor.execute("""
                CREATE TEMPORARY TABLE IF NOT EXISTS code_mapping (
                    old_code TEXT PRIMARY KEY,
                    new_code TEXT NOT NULL
                )
            """)
            temp_cursor.execute("SELECT code, title, country, language, year, genre, description, image, video FROM anime")
            for row in temp_cursor.fetchall():
                original_code = row[0]
                title = row[1]
                new_code = original_code
                is_conflict = False
                main_cursor.execute("SELECT title FROM anime WHERE code = ?", (original_code,))
                existing = main_cursor.fetchone()
                if existing:
                    if existing[0] == title:
                        main_cursor.execute(
                            "INSERT OR IGNORE INTO code_mapping (old_code, new_code) VALUES (?, ?)",
                            (original_code, original_code)
                        )
                        skipped['anime'] += 1
                        continue
                    else:
                        counter = 1
                        while True:
                            new_code = f"{original_code}_{counter}"
                            main_cursor.execute("SELECT 1 FROM anime WHERE code = ?", (new_code,))
                            if not main_cursor.fetchone():
                                break
                            counter += 1
                        is_conflict = True
                        conflicts_resolved += 1
                        conflict_anime.append(f"{title} (kod: {original_code} → {new_code})")
                try:
                    main_cursor.execute("""
                        INSERT OR IGNORE INTO anime (
                            code, title, country, language, year, genre, 
                            description, image, video
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (new_code, *row[1:]))
                    main_cursor.execute(
                        "INSERT OR REPLACE INTO code_mapping (old_code, new_code) VALUES (?, ?)",
                        (original_code, new_code)
                    )
                    if main_cursor.rowcount > 0:
                        transferred['anime'] += 1
                        added_anime.append(f"{title} (kod: {new_code})")
                except sqlite3.Error as e:
                    skipped['anime'] += 1
                    logging.error(f"Anime insert error (code: {new_code}): {e}")
                    continue
            main_conn.commit()
            temp_cursor.execute("""
                SELECT e.anime_code, e.episode_number, e.video_file_id
                FROM episodes e
                ORDER BY e.anime_code, e.episode_number
            """)
            for anime_code, ep_num, video_id in temp_cursor.fetchall():
                main_cursor.execute(
                    "SELECT new_code FROM code_mapping WHERE old_code = ?",
                    (anime_code,)
                )
                mapping = main_cursor.fetchone()
                if not mapping:
                    skipped['episodes'] += 1
                    logging.warning(f"Episode skipped - no mapping for anime: {anime_code}")
                    continue
                new_code = mapping[0]
                try:
                    main_cursor.execute(
                        "SELECT 1 FROM episodes WHERE anime_code = ? AND episode_number = ?",
                        (new_code, ep_num)
                    )
                    if main_cursor.fetchone():
                        skipped['episodes'] += 1
                        continue
                    main_cursor.execute("""
                        INSERT INTO episodes (anime_code, episode_number, video_file_id) 
                        VALUES (?, ?, ?)
                    """, (new_code, ep_num, video_id))
                    transferred['episodes'] += 1
                except sqlite3.IntegrityError as e:
                    if "FOREIGN KEY constraint failed" in str(e):
                        skipped['episodes'] += 1
                        logging.error(f"Foreign key error - anime {new_code} not found for episode {ep_num}")
                    else:
                        raise
                except sqlite3.Error as e:
                    skipped['episodes'] += 1
                    logging.error(f"Episode insert error (anime: {new_code}, ep: {ep_num}): {e}")
            main_conn.commit()
            temp_cursor.execute("SELECT anime_code FROM ongoing_anime")
            for (anime_code,) in temp_cursor.fetchall():
                main_cursor.execute(
                    "SELECT new_code FROM code_mapping WHERE old_code = ?",
                    (anime_code,)
                )
                mapping = main_cursor.fetchone()
                if not mapping:
                    skipped['ongoing'] += 1
                    continue
                new_code = mapping[0]
                try:
                    main_cursor.execute(
                        "INSERT OR IGNORE INTO ongoing_anime (anime_code) VALUES (?)",
                        (new_code,)
                    )
                    if main_cursor.rowcount > 0:
                        transferred['ongoing'] += 1
                except sqlite3.Error as e:
                    skipped['ongoing'] += 1
                    logging.error(f"Ongoing insert error: {e}")
            main_conn.commit()
            report = [
                "📊 Ko'chirish natijalari:",
                f"• Anime: {transferred['anime']} ta qo'shildi, {skipped['anime']} ta o'tkazib yuborildi",
                f"• Epizodlar: {transferred['episodes']} ta qo'shildi, {skipped['episodes']} ta o'tkazib yuborildi",
                f"• Ongoing: {transferred['ongoing']} ta qo'shildi, {skipped['ongoing']} ta o'tkazib yuborildi",
                f"• Kod konfliktlari: {conflicts_resolved} ta hal qilindi"
            ]
            if added_anime:
                report.append("\n➕ Yangi animelar:")
                report.extend(added_anime[:5])
                if len(added_anime) > 5:
                    report.append(f"... va yana {len(added_anime) - 5} ta")
            if conflict_anime:
                report.append("\n🛠 Kodlari o'zgartirilgan animelar:")
                report.extend(conflict_anime[:3])
                if len(conflict_anime) > 3:
                    report.append(f"... va yana {len(conflict_anime) - 3} ta")
            full_report = "\n".join(report)
            if len(full_report) > 4000:
                parts = [full_report[i:i + 4000] for i in range(0, len(full_report), 4000)]
                for part in parts:
                    await call.message.answer(part)
            else:
                await call.message.answer(full_report)
    except sqlite3.Error as e:
        logging.error(f"Database transfer failed: {e}", exc_info=True)
        await call.message.answer(f"❌ Ma'lumotlar bazasi xatosi: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error in database transfer: {e}", exc_info=True)
        await call.message.answer(f"❌ Kutilmagan xatolik yuz berdi: {str(e)}")
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        await state.clear()

@dp.callback_query(F.data == "cancel_db_transfer", StateFilter(TransferDB.waiting_confirmation))
async def cancel_db_transfer(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    temp_dir = data.get('temp_dir')
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    await call.message.answer("❌ Baza qabul qilinmadi")
    await state.clear()

class AddAdmin(StatesGroup):
    waiting_user_id = State()

@dp.callback_query(lambda call: call.data == "add_admin")
async def add_admin_start(call: types.CallbackQuery, state: FSMContext):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    await state.set_state(AddAdmin.waiting_user_id)
    await call.message.answer(
        "➕ Yangi admin qo'shish uchun foydalanuvchi ID sini yuboring:\n"
        "Foydalanuvchi ID sini olish uchun @userinfobot dan foydalanishingiz mumkin.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
            resize_keyboard=True
        )
    )
    await call.answer()

@dp.message(AddAdmin.waiting_user_id)
async def add_admin_process(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await state.clear()
        await cancel_action(message)
        return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Faqat raqam kiriting:")
        return
    try:
        user = await bot.get_chat(user_id)
    except exceptions.TelegramAPIError:
        await message.answer("❌ Bunday ID li foydalanuvchi topilmadi yoki bot bloklangan!")
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            await message.answer("ℹ️ Bu foydalanuvchi allaqachon admin!")
            return
        cursor.execute(
            "INSERT INTO admins (user_id, username, added_by) VALUES (?, ?, ?)",
            (user_id, user.username or f"user_{user_id}", message.from_user.id)
        )
        conn.commit()
        await message.answer(
            f"✅ Yangi admin muvaffaqiyatli qo'shildi!\n"
            f"👤 Foydalanuvchi: {user.full_name}\n"
            f"🆔 ID: {user_id}\n"
            f"📌 Username: @{user.username or 'yoq'}"
        )
        try:
            await bot.send_message(
                user_id,
                f"🎉 Tabriklaymiz! Siz {message.from_user.full_name} tomonidan "
                f"bot admini qilib tayinlandingiz!\n"
                f"Endi siz /admin buyrug'i orqali admin panelga kirishingiz mumkin."
            )
        except exceptions.TelegramAPIError as e:
            logging.error(f"Yangi adminga xabar yuborishda xatolik: {e}")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        await state.clear()
        conn.close()

@dp.callback_query(lambda call: call.data == "list_admins")
async def list_admins(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT a.user_id, a.username, a.added_at, 
                   b.username as added_by_username
            FROM admins a
            LEFT JOIN admins b ON a.added_by = b.user_id
            ORDER BY a.added_at
        """)
        admins = cursor.fetchall()
        if not admins:
            await call.message.answer("ℹ️ Hozircha adminlar ro'yxati bo'sh")
            return
        text = "👨‍💻 Adminlar ro'yxati:\n"
        for idx, (user_id, username, added_at, added_by) in enumerate(admins, 1):
            text += (
                f"{idx}. ID: {user_id}\n"
                f"   👤 Username: @{username or 'yoq'}\n"
                f"   📅 Qo'shilgan: {added_at}\n"
                f"   🛠 Qo'shgan admin: @{added_by or 'yoq'}\n"
            )
        await call.message.answer(text)
    except Exception as e:
        await call.message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data == "remove_admin")
async def remove_admin_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT user_id, username 
            FROM admins 
            WHERE user_id != ?
            ORDER BY username
        """, (ADMIN_ID,))
        admins = cursor.fetchall()
        if not admins:
            await call.answer("ℹ️ O'chirish uchun adminlar mavjud emas", show_alert=True)
            return
        buttons = []
        for user_id, username in admins:
            buttons.append([InlineKeyboardButton(
                text=f"❌ @{username or user_id}",
                callback_data=f"remove_admin_{user_id}"
            )])
        buttons.append([InlineKeyboardButton(
            text="🔙 Orqaga",
            callback_data="manage_admins"
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(
            "🗑 Admin o'chirish uchun tanlang:\n"
            "⚠️ Asosiy adminni o'chirib bo'lmaydi!",
            reply_markup=keyboard
        )
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data.startswith("remove_admin_"))
async def remove_admin_confirm(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    user_id = int(call.data.replace("remove_admin_", ""))
    if user_id == ADMIN_ID:
        await call.answer("❌ Asosiy adminni o'chirib bo'lmaydi!", show_alert=True)
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username FROM admins WHERE user_id = ?", (user_id,))
        admin = cursor.fetchone()
        if not admin:
            await call.answer("❌ Admin topilmadi!", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"confirm_remove_admin_{user_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="remove_admin")
            ]
        ])
        await call.message.edit_text(
            f"⚠️ Adminni o'chirishni tasdiqlaysizmi?\n"
            f"👤 Foydalanuvchi: @{admin[0] or user_id}\n"
            f"🆔 ID: {user_id}",
            reply_markup=keyboard
        )
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
    finally:
        conn.close()

@dp.callback_query(lambda call: call.data.startswith("confirm_remove_admin_"))
async def remove_admin_final(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call, require_owner=True):
        return
    user_id = int(call.data.replace("confirm_remove_admin_", ""))
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username FROM admins WHERE user_id = ?", (user_id,))
        admin = cursor.fetchone()
        if not admin:
            await call.answer("❌ Admin topilmadi!", show_alert=True)
            return
        cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
        await call.answer(f"✅ Admin @{admin[0]} muvaffaqiyatli o'chirildi!", show_alert=True)
        try:
            await bot.send_message(
                user_id,
                f"⚠️ Siz {call.from_user.full_name} tomonidan "
                f"bot adminlaridan o'chirildingiz!\n"
                f"Endi siz /admin buyrug'i orqali admin panelga kira olmaysiz."
            )
        except exceptions.TelegramAPIError as e:
            logging.error(f"O'chirilgan adminga xabar yuborishda xatolik: {e}")
        await manage_admins(call)
    except Exception as e:
        await call.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
    finally:
        conn.close()

# ==================== POST FUNCTIONS ====================

class CreatePost(StatesGroup):
    waiting_anime_code = State()

# ==================== MUHIM: cancel_post_action funksiyasi faqat bitta marta aniqlangan ====================
async def cancel_post_action(message: types.Message, state: FSMContext = None):
    # Clear state if provided
    if state:
        try:
            await state.clear()
        except Exception as e:
            logging.error(f"Error clearing state: {e}")
    # Clear user_state dictionary — BU MUHIM!
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    # Create admin keyboard
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Post Tayyorlash")],
            [KeyboardButton(text="🔙 Admin Panel")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "❌ Post tayyorlash bekor qilindi.",
        reply_markup=keyboard
    )
@dp.message(lambda message: message.text == "📝 Post Tayyorlash")
async def create_post_start(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id, message=message):
        return
    await state.set_state(CreatePost.waiting_anime_code)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
        resize_keyboard=True
    )
    await message.answer(
        "🔢 <b>Post uchun anime kodini kiriting:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.message(CreatePost.waiting_anime_code)
async def get_anime_for_post(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await cancel_post_action(message, state)
        return
    anime_code = message.text.strip()
    if not anime_code.isalnum():
        await message.answer(
            "❌ Noto'g'ri anime kodi! Faqat harflar va raqamlardan foydalaning.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                resize_keyboard=True
            )
        )
        return
    try:
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, country, language, year, genre, image, video 
                FROM anime WHERE code = ?
            """, (anime_code,))
            anime = cursor.fetchone()
            if not anime:
                await message.answer(
                    "❌ Bunday kodli anime topilmadi. Qayta urinib ko'ring:",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
                        resize_keyboard=True
                    )
                )
                return
            title, country, language, year, genre, image, video = anime
            cursor.execute("SELECT COUNT(*) FROM episodes WHERE anime_code = ?", (anime_code,))
            episodes_count = cursor.fetchone()[0]
            cursor.execute("SELECT channel_name FROM channels WHERE channel_type = 'post' LIMIT 1")
            channel = cursor.fetchone()
            channel_name = channel[0] if channel else (await bot.get_me()).username
            post_caption = f"""
‣  Anime: {html.escape(title)}
╭━━━━━━━━━━━━━━━━━━━━━━━━━
• Janr: {html.escape(genre)}
• Qismi: {episodes_count} ta
• Davlat: {html.escape(country)}
• Til: {html.escape(language)}
• Kanal: {html.escape(channel_name)}
╰━━━━━━━━━━━━━━━━━━━━━━━━━
            """
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✨Tomosha Qilish✨", 
                    callback_data=f"watch_{anime_code}"
                )],
                [InlineKeyboardButton(
                    text="📢 Kanalga Yuborish", 
                    callback_data=f"confirm_post_{anime_code}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Admin Panel", 
                    callback_data="back_to_admin"
                )]
            ])
            try:
                if video:
                    await message.answer_video(
                        video=video,
                        caption=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                elif image:
                    await message.answer_photo(
                        photo=image,
                        caption=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    await message.answer(
                        text=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                await state.clear()
            except exceptions.TelegramAPIError as e:
                await message.answer(f"❌ Telegram xatosi: {str(e)}")
                logging.error(f"Telegram API error: {str(e)}")
    except sqlite3.Error as e:
        await message.answer("❌ Ma'lumotlar bazasi xatosi! Iltimos, keyinroq urinib ko'ring.")
        logging.error(f"Database error: {str(e)}")
    except Exception as e:
        await message.answer("❌ Kutilmagan xatolik yuz berdi! Iltimos, keyinroq urinib ko'ring.")
        logging.error(f"Unexpected error: {str(e)}")

@dp.callback_query(lambda call: call.data.startswith("confirm_post_"))
async def confirm_post(call: types.CallbackQuery):
    anime_code = call.data.replace("confirm_post_", "")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Ha, Kanalga Yuborish", 
            callback_data=f"send_post_{anime_code}"
        )],
        [InlineKeyboardButton(
            text="❌ Bekor qilish", 
            callback_data="cancel_post"
        )]
    ])
    await call.message.edit_reply_markup(reply_markup=keyboard)
    await call.answer()

@dp.callback_query(lambda call: call.data.startswith("send_post_"))
async def send_post_to_channel(call: types.CallbackQuery):
    try:
        anime_code = call.data.replace("send_post_", "").strip()
        if not anime_code.isalnum():
            await call.answer("❌ Noto'g'ri anime kodi!", show_alert=True)
            return
        with sqlite3.connect('anime_bot.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, country, language, year, genre, image, video 
                FROM anime WHERE code = ?
            """, (anime_code,))
            anime = cursor.fetchone()
            if not anime:
                await call.answer("❌ Anime topilmadi!", show_alert=True)
                return
            title, country, language, year, genre, image, video = anime
            cursor.execute("SELECT COUNT(*) FROM episodes WHERE anime_code = ?", (anime_code,))
            episodes_count = cursor.fetchone()[0]
            cursor.execute("SELECT channel_id, channel_name FROM channels WHERE channel_type = 'post' LIMIT 1")
            channel = cursor.fetchone()
            if not channel:
                await call.answer("❌ Post kanali o'rnatilmagan!", show_alert=True)
                return
            channel_id, channel_name = channel
            try:
                if str(channel_id).startswith('-100') and str(channel_id)[4:].isdigit():
                    channel_id = int(channel_id)
                elif str(channel_id).isdigit():
                    channel_id = int(f"-100{channel_id}")
            except:
                pass
            bot_username = (await bot.get_me()).username
            channel_display = f"{channel_name}" if channel_name else f"{bot_username}"
            post_caption = f"""
‣  Anime: {title} 
╭━━━━━━━━━━━━━━━━━━━━━━━━━
• Janr: {genre}
• Qismi: {episodes_count} ta
• Davlat: {country}
• Til: {language}
• Kanal: {channel_display}
╰━━━━━━━━━━━━━━━━━━━━━━━━━
            """
            watch_url = f"https://t.me/{bot_username}?start=watch_{anime_code}"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✨Tomosha Qilish✨", 
                    url=watch_url
                )]
            ])
            try:
                if video:
                    msg = await bot.send_video(
                        chat_id=channel_id,
                        video=video,
                        caption=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                elif image:
                    msg = await bot.send_photo(
                        chat_id=channel_id,
                        photo=image,
                        caption=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    msg = await bot.send_message(
                        chat_id=channel_id,
                        text=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                await call.answer("✅ Post kanalga muvaffaqiyatli yuborildi!", show_alert=True)
            except exceptions.ChatNotFound:
                await call.answer("❌ Kanal topilmadi yoki bot admin emas!", show_alert=True)
            except exceptions.BotBlocked:
                await call.answer("❌ Bot kanalda bloklangan!", show_alert=True)
            except exceptions.ChatWriteForbidden:
                await call.answer("❌ Botda kanalga yozish huquqi yo'q!", show_alert=True)
            except exceptions.RetryAfter as e:
                await call.answer(f"❌ Telegram limiti: {e.timeout} soniyadan keyin urinib ko'ring", show_alert=True)
            except Exception as e:
                error_msg = f"❌ Yuborishda xatolik: {str(e)}"
                logging.error(f"Post yuborishda xatolik: {str(e)}")
                await call.answer(error_msg[:200], show_alert=True)
    except sqlite3.Error as e:
        await call.answer("❌ Ma'lumotlar bazasi xatosi!", show_alert=True)
        logging.error(f"Database error: {str(e)}")
    except Exception as e:
        logging.error(f"Unexpected error in send_post: {str(e)}")
        await call.answer("❌ Kutilmagan xatolik yuz berdi!", show_alert=True)

@dp.callback_query(lambda call: call.data == "cancel_post")
async def cancel_post_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        await state.clear()
    except:
        pass
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await cancel_post_action(call.message, state)
    await call.answer("❌ Post yuborish bekor qilindi", show_alert=True)

import logging
import sqlite3
import asyncio
import os
import tempfile
import requests  # YANGI QO'SHILDI: generate_html_post_image_pillow uchun
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
from aiogram import types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import exceptions

class SerialPost(StatesGroup):
    waiting_anime_code = State()
    waiting_episode_number = State()
    waiting_description = State()
    waiting_template = State()
    waiting_media = State()
    waiting_channel = State()
    post_type = State()  # YANGI: "simple" yoki "html"

@dp.message(lambda message: message.text == "🎞 Serial Post Qilish")
async def serial_post_start(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id, message=message):
        return

    # Yangi: Post turini tanlash
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 HTML Template bilan", callback_data="post_type_html")],
        [InlineKeyboardButton(text="📝 Oddiy Post", callback_data="post_type_simple")],
        [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="cancel_serial_post")]
    ])
    await message.answer("Qanday turdagi post yaratmoqchisiz?", reply_markup=keyboard)
    await state.set_state(SerialPost.post_type)

@dp.callback_query(SerialPost.post_type, lambda c: c.data == "post_type_html")
async def handle_html_post_type(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(post_type="html")
    await call.answer()
    await call.message.edit_text("🔢 <b>Serial post qilish uchun anime kodini kiriting:</b>", parse_mode="HTML")
    await state.set_state(SerialPost.waiting_anime_code)

@dp.message(SerialPost.waiting_anime_code)
async def get_serial_anime_code(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await state.clear()
        await cancel_post_action(message)
        return
    anime_code = message.text.strip()
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            await message.answer("❌ Bunday kodli anime topilmadi. Qayta urinib ko'ring:")
            return
        await state.update_data(anime_code=anime_code, anime_title=anime[0])
        await state.set_state(SerialPost.waiting_episode_number)
        cursor.execute("SELECT episode_number FROM episodes WHERE anime_code = ? ORDER BY episode_number", (anime_code,))
        episodes = cursor.fetchall()
        if not episodes:
            await message.answer("❌ Bu anime uchun hech qanday qism topilmadi.")
            return
        buttons = []
        row = []
        for ep in episodes:
            row.append(InlineKeyboardButton(
                text=f"{ep[0]}-qism",
                callback_data=f"select_ep_{ep[0]}"
            ))
            if len(row) >= 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(
            text="🔙 Bekor qilish",
            callback_data="cancel_serial_post"
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"🎬 {anime[0]}\n"
            f"📺 Post qilish uchun qismni tanlang:",
            reply_markup=keyboard
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

@dp.callback_query(SerialPost.waiting_episode_number, lambda c: c.data.startswith("select_ep_"))
async def select_episode_for_post(call: types.CallbackQuery, state: FSMContext):
    episode_number = int(call.data.replace("select_ep_", ""))
    await state.update_data(episode_number=episode_number)
    await state.set_state(SerialPost.waiting_description)
    await call.message.edit_text(
        f"📝 {episode_number}-qism uchun post tavsifini kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="cancel_serial_post")]
        ])
    )
    await call.answer()

@dp.message(SerialPost.waiting_description)
async def get_serial_description(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await state.clear()
        await cancel_post_action(message)
        return
    await state.update_data(description=message.text)
    await state.set_state(SerialPost.waiting_media)
    await message.answer(
        "🖼 Post uchun rasm yoki video yuboring (agar kerak bo'lsa):\n"
        "Agar media yubormasangiz, anime standart rasmi/videosi ishlatiladi",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="⏭️ Media yubormaslik")],
                [KeyboardButton(text="🔙 Bekor qilish")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(SerialPost.waiting_media, lambda m: m.text == "⏭️ Media yubormaslik")
@dp.message(SerialPost.waiting_media, lambda m: m.photo or m.video)
async def get_serial_media(message: types.Message, state: FSMContext):
    if message.text == "🔙 Bekor qilish":
        await state.clear()
        await cancel_post_action(message)
        return

    # Holatdan post_type ni o'qib olamiz
    data = await state.get_data()
    post_type = data.get('post_type', 'simple')  # default: oddiy post

    media_file_id = None
    media_type = None

    if message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = 'photo'
    elif message.video:
        media_file_id = message.video.file_id
        media_type = 'video'
    elif message.text == "⏭️ Media yubormaslik":
        if post_type == "html":
            # HTML Template uchun media majburiy — xato beramiz
            await message.answer("❌ HTML Template uchun rasm majburiy! Iltimos, PNG/JPG rasm yuboring.")
            return  # Holatni o'zgartirmaymiz — qayta rasm so'raymiz
        else:
            # Oddiy postda — media yubormaslik mumkin
            await state.update_data(media_file_id=None, media_type=None)
            await show_template_selection(message, state)  # Shablon tanlashga o'tamiz
            return

    # Media ma'lumotlarini saqlash
    await state.update_data(media_file_id=media_file_id, media_type=media_type)

    # Shablonlarni ko'rsatish
    await show_template_selection(message, state)

# YANGI: show_template_selection funksiyasi tashqariga chiqarildi
async def show_template_selection(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT template_id, template_name FROM post_templates ORDER BY template_id")
        templates = cursor.fetchall()
        if not templates:
            await message.answer("❌ Hech qanday shablon topilmadi. Iltimos, avval shablon qo'shing.")
            await state.clear()
            return

        buttons = []
        row = []
        for temp_id, name in templates:
            row.append(InlineKeyboardButton(
                text=f"ID {temp_id}: {name}",
                callback_data=f"select_template_{temp_id}"
            ))
            if len(row) >= 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton(
            text="⏭️ O'tkazib yuborish",
            callback_data="skip_template_selection"
        )])
        buttons.append([InlineKeyboardButton(
            text="🔙 Bekor qilish",
            callback_data="cancel_serial_post"
        )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await state.set_state(SerialPost.waiting_template)
        await message.answer(
            "📋 Post uchun shablonni tanlang:",
            reply_markup=keyboard
        )
    except Exception as e:
        logging.error(f"Shablonlarni olishda xatolik: {e}")
        await message.answer("❌ Xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.")
    finally:
        conn.close()

@dp.callback_query(SerialPost.waiting_template, lambda c: c.data.startswith("select_template_"))
async def select_post_template(call: types.CallbackQuery, state: FSMContext):
    template_id = int(call.data.replace("select_template_", ""))
    await state.update_data(selected_template_id=template_id)
    await show_channel_selection(call, state)
    await call.answer()

@dp.callback_query(SerialPost.waiting_template, lambda c: c.data == "skip_template_selection")
async def skip_template_selection(call: types.CallbackQuery, state: FSMContext):
    # Hech qanday shablon tanlanmagan, shuning uchun None qilib saqlaymiz
    await state.update_data(selected_template_id=None)
    await show_channel_selection(call, state)
    await call.answer()

# Kanallarni ko'rsatish uchun umumiy funksiya
async def show_channel_selection(call_or_message, state: FSMContext):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels WHERE channel_type = 'post'")
    channels = cursor.fetchall()
    conn.close()

    if not channels:
        text = "❌ Post kanali topilmadi! Iltimos, avval kanal qo'shing."
        if isinstance(call_or_message, types.CallbackQuery):
            await call_or_message.answer(text, show_alert=True)
        else:
            await call_or_message.answer(text)
        await state.clear()
        return

    buttons = []
    for channel_id, channel_name in channels:
        buttons.append([InlineKeyboardButton(
            text=f"📢 {channel_name}",
            callback_data=f"select_channel_{channel_id}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🔙 Bekor qilish",
        callback_data="cancel_serial_post"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(SerialPost.waiting_channel)

    text = "📢 Post qilish uchun kanalni tanlang:"
    if isinstance(call_or_message, types.CallbackQuery):
        await call_or_message.message.edit_text(text, reply_markup=keyboard)
    else:
        await call_or_message.answer(text, reply_markup=keyboard)

# YANGI: generate_html_post_image_pillow funksiyasi
import logging
import sqlite3
import asyncio
import os
import tempfile
# Pillow kutubxonasi kerak
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
import math
# Aiogram kutubxonasi
from aiogram import types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import exceptions

# Global bot obyekti (sizning kodingizda allaqachon yaratilgan)
# from your_main_file import bot  # Agar boshqa faylda bo'lsa

import logging
import asyncio
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
import tempfile

# Global bot obyekti (sizning kodingizda allaqachon e'lon qilingan)
# from your_main_file import bot  # Agar boshqa faylda bo'lsa

def load_font(size, bold=False):
    """Yaxshilangan font yuklash funksiyasi"""
    # Tizim fontlarini tekshirish tartibi
    fonts = [
        # Linux
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans{'-Bold' if bold else ''}.ttf",
        # macOS
        f"/System/Library/Fonts/Arial{' Bold' if bold else ''}.ttf",
        "/System/Library/Fonts/Helvetica.ttf",
        # Windows
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        "C:/Windows/Fonts/calibri{'b' if bold else ''}.ttf",
        # Umumiy
        "arial.ttf" if not bold else "arialbd.ttf",
        "DejaVuSans.ttf" if not bold else "DejaVuSans-Bold.ttf",
        "calibri.ttf" if not bold else "calibrib.ttf",
    ]
    
    for font_path in fonts:
        try:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, size)
                logging.info(f"✅ Font yuklandi: {font_path}")
                return font
        except (OSError, IOError):
            continue
    
    # Agar hech qanday font topilmasa, default font
    logging.warning("⚠️ Tizim font topilmadi, default font ishlatiladi")
    try:
        font = ImageFont.load_default()
        logging.info("✅ Default font yuklandi")
        return font
    except:
        return ImageFont.load_default()

# ==================== MATN QISQARTIRISH FUNKSIYASI ====================
def wrap_text(text, font, max_width, draw_obj, max_words_for_title=999):
    """
    Matnni berilgan kenglikda qatorlarga ajratadi
    Sarlavha uchun max_words_for_title limitini qo'llaydi (999 = cheksiz)
    """
    words = text.split()
    
    # Sarlavha uchun max_words_for_title tekshiruvi
    if len(words) > max_words_for_title and max_words_for_title < 999:
        # Faqat birinchi max_words_for_title ta so'z + "..."
        truncated_text = ' '.join(words[:max_words_for_title]) + "..."
        # Truncated matnni tekshirish
        try:
            bbox = draw_obj.textbbox((0, 0), truncated_text, font=font)
            test_width = bbox[2] - bbox[0]
            if test_width <= max_width:
                return [truncated_text]  # Faqat bitta qator
            else:
                # Agar truncated ham sig'masa, oxirgi so'zni kesib tashlaymiz
                while len(words[:max_words_for_title]) > 1:
                    words = words[:max_words_for_title-1]
                    truncated_text = ' '.join(words) + "..."
                    bbox = draw_obj.textbbox((0, 0), truncated_text, font=font)
                    test_width = bbox[2] - bbox[0]
                    if test_width <= max_width:
                        return [truncated_text]
        except:
            # Xatolik bo'lsa oddiy usul
            return [' '.join(words[:max_words_for_title]) + "..."]
        # Agar hech narsa sig'masa, faqat birinchi so'z + "..."
        return [words[0] + "..."]
    
    # Oddiy wrap_text logikasi (cheksiz so'zlar uchun)
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        try:
            bbox = draw_obj.textbbox((0, 0), test_line, font=font)
            test_width = bbox[2] - bbox[0]
        except:
            try:
                bbox = draw_obj.textbbox((0, 0), test_line, font=font)
                test_width = bbox[2] - bbox[0]
            except:
                test_width = len(test_line) * 10
        
        if test_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines

# ==================== HTML POST RASM GENERATORI ====================
import logging
import math
from io import BytesIO
import tempfile
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw, max_words_for_title=None) -> list:
    words = text.split()
    lines = []
    current_line = []
   
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        test_width = bbox[2] - bbox[0]
       
        if test_width <= max_width:
            current_line.append(word)
            # Faqat sarlavha uchun so'zlar sonini cheklash (agar kerak bo'lsa)
            if max_words_for_title and len(current_line) >= max_words_for_title:
                # So'zlar soni chegarasiga yetganda, lekin to'liq matnni ko'rsatish
                if len(words) > max_words_for_title:
                    lines.append(' '.join(current_line) + '...')
                    return lines
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
   
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def load_font(size, bold=False):
    fonts = [
        "Poppins-Bold.ttf" if bold else "Poppins-Regular.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for font_name in fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()

async def generate_html_post_image_pillow(
    title: str, desc: str, genre: str, file_id: str, anime_code: str, episode_num: int
) -> str:
    """
    Qirqilgan va siljitilgan rasm generator
    O'ng tomondan 25% qirqiladi va chap tomonga siljitiladi
    """
    try:
        logging.info(f"🎨 Rasm yaratish boshlandi: {title}")
        logging.info(f"📁 File ID: {file_id[:20]}...")
        # 1. Rasmni yuklab olish
        try:
            logging.info("🔍 Bot orqali file olish...")
            file = await bot.get_file(file_id)
            logging.info(f"✅ File olingan: {file.file_path}")
            logging.info("📥 File yuklanmoqda...")
            file_bytes_io = await bot.download_file(file.file_path)
            file_bytes = file_bytes_io.getvalue()
            file_bytes_io.close()
            logging.info(f"✅ File yuklandi: {len(file_bytes)} bytes")
        except Exception as file_error:
            logging.error(f"❌ File yuklashda xatolik: {file_error}")
            raise Exception(f"File yuklashda xatolik: {file_error}")
        # BytesIO orqali rasmni ochish
        try:
            image_stream = BytesIO(file_bytes)
            image_stream.seek(0)
            logging.info("🖼️ PIL orqali rasm ochilmoqda...")
            bg_image = Image.open(image_stream).convert("RGBA")
            logging.info(f"✅ Asl rasm o'lchami: {bg_image.size}")
            image_stream.close()
        except Exception as pil_error:
            logging.error(f"❌ PIL da rasm ochishda xatolik: {pil_error}")
            raise Exception(f"Rasm ochishda xatolik: {pil_error}")
        # 2. RASMNI 1920x1080 GA MOSLASHTIRISH + QIRQISH
        original_size = bg_image.size
        if original_size != (1920, 1080):
            logging.info(f"📏 Rasm {original_size} -> 1920x1080 ga o'zgartirilmoqda")
            bg_image = bg_image.resize((1920, 1080), Image.Resampling.LANCZOS)
            logging.info("✅ Rasm 1920x1080 ga resize qilindi")
        else:
            logging.info("✅ Rasm allaqachon 1920x1080")
        # O'NG TOMONDAN 25% QIRQISH + CHAP TOMONGA SILJITISH
        try:
            logging.info("✂️ O'ng tomondan 25% qirqilmoqda...")
            original_width = bg_image.width
            cut_width = int(original_width * 0.25) # 25% qirqish (480px)
            remaining_width = original_width - cut_width # Qolgan 75% (1440px)
            # O'ng tomondan qirqish (1440px dan 1920px gacha)
            cut_region = bg_image.crop((remaining_width, 0, original_width, bg_image.height))
            # Yangi rasm yaratish va qirqilgan qismni chap tomonga siljitish
            new_image = Image.new("RGBA", (original_width, bg_image.height), (0, 0, 0, 0))
            # Chap tomonga qirqilgan qismni joylashtirish (0 dan 480px gacha)
            new_image.paste(cut_region, (0, 0))
            # O'rta qismni joylashtirish (480px dan 1920px gacha)
            middle_part = bg_image.crop((0, 0, remaining_width, bg_image.height))
            new_image.paste(middle_part, (cut_width, 0))
            # Natijani saqlash
            bg_image = new_image
            logging.info(f"✅ Qirqish yakunlandi: {cut_width}px qirqildi va chap tomonga siljitildi")
            logging.info(f"📐 Yangi rasm: {bg_image.size}")
        except Exception as crop_error:
            logging.warning(f"⚠️ Qirqishda xatolik: {crop_error}")
            # Agar xatolik bo'lsa, asl rasm saqlanadi
    except Exception as e:
        logging.error(f"❌ Rasmni yuklashda xatolik: {e}")
        # Fallback rasm
        bg_image = Image.new("RGBA", (1920, 1080), (25, 25, 25, 255))
        draw = ImageDraw.Draw(bg_image)
        fallback_font = load_font(60, bold=True)
        draw.text((100, 100), f"FALLBACK: {title[:20]}...", fill=(255, 255, 255), font=fallback_font)
        logging.info("✅ Fallback rasm tayyor")
    # 3. Dominant rang - YAXSHILANGAN
    try:
        # Markaziy qismdan rang olish
        center_x, center_y = bg_image.size[0] // 2, bg_image.size[1] // 2
        sample_size = 100
        sample = bg_image.crop((
            center_x - sample_size//2,
            center_y - sample_size//2,
            center_x + sample_size//2,
            center_y + sample_size//2
        ))
        # O'rtacha rangni hisoblash
        pixels = sample.load()
        r_total, g_total, b_total, a_total = 0, 0, 0, 0
        pixel_count = 0
        for x in range(sample.size[0]):
            for y in range(sample.size[1]):
                r, g, b, a = pixels[x, y]
                if a > 0: # Shaffof emas
                    r_total += r
                    g_total += g
                    b_total += b
                    a_total += a
                    pixel_count += 1
        if pixel_count > 0:
            dominant_color = (
                int(r_total / pixel_count),
                int(g_total / pixel_count),
                int(b_total / pixel_count)
            )
        else:
            dominant_color = (100, 100, 100)
        logging.info(f"🎨 Dominant rang: {dominant_color}")
    except Exception as e:
        logging.warning(f"⚠️ Rang hisoblashda xatolik: {e}")
        dominant_color = (246, 79, 89)
    # 4. Asosiy rasm yaratish
    final_image = bg_image.copy()
    logging.info("🖼️ Final rasm yaratildi")
    # 5. Chap tomonga gradient - KATTALASHTIRILDI
    try:
        left_width = int(1920 * 0.6) # Kattaroq
        mask = Image.new('L', (left_width, 1080), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon([
            (0, 0),
            (left_width, 0),
            (int(0.8 * left_width), 1080),
            (0, 1080)
        ], fill=255)
        gradient_layer = Image.new("RGBA", (left_width, 1080))
        pixels = gradient_layer.load()
        angle_rad = math.radians(-225)
        dx = math.cos(angle_rad)
        dy = math.sin(angle_rad)
        center_x, center_y = left_width / 2, 1080 / 2
        max_dist = math.sqrt(left_width**2 + 1080**2) / 2
        for x in range(left_width):
            for y in range(1080):
                distance = (x - center_x) * dx + (y - center_y) * dy
                ratio = max(0.0, min(1.0, (distance + max_dist) / (2 * max_dist)))
                r = int(dominant_color[0] * (1 - ratio) + 0 * ratio)
                g = int(dominant_color[1] * (1 - ratio) + 0 * ratio)
                b = int(dominant_color[2] * (1 - ratio) + 0 * ratio)
                a = int(60 + 80 * ratio)
                pixels[x, y] = (r, g, b, a)
        final_image.paste(gradient_layer, (0, 0), mask=mask)
        logging.info("🌈 Gradient qo'shildi - kattaroq")
    except Exception as e:
        logging.warning(f"⚠️ Gradientda xatolik: {e}")
    # 6. YAXSHILANGAN BLUR QISMI
    draw_temp = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    try:
        # Font o'lchamlari - SIZ O'ZGARTIRGAN O'LCHAMLAR
        title_font = load_font(60, bold=True) # Sarlavha
        episode_font = load_font(36, bold=True) # Qism - nomdan kichikroq
        desc_font = load_font(24, bold=False) # Tavsif - ozgina kichik
        btn_font = load_font(20, bold=True) # Tugma
        menu_font = load_font(28, bold=True) # Janrlar
        # MATN O'LCHAMLARINI HISOBLASH
        # Sarlavha uchun to'liq matn bilan
        title_lines = wrap_text(title.upper(), title_font, 1200, draw_temp)
        title_height = len(title_lines) * 65 # Kichikroq line height
        episode_height = 45
        desc_lines = wrap_text(desc, desc_font, 1200, draw_temp)
        desc_height = len(desc_lines) * 40 # Kichikroq line height
        # Tugma
        btn_text = "TOMOSHA QILISH"
        bbox = draw_temp.textbbox((0, 0), btn_text, font=btn_font)
        btn_height = bbox[3] - bbox[1] + 50
        # JAMI MATN BALANDLIGI
        total_text_height = title_height + episode_height + desc_height + btn_height
        # BLUR REGION O'LCHAMLARI
        base_width = 1300
        min_height = total_text_height + 200
        max_height = min(total_text_height + 180, 700)
        blur_width = base_width
        blur_height = max(min_height, max_height)
        # MARKAZGA JOYLASHTIRISH
        blur_x = (1920 - blur_width) // 2
        blur_y = (1080 - blur_height) // 2
        # Pastdan minimal bo'sh joy
        min_bottom_margin = 100
        if blur_y + blur_height > 1080 - min_bottom_margin:
            blur_y = 1080 - blur_height - min_bottom_margin
        # Tepadan minimal joy
        min_top_margin = 120
        if blur_y < min_top_margin:
            blur_y = min_top_margin
        logging.info(f"📏 Matn balandligi: {total_text_height}px")
        logging.info(f"📐 Blur region: {blur_width}x{blur_height}")
        logging.info(f"📍 Joylashuv: ({blur_x}, {blur_y})")
        # BLUR REGION - XAVFSIZ
        safe_blur_x = max(0, blur_x)
        safe_blur_y = max(0, blur_y)
        safe_width = min(blur_width, 1920 - safe_blur_x)
        safe_height = min(blur_height, 1080 - safe_blur_y)
        if safe_width > 0 and safe_height > 0:
            try:
                # Blur region yaratish
                region_for_blur = final_image.crop((safe_blur_x, safe_blur_y, safe_blur_x + safe_width, safe_blur_y + safe_height))
                # ANIQ BLUR EFEKTI
                blurred_region = region_for_blur.filter(ImageFilter.GaussianBlur(radius=25))
                # Shaffoflik - QORA SHAFFOF
                transparent_bg = Image.new('RGBA', blurred_region.size, (0, 0, 0, 0))
                blurred_region = Image.alpha_composite(transparent_bg, blurred_region)
                blurred_region = Image.alpha_composite(blurred_region, Image.new('RGBA', blurred_region.size, (0, 0, 0, 10)))
                # Yumaloq burchakli maska
                mask_round = Image.new('L', (safe_width, safe_height), 0)
                mask_draw = ImageDraw.Draw(mask_round)
                try:
                    mask_draw.rounded_rectangle([0, 0, safe_width, safe_height], radius=50, fill=255)
                except AttributeError:
                    mask_draw.rectangle([0, 0, safe_width, safe_height], fill=255)
                # BLUR NI JOYLASHTIRISH
                final_image.paste(blurred_region, (safe_blur_x, safe_blur_y), mask_round)
                # RAMKA CHIZISH
                draw = ImageDraw.Draw(final_image)
                try:
                    draw.rounded_rectangle(
                        [safe_blur_x, safe_blur_y, safe_blur_x + safe_width, safe_blur_y + safe_height],
                        radius=50,
                        outline=(255, 255, 255, 100),
                        width=1
                    )
                except:
                    draw.rectangle(
                        [safe_blur_x, safe_blur_y, safe_blur_x + safe_width, safe_blur_y + safe_height],
                        outline=(255, 255, 255, 100),
                        width=1
                    )
                # MATN KOORDINATLARI
                caption_x = safe_blur_x + 60
                caption_y = safe_blur_y + 60
                max_text_width = safe_width - 120
            except Exception as blur_error:
                logging.warning(f"⚠️ Blur jarayonida xatolik: {blur_error}")
                # Fallback - qora fon
                draw = ImageDraw.Draw(final_image)
                try:
                    draw.rounded_rectangle(
                        [safe_blur_x, safe_blur_y, safe_blur_x + safe_width, safe_blur_y + safe_height],
                        radius=50,
                        fill=(0, 0, 0, 180)
                    )
                except:
                    draw.rectangle(
                        [safe_blur_x, safe_blur_y, safe_blur_x + safe_width, safe_blur_y + safe_height],
                        fill=(0, 0, 0, 180)
                    )
                caption_x = safe_blur_x + 60
                caption_y = safe_blur_y + 60
                max_text_width = safe_width - 120
        else:
            logging.warning("⚠️ Blur region xavfsiz emas, standart pozitsiya")
            caption_x, caption_y = 360, 240
            max_text_width = 1200 - 80
    except Exception as e:
        logging.warning(f"⚠️ Umumiy blur xatosi: {e}")
        caption_x, caption_y = 360, 240
        max_text_width = 1200 - 80
    # 7. MATNLARNI CHIZISH
    draw = ImageDraw.Draw(final_image)
    current_y = caption_y
    # 8. SARLAVHA - TO'LIQ MATN
    try:
        title_lines = wrap_text(title.upper(), title_font, max_text_width, draw)
        line_height_title = 65 # Kichikroq
        for i, line in enumerate(title_lines):
            text_x = caption_x
            text_y = current_y + (i * line_height_title)
            # KATTA SOYA EFEKTI
            shadow_offset = 4
            shadow_color = (0, 0, 0, 220)
            # Soya nuqtalar
            for dx, dy in [
                (-shadow_offset, -shadow_offset), (0, -shadow_offset), (shadow_offset, -shadow_offset),
                (-shadow_offset, 0), (shadow_offset, 0),
                (-shadow_offset, shadow_offset), (0, shadow_offset), (shadow_offset, shadow_offset)
            ]:
                draw.text((text_x + dx, text_y + dy), line, fill=shadow_color, font=title_font)
            # Asosiy matn - OQ
            draw.text((text_x, text_y), line, fill=(255, 255, 255), font=title_font)
        current_y += len(title_lines) * line_height_title + 30 # Episode ga spacing - kichikroq
        logging.info(f"✅ Sarlavha yozildi: {len(title_lines)} qator - '{title_lines[0] if title_lines else ''}'")
        # DEBUG: Asl title va so'zlar soni
        original_title_words = len(title.split())
        if original_title_words > 2:
            logging.info(f"📝 Sarlavha: {title} ({original_title_words} so'z)")
    except Exception as e:
        logging.warning(f"⚠️ Sarlavhada xatolik: {e}")
        current_y += 100
    # 9. EPISODE - NOMDAN KICHIKROQ
    try:
        episode_text = f"QISM {episode_num}"
        episode_shadow_offset = 3
        # Soya
        for dx, dy in [
            (-episode_shadow_offset, -episode_shadow_offset), (0, -episode_shadow_offset), (episode_shadow_offset, -episode_shadow_offset),
            (-episode_shadow_offset, 0), (episode_shadow_offset, 0),
            (-episode_shadow_offset, episode_shadow_offset), (0, episode_shadow_offset), (episode_shadow_offset, episode_shadow_offset)
        ]:
            draw.text((caption_x + dx, current_y + dy), episode_text, fill=(0,0,0,200), font=episode_font)
        # Asosiy matn
        draw.text((caption_x, current_y), episode_text, fill=(255,255,255), font=episode_font)
        current_y += 45 + 20 # Desc ga spacing - kichikroq
        logging.info(f"✅ Episode yozildi: {episode_text}")
    except Exception as e:
        logging.warning(f"⚠️ Episode xatosi: {e}")
        current_y += 65
    # 10. TAVSIF - KATTA, AJRALIB TURADI
    try:
        desc_lines = wrap_text(desc, desc_font, max_text_width, draw)
        line_height_desc = 30 # Kichikroq
        for line in desc_lines:
            # Engil soya
            draw.text((caption_x + 1, current_y + 1), line, fill=(0,0,0,100), font=desc_font)
            # Asosiy matn - Ozgina kulrang qilib ajratish
            draw.text((caption_x, current_y), line, fill=(220, 220, 220), font=desc_font)
            current_y += line_height_desc
        current_y += 30 # Btn ga spacing - kichikroq
        logging.info(f"✅ Tavsif yozildi: {len(desc_lines)} qator")
    except Exception as e:
        logging.warning(f"⚠️ Tavsif xatosi: {e}")
        current_y += 150
    # 11. KATTA TUGMA - MARKAZDA
    try:
        btn_text = "TOMOSHA QILISH"
        bbox = draw.textbbox((0, 0), btn_text, font=btn_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        padding_x = 20
        padding_y = 15
        btn_w = text_w + 2 * padding_x
        btn_h = text_h + 2 * padding_y
        btn_x = caption_x # Markazga
        btn_y = current_y
        # GRADIENT TUGMA
        start_color = (30, 144, 255) # Ko'k
        end_color = (220, 20, 60) # Qizil
        # Gradient yaratish
        gradient_btn = Image.new('RGB', (btn_w, btn_h))
        btn_draw = ImageDraw.Draw(gradient_btn)
        for x in range(btn_w):
            ratio = x / (btn_w - 1) if btn_w > 1 else 0
            r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
            for y in range(btn_h):
                btn_draw.point((x, y), fill=(r, g, b))
        # Yumaloq burchaklar maskasi
        btn_mask = Image.new('L', (btn_w, btn_h), 0)
        mask_draw = ImageDraw.Draw(btn_mask)
        try:
            mask_draw.rounded_rectangle([0, 0, btn_w, btn_h], radius=30, fill=255)
        except:
            mask_draw.rectangle([0, 0, btn_w, btn_h], fill=255)
        # Gradientni RGBA ga o'tkazish
        gradient_rgba = Image.new('RGBA', (btn_w, btn_h), (0, 0, 0, 0))
        gradient_rgba.paste(gradient_btn, (0, 0), btn_mask)
        # Tugmani joylashtirish
        final_image.paste(gradient_rgba, (btn_x, btn_y), btn_mask)
        # Qalin ramka
        try:
            draw.rounded_rectangle(
                [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
                radius=30,
                outline=(255, 255, 255),
                width=3
            )
        except:
            draw.rectangle(
                [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
                outline=(255, 255, 255),
                width=3
            )
        # Matn - Markazda
        text_x = btn_x + (btn_w - text_w) // 2
        text_y = btn_y + (btn_h - text_h) // 2 - 5
        draw.text((text_x, text_y), btn_text, fill=(255, 255, 255), font=btn_font)
        current_y += btn_h + 20
        logging.info(f"✅ Tugma qo'shildi: {btn_w}x{btn_h}px at ({btn_x}, {btn_y})")
    except Exception as e:
        logging.warning(f"⚠️ Tugma xatosi: {e}")
        current_y += 80
    # 12. JANR MENYUSI - ANIQ VA KATTA
    try:
        menu_y = 60
        menu_x_start = 100
        genres = [g.strip().upper() for g in genre.split(',')] if genre else ["ACTION", "DRAMA", "FANTASY"]
        items = genres[:3] if len(genres) >= 3 else (genres + ["YO'Q"] * 3)[:3]
        menu_x = menu_x_start
        for i, item in enumerate(items):
            bbox = draw.textbbox((0, 0), item, font=menu_font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            # Rangli effekt
            if i == 0:
                fill_color = (255, 215, 0) # Oltin
                stroke_color = (139, 69, 19) # Jigarrang
                stroke_width = 2
            elif i == 1:
                fill_color = (255, 255, 255) # Oq
                stroke_color = (0, 0, 0)
                stroke_width = 1
            else:
                fill_color = (200, 200, 200) # Kulrang
                stroke_color = None
                stroke_width = 0
            # Soya
            draw.text((menu_x + 2, menu_y + 2), item, fill=(0,0,0,150), font=menu_font)
            # Asosiy matn
            draw.text((menu_x, menu_y), item, fill=fill_color, font=menu_font,
                     stroke_width=stroke_width, stroke_fill=stroke_color)
            menu_x += w + 100
        logging.info(f"✅ Janrlar qo'shildi: {items}")
    except Exception as e:
        logging.warning(f"⚠️ Janrlar xatosi: {e}")
        # Fallback janrlar
        draw.text((100, 60), "ACTION", fill=(255,255,255), font=menu_font)
        draw.text((300, 60), "DRAMA", fill=(255,255,255), font=menu_font)
        draw.text((500, 60), "FANTASY", fill=(255,255,255), font=menu_font)
    # 13. SAQLASH - XAVFSIZ
    try:
        temp_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False)
        temp_file_path = temp_file.name
        temp_file.close()
        # RGBA ni RGB ga o'tkazish
        final_image_rgb = final_image.convert("RGB")
        # Saqlash
        final_image_rgb.save(temp_file_path, format="PNG", quality=95, optimize=True)
        # Fayl mavjudligini tekshirish
        if os.path.exists(temp_file_path):
            file_size = os.path.getsize(temp_file_path)
            if file_size > 0 and file_size < 10 * 1024 * 1024: # 10MB dan kichik
                logging.info(f"💾 Rasm saqlandi: {temp_file_path} ({file_size} bytes)")
                return temp_file_path
            else:
                os.unlink(temp_file_path)
                raise ValueError(f"Fayl hajmi noto'g'ri: {file_size}")
        else:
            raise FileNotFoundError(f"Fayl yaratilmadi: {temp_file_path}")
    except Exception as e:
        logging.error(f"❌ Saqlashda xatolik: {e}")
        raise Exception(f"Rasm saqlashda jiddiy xatolik: {e}")
# ==================== SERIAL POST FIXES ====================

@dp.callback_query(SerialPost.post_type, lambda c: c.data == "post_type_simple")
async def handle_simple_post_type(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(post_type="simple")
    await call.answer()
    await call.message.edit_text("🔢 <b>Serial post qilish uchun anime kodini kiriting:</b>", parse_mode="HTML")
    await state.set_state(SerialPost.waiting_anime_code)

@dp.callback_query(SerialPost.post_type, lambda c: c.data == "cancel_serial_post")
async def cancel_serial_post_from_type(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("❌ Post qilish bekor qilindi", show_alert=True)
    await call.message.delete()

@dp.message(SerialPost.waiting_media, lambda m: m.text == "⏭️ Media yubormaslik")
async def handle_no_media_for_simple_post(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_type = data.get('post_type', 'simple')
    
    if post_type == "html":
        await message.answer("❌ HTML Template uchun rasm majburiy! Iltimos, PNG/JPG rasm yuboring.")
        return
    
    # Oddiy post uchun media yubormaslik mumkin
    await state.update_data(media_file_id=None, media_type=None)
    await show_template_selection(message, state)

# Oddiy post uchun kanal tanlashda yuborish logikasini tuzatish
@dp.callback_query(SerialPost.waiting_channel, lambda c: c.data.startswith("select_channel_"))
async def select_serial_channel(call: types.CallbackQuery, state: FSMContext):
    channel_id = call.data.replace("select_channel_", "")
    data = await state.get_data()
    anime_code = data.get('anime_code')
    episode_number = data.get('episode_number')
    post_type = data.get('post_type', 'simple')
    
    if not anime_code or not episode_number:
        await call.answer("❌ Xatolik: Anime kodi yoki qism raqami saqlanmagan!", show_alert=True)
        await state.clear()
        return

    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title, genre, image, video FROM anime WHERE code = ?", (anime_code,))
        anime = cursor.fetchone()
        if not anime:
            await call.answer("❌ Anime topilmadi!", show_alert=True)
            return
        
        title, genre, anime_image, anime_video = anime
        desc = data.get('description', 'Tavsif yo\'q')

        selected_template_id = data.get('selected_template_id')
        if selected_template_id:
            cursor.execute("SELECT template_content, font_style FROM post_templates WHERE template_id = ?", (selected_template_id,))
            template_row = cursor.fetchone()
            if template_row:
                template_content = template_row[0]
                font_style = template_row[1] or 'default'
            else:
                template_content = "<blockquote>\n<b>- {title}</b>  \n<b>- QISM - {episode_number}</b>\n</blockquote>"
                font_style = 'default'
        else:
            template_content = "<blockquote>\n<b>- {title}</b>  \n<b>- QISM - {episode_number}</b>\n</blockquote>"
            font_style = 'default'

        # Shablonni to'ldirish
        raw_caption = template_content.format(title=title, episode_number=episode_number)
        if font_style == "bold":
            post_caption = f"<b>{raw_caption}</b>"
        elif font_style == "italic":
            post_caption = f"<i>{raw_caption}</i>"
        elif font_style == "bold_italic":
            post_caption = f"<b><i>{raw_caption}</i></b>"
        else:
            post_caption = raw_caption

        # ✅ MUHIM: Tugma URL ni TO'G'RI YARATISH
        bot_username = (await bot.get_me()).username
        # Episode uchun to'g'ri URL - episode_ formatida
        watch_url = f"https://t.me/{bot_username}?start=episode_{anime_code}_{episode_number}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨Tomosha Qilish✨", url=watch_url)]
        ])

        # MEDIA: Admin yuborgan media yoki anime media
        media_file_id = data.get('media_file_id')
        media_type = data.get('media_type')
        
        if post_type == "html":
            # HTML post uchun rasm majburiy
            if not media_file_id:
                await call.answer("❌ HTML Template uchun rasm majburiy!", show_alert=True)
                return
                
            try:
                # HTML post logikasi...
                image_path = await generate_html_post_image_pillow(
                    title=title,
                    desc=desc,
                    genre=genre,
                    file_id=media_file_id,
                    bot_username=bot_username,
                    anime_code=anime_code,
                    episode_num=episode_number
                )
                
                with open(image_path, 'rb') as photo:
                    await bot.send_photo(
                        chat_id=channel_id,
                        photo=BufferedInputFile(photo.read(), filename="post.png"),
                        caption=post_caption,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                os.unlink(image_path)
                
            except Exception as e:
                logging.error(f"HTML rasm yaratishda xatolik: {e}")
                await call.answer(f"❌ Rasm yaratishda xatolik: {str(e)}", show_alert=True)
                return
                
        else:
            # ODDIY POST - media mavjudligini tekshirish
            final_media_file_id = media_file_id
            final_media_type = media_type
            
            # Agar admin media yubormagan bo'lsa, anime media ishlatish
            if not final_media_file_id:
                if anime_video:
                    final_media_file_id = anime_video
                    final_media_type = 'video'
                elif anime_image:
                    final_media_file_id = anime_image
                    final_media_type = 'photo'
            
            # Postni yuborish
            if final_media_type == 'photo' and final_media_file_id:
                await bot.send_photo(
                    chat_id=channel_id, 
                    photo=final_media_file_id, 
                    caption=post_caption, 
                    reply_markup=keyboard, 
                    parse_mode="HTML"
                )
            elif final_media_type == 'video' and final_media_file_id:
                await bot.send_video(
                    chat_id=channel_id, 
                    video=final_media_file_id, 
                    caption=post_caption, 
                    reply_markup=keyboard, 
                    parse_mode="HTML"
                )
            else:
                # Hech qanday media yo'q bo'lsa, faqat tekst
                await bot.send_message(
                    chat_id=channel_id, 
                    text=post_caption, 
                    reply_markup=keyboard, 
                    parse_mode="HTML"
                )

        await call.answer("✅ Post muvaffaqiyatli yuborildi!", show_alert=True)
        
    except Exception as e:
        logging.error(f"select_serial_channel xatosi: {e}")
        await call.answer(f"❌ Kutilmagan xatolik: {str(e)}", show_alert=True)
    finally:
        await state.clear()
        conn.close()

@dp.callback_query(SerialPost.waiting_channel, lambda c: c.data == "cancel_serial_post")
async def cancel_serial_post(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("❌ Post qilish bekor qilindi", show_alert=True)
    await call.message.delete()

# ==================== STATISTICS ====================

@dp.message(lambda message: message.text == "📊 Statistika")
async def show_stats(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM anime")
        anime_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM episodes")
        episodes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM subscribers WHERE notifications = TRUE")
        active_subs = cursor.fetchone()[0]
        try:
            blocked_count = 0
            cursor.execute("SELECT user_id FROM subscribers")
            for (user_id,) in cursor.fetchall():
                try:
                    member = await bot.get_chat_member(user_id, user_id)
                    if member.status == ChatMemberStatus.BANNED:
                        blocked_count += 1
                except exceptions.TelegramAPIError as e:
                    if "user not found" in str(e).lower() or "bot was blocked" in str(e).lower():
                        blocked_count += 1
        except Exception as e:
            blocked_count = "Noma'lum"
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) FROM subscribers WHERE DATE(created_at) = ?", (today,))
        today_subs = cursor.fetchone()[0]
        current_month = datetime.now().strftime("%Y-%m")
        cursor.execute("""
            SELECT strftime('%Y-%m', created_at) as month, 
                   COUNT(*) as count
            FROM subscribers
            WHERE strftime('%Y-%m', created_at) = ?
            GROUP BY month
        """, (current_month,))
        monthly_stats = cursor.fetchone()
        monthly_subs = monthly_stats[1] if monthly_stats else 0
        cursor.execute("SELECT COUNT(*) FROM channels WHERE channel_type = 'mandatory'")
        mandatory_channels = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM channels WHERE channel_type = 'post'")
        post_channels = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM questions")
        questions_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM quiz_participants")
        quiz_participants = cursor.fetchone()[0]
        stats_text = f"""
📊 <b>Bot statistikasi:</b>
🎬 <b>Anime lar soni:</b> {anime_count}
📺 <b>Qismlar soni:</b> {episodes_count}
👥 <b>Obunachilar:</b>
├─ Faol obunachilar: {active_subs}
├─ Bugun qo'shilganlar: {today_subs}
├─ Bu oy qo'shilganlar: {monthly_subs}
└─ Bloklanganlar: {blocked_count}
📢 <b>Kanallar:</b>
├─ Majburiy kanallar: {mandatory_channels}
└─ Post kanallari: {post_channels}
❓ <b>Savol-javob:</b>
├─ Savollar soni: {questions_count}
└─ Qatnashchilar soni: {quiz_participants}
"""
        cursor.execute("""
            SELECT strftime('%Y-%m', created_at) as month, 
                   COUNT(*) as count
            FROM subscribers
            GROUP BY month
            ORDER BY month DESC
            LIMIT 6
        """)
        monthly_data = cursor.fetchall()
        if monthly_data:
            stats_text += "\n📈 <b>Oxirgi 6 oylik obunachilar statistikasi:</b>\n"
            for month, count in monthly_data:
                stats_text += f"├─ {month}: {count} ta\n"
            stats_text += "└─ ..."
        await message.answer(stats_text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

# ==================== SUBSCRIBERS MANAGEMENT ====================

@dp.message(lambda message: message.text == "👥 Obunachilar")
async def manage_subscribers(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM subscribers WHERE notifications = TRUE")
    active_count = cursor.fetchone()[0]
    conn.close()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Xabar Yuborish", callback_data="send_to_subs")],
        [InlineKeyboardButton(text="🔙 Admin Panel", callback_data="back_to_admin")]
    ])
    await message.answer(
        f"👥 Obunachilar boshqaruvi\n"
        f"🔔 Faol obunachilar soni: {active_count}",
        reply_markup=keyboard
    )

@dp.callback_query(lambda call: call.data == "send_to_subs")
async def send_to_subs_start(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    user_state[call.from_user.id] = {"state": "waiting_subs_message"}
    await call.message.edit_text("📢 Obunachilarga yubormoqchi bo'lgan xabaringizni yuboring:")

@dp.message(lambda message: user_state.get(message.from_user.id, {}).get("state") == "waiting_subs_message")
async def send_to_subs_process(message: types.Message):
    conn = sqlite3.connect('anime_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM subscribers WHERE notifications = TRUE")
        subscribers = cursor.fetchall()
        success = 0
        failed = 0
        for (user_id,) in subscribers:
            try:
                await bot.send_message(user_id, message.text)
                success += 1
            except Exception as e:
                failed += 1
                logging.error(f"Xabar yuborishda xatolik (user_id={user_id}): {e}")
        await message.answer(
            f"📢 Xabar yuborish natijasi:\n"
            f"✅ Muvaffaqiyatli: {success}\n"
            f"❌ Xatoliklar: {failed}"
        )
        del user_state[message.from_user.id]
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
    finally:
        conn.close()

# ==================== BACK BUTTONS ====================

@dp.message(lambda message: message.text == "🔙 Orqaga")
async def back_from_anime_settings(message: types.Message):
    if not await check_admin(message.from_user.id, message=message):
        return
    await admin_login(message)

@dp.callback_query(lambda call: call.data == "back_to_admin")
async def back_to_admin(call: types.CallbackQuery):
    if not await check_admin(call.from_user.id, call=call):
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
          [KeyboardButton(text="🎥 Anime Sozlash"), KeyboardButton(text="📢 Kanal Sozlash")],
            [KeyboardButton(text="📝 Post Tayyorlash"), KeyboardButton(text="🎞 Serial Post Qilish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Obunachilar")],
            [KeyboardButton(text="👨‍💻 Adminlar"), KeyboardButton(text="⚙️ Qo'shimcha Funksiyalar")],
            
            [KeyboardButton(text="🔙 Bosh Menyu")]
        ],
        resize_keyboard=True
    )
    await call.message.edit_text("👨‍💻 Admin Panel")
    await call.message.answer("Tanlang:", reply_markup=keyboard)

@dp.message(lambda message: message.text == "🔙 Bosh Menyu")
async def back_to_main(message: types.Message):
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    # show_main_menu o'rniga oddiy xabar
    await message.answer("✅ Bosh menyuga qaytdingiz.")

# ==================== MAIN FUNCTION (Global bot ishlatiladi) ====================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Database initialization
    try:
        init_db()
        logging.info("✅ Database initialized successfully")
    except Exception as e:
        logging.error(f"❌ Database initialization failed: {e}")
        return

    try:
        logging.info("🚀 Bot starting...")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Bot failed to start: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    # Railway uchun port sozlamasi
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"🌐 Server port: {port}")
    
    # Asosiy funksiyani ishga tushirish
    asyncio.run(main())
