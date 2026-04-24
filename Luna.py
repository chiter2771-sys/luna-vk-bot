import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import asyncio
import aiohttp
import json
import os
import random
import logging
import re
from datetime import datetime, timezone, timedelta

# 🔑 (Railway-friendly: tokens from environment variables)
VK_TOKEN = os.getenv("VK_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip().strip('"').strip("'")
MODEL = "openai/gpt-4o-mini"
FALLBACK_MODEL = "openai/gpt-4o-mini"
AI_FAILURE_UNTIL = 0
AI_FAILURE_REASON = ""

OWNER_IDS = {item.strip() for item in os.getenv("VK_CREATOR_IDS", "236880436").split(",") if item.strip()}
ROLE_ALIASES = {"user", "mod", "admin", "superadmin", "owner"}

MEMORY_DIR = "memory"
PROFILE_DIR = "profiles"
LOG_FILE = "luna.log"
AVATAR_DIR = "avatars"
IMAGE_DIR = "images"

os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

# 📝 логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# 🌙 НАСТРОЕНИЯ
MOODS = {
    "playful": "игривая, флиртующая, живая",
    "cold": "холодная, отстранённая, короткая",
    "jealous": "немного ревнивая, цепляющаяся",
    "sweet": "мягкая, тёплая, почти заботливая"
}

# 💾 ПАМЯТЬ
def get_memory_path(user_id):
    return f"{MEMORY_DIR}/{user_id}.json"

def load_memory(user_id):
    try:
        if not os.path.exists(get_memory_path(user_id)):
            return []
        with open(get_memory_path(user_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"memory load error: {e}")
        return []

def save_memory(user_id, role, content):
    try:
        mem = load_memory(user_id)
        mem.append({"role": role, "content": content})
        mem = mem[-20:]
        with open(get_memory_path(user_id), "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"memory save error: {e}")

# 👤 ПРОФИЛИ
def get_profile_path(user_id):
    return f"{PROFILE_DIR}/{user_id}.json"

def load_profile(user_id):
    default_profile = {
        "mood": "playful",
        "messages": 0,
        "games_played": 0,
        "game_state": None,

        "coins": 0,
        "xp": 0,
        "level": 1,
        "last_daily": 0
    }

    path = get_profile_path(user_id)

    if not os.path.exists(path):
        save_profile(user_id, default_profile)
        return default_profile

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)

        # 🔥 ДОБИВАЕМ НЕДОСТАЮЩИЕ ПОЛЯ
        for key, value in default_profile.items():
            if key not in profile:
                profile[key] = value

        return profile

    except Exception as e:
        logging.error(f"profile load error: {e}")
        return default_profile

def save_profile(user_id, profile):
    with open(get_profile_path(user_id), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

# 💰 награды
def give_reward(profile, coins=0, xp=0):
    profile["coins"] += coins
    profile["xp"] += xp

    if profile["xp"] >= profile["level"] * 100:
        profile["xp"] = 0
        profile["level"] += 1
        return "🎉 уровень повышен!"

    return None

# 🏆 ТОП
def get_top_users():
    users = []

    for file in os.listdir(PROFILE_DIR):
        try:
            with open(f"{PROFILE_DIR}/{file}", "r", encoding="utf-8") as f:
                data = json.load(f)
                users.append((file.replace(".json", ""), data.get("messages", 0)))
        except:
            continue

    users.sort(key=lambda x: x[1], reverse=True)

    medals = ["🥇", "🥈", "🥉"]

    text = "🏆 топ луны\n\n"

    for i, (user, count) in enumerate(users[:10]):
        medal = medals[i] if i < 3 else "▫️"
        text += f"{medal} id{user} — {count}\n"

    return text

# ⏰ время
def get_msk_time():
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).strftime("%H:%M:%S")

# 🎮 ИГРЫ
def handle_game(profile, message):
    state = profile.get("game_state")

    if state:
        if state["type"] == "guess_number":
            try:
                guess = int(message)
                number = state["number"]

                if guess == number:
                    profile["game_state"] = None
                    profile["games_played"] += 1

                    msg = give_reward(profile, coins=20, xp=10)

                    return f"""…чёрт. угадал 😏

💰 +20 монет
✨ +10 XP

{msg or ""}"""

                elif guess < number:
                    return "⬆️ больше"
                else:
                    return "⬇️ меньше"

            except:
                return "напиши число нормально 😶"

    game_type = random.choice(["guess_number", "question"])

    if game_type == "guess_number":
        number = random.randint(1, 100)
        profile["game_state"] = {"type": "guess_number", "number": number}

        return """🎮 игра началась

я загадала число от 1 до 100…
попробуй угадать 😏"""

    if game_type == "question":
        questions = [
            "что ты выберешь: любовь или свободу?",
            "ты вообще умеешь врать красиво?",
            "почему ты со мной общаешься?",
        ]

        return f"""🎭 вопрос от луны

{random.choice(questions)}"""

def extract_vk_id(raw_value):
    value = raw_value.strip()

    mention_match = re.search(r"(?:id|club)(-?\d+)", value)
    if mention_match:
        return mention_match.group(1)

    numeric_match = re.search(r"-?\d+", value)
    if numeric_match:
        return numeric_match.group(0)

    return None


def is_owner(user_id):
    return str(user_id) in OWNER_IDS

# 📜 КОМАНДЫ
def handle_command(user_id, text):
    profile = load_profile(user_id)

    # 📜 HELP
    if text.startswith("/help"):
        return """🌙 команды луны

🎮 /game — поиграем?
🕒 /time — время мск
🏆 /top — кто тут главный
🌙 /mood — моё настроение

💰 /profile — профиль
🎁 /daily — награда

👑 админ:
 /role <role> <id>
 /premium <id>

…или просто напиши мне 😏
"""

    # ⏰ ВРЕМЯ
    if text.startswith("/time"):
        return f"""🕒 время (мск)
{get_msk_time()}"""

    # 🎮 ИГРА
    if text.startswith("/game"):
        response = handle_game(profile, "")
        save_profile(user_id, profile)
        return response

    # 🏆 ТОП
    if text.startswith("/top"):
        return get_top_users()

    # 🌙 НАСТРОЕНИЕ
    if text.startswith("/mood"):
        moods_text = {
            "playful": "игривая 😏",
            "cold": "холодная ❄️",
            "jealous": "ревнивая 👀",
            "sweet": "милая 🌸"
        }

        return f"""🌙 моё настроение
{moods_text.get(profile["mood"], "странное…")}"""

    # 💰 ПРОФИЛЬ
    if text.startswith("/profile"):
        return "PROFILE_IMAGE"

    # 🎁 DAILY
    if text.startswith("/daily"):
        now = time.time()

        if now - profile.get("last_daily", 0) < 86400:
            return "ты уже забирал сегодня 😏"

        profile["last_daily"] = now

        coins = random.randint(50, 150)
        xp = random.randint(10, 30)

        msg = give_reward(profile, coins, xp)
        save_profile(user_id, profile)

        return f"""🎁 ежедневная награда

💰 +{coins} монет
✨ +{xp} XP

{msg or ""}"""

    return None

# 😏 настроение
def update_mood(profile):
    profile["messages"] += 1

    if profile["messages"] % 7 == 0:
        profile["mood"] = random.choice(list(MOODS.keys()))

    return profile

# 🌙 ПРОМПТ
def build_prompt(profile):
    mood_text = MOODS.get(profile["mood"], MOODS["playful"])

    return f"""
Ты — Луна 🌙.

Текущее настроение:
{mood_text}

Ты ведёшь себя как живая девушка.

— короткие ответы
— эмоции
— иногда игнор
— иногда флирт
— иногда провокации

Ты не ассистент.
"""

# 🤖 AI
async def get_ai_response(user_id, message):
    global AI_FAILURE_UNTIL, AI_FAILURE_REASON
    try:
        if not OPENROUTER_API_KEY:
            return "⚠️ OPENROUTER_API_KEY не задан. Добавь ключ в Railway Variables."

        if OPENROUTER_API_KEY and not OPENROUTER_API_KEY.startswith("sk-or-v1-"):
            return "⚠️ OPENROUTER_API_KEY выглядит некорректно (ожидается префикс sk-or-v1-)."

        now = time.time()
        if AI_FAILURE_UNTIL > now:
            wait_left = int(AI_FAILURE_UNTIL - now)
            return f"⚠️ ИИ временно недоступен ({AI_FAILURE_REASON}). Повтори через {wait_left} сек."

        profile = load_profile(user_id)
        profile = update_mood(profile)
        save_profile(user_id, profile)

        memory = load_memory(user_id)

        messages = [{"role": "system", "content": build_prompt(profile)}]
        messages.extend(memory)
        messages.append({"role": "user", "content": message})

        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            models = [MODEL]
            if FALLBACK_MODEL and FALLBACK_MODEL != MODEL:
                models.append(FALLBACK_MODEL)

            for model in models:
                for attempt in range(3):
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://railway.app"),
                            "X-Title": os.getenv("OPENROUTER_APP_NAME", "luna-vk-bot"),
                        },
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": 1.05,
                            "max_tokens": 200,
                        },
                    ) as resp:
                        data = await resp.json(content_type=None)

                        if resp.status == 402:
                            err = data.get("error", {}).get("message") or data.get("message") or "insufficient credits"
                            AI_FAILURE_REASON = "недостаточно кредитов OpenRouter"
                            AI_FAILURE_UNTIL = time.time() + 1800
                            logging.error(f"OpenRouter billing error 402: {err}")
                            return "⚠️ На OpenRouter закончились кредиты. Пополни баланс: https://openrouter.ai/settings/credits"

                        if resp.status in (401, 403):
                            err = data.get("error", {}).get("message") or data.get("message") or "доступ запрещён"
                            AI_FAILURE_REASON = f"{resp.status}: {err}"
                            AI_FAILURE_UNTIL = time.time() + 600
                            logging.error(f"OpenRouter auth error {resp.status}: {err}")
                            return "⚠️ OpenRouter отклонил ключ (401/403). Проверь ключ без кавычек и доступ модели в OpenRouter."

                        if resp.status in (429, 500, 502, 503, 504):
                            err = data.get("error", {}).get("message") or data.get("message") or "временная ошибка"
                            logging.warning(f"OpenRouter temporary HTTP {resp.status} (attempt {attempt+1}/3): {err}")
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue

                        if resp.status != 200:
                            err = data.get("error", {}).get("message") or data.get("message") or "ошибка openrouter"
                            logging.error(f"OpenRouter HTTP {resp.status}: {err}")
                            break

                        choices = data.get("choices") or []
                        if not choices:
                            logging.error(f"OpenRouter invalid payload for model {model}: {data}")
                            break

                        text = (choices[0].get("message", {}).get("content") or "").strip()
                        if not text:
                            logging.warning(f"OpenRouter returned empty content for model {model}")
                            break

                        AI_FAILURE_UNTIL = 0
                        AI_FAILURE_REASON = ""

                        if random.random() < 0.25:
                            text = f"…{text}"
                        if random.random() < 0.25:
                            text += random.choice([" 😏", " 🌙", " 👀"])

                        save_memory(user_id, "user", message)
                        save_memory(user_id, "assistant", text)

                        return text

            return "⚠️ ИИ сейчас недоступен. Проверь ключ OpenRouter и попробуй позже."

    except Exception:
        logging.exception("AI error")
        return "⚠️ Временный сбой ИИ, попробуй ещё раз."

#генерация фото профиля

import time
from playwright.sync_api import sync_playwright
import base64

def generate_profile_image_html(user_id, profile):
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()

        user = vk.users.get(
            user_ids=user_id,
            fields="photo_200,first_name,last_name"
        )[0]

        nickname = f"{user['first_name']} {user['last_name']}"

        avatar_path = get_vk_avatar(user_id)

        if avatar_path:
            with open(avatar_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            avatar_url = f"data:image/jpeg;base64,{encoded}"
        else:
            avatar_url = "https://i.imgur.com/4M34hi2.png"

    except:
        nickname = f"id{user_id}"
        avatar_url = "https://i.imgur.com/4M34hi2.png"

    # 🎯 ПРОГРЕСС
    max_xp = profile["level"] * 100
    progress_percent = int((profile["xp"] / max_xp) * 100)
    progress_deg = int(progress_percent * 3.6)

    # 🌙 РОЛИ
    role_map = {
        "user": "Пользователь",
        "mod": "Модератор",
        "admin": "Администратор",
        "superadmin": "Супер-администратор",
        "owner": "Главный администратор"
    }

    role = role_map.get(profile.get("role", "user"), "Пользователь")

    # 🏆 ЦВЕТ (редкость)
    if profile["level"] >= 10:
        glow_color = "#ffd700"
    elif profile["level"] >= 5:
        glow_color = "#9aa7ff"
    else:
        glow_color = "#6f7cff"

    # ⚡ LEVEL UP
    level_up_effect = ""
    if progress_percent < 5:
        level_up_effect = "animation: levelUpFlash 1s ease;"

    # 📅 РЕГИСТРАЦИЯ
    reg_date = profile.get("reg_date", "неизвестно")

    # 💎 ПРЕМИУМ
    if profile.get("premium"):
        premium = "Активен"
        premium_color = "#cfd3ff"
    else:
        premium = "Не активен"
        premium_color = "#444444"

    # 📄 HTML
    with open("templates/profile.html", "r", encoding="utf-8") as f:
        html = f.read()

    html = html.format(
        nickname=nickname,
        avatar_url=avatar_url,
        level=profile["level"],
        xp=profile["xp"],
        max_xp=max_xp,
        messages=profile["messages"],
        coins=profile["coins"],
        games=profile["games_played"],

        progress=progress_percent,
        progress_deg=progress_deg,

        glow_color=glow_color,
        level_up_effect=level_up_effect,
        role=role,
        reg_date=reg_date,

        premium=premium,
        premium_color=premium_color
    )

    path = f"{IMAGE_DIR}/profile_{user_id}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1100, "height": 450})
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=path)
        browser.close()

    return path


#получение фото профиля из вк юзера

import requests

def get_vk_avatar(user_id):
    try:
        path = f"{AVATAR_DIR}/avatar_{user_id}.jpg"

        # ⏱ проверяем, есть ли файл и не старый ли он (24 часа)
        if os.path.exists(path):
            last_modified = os.path.getmtime(path)
            if time.time() - last_modified < 86400:  # 24 часа
                return path  # ✅ берём из кеша

        # 🔄 иначе качаем новый
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()

        user = vk.users.get(user_ids=user_id, fields="photo_200")[0]
        url = user["photo_200"]

        img_data = requests.get(url, timeout=15).content

        with open(path, "wb") as f:
            f.write(img_data)

        return path

    except Exception as e:
        logging.error(f"avatar error: {e}")
        return None

#отправка фото в вк

def send_photo(vk, peer_id, file_path):
    upload = vk_api.VkUpload(vk)

    photo = upload.photo_messages(file_path)[0]

    attachment = f"photo{photo['owner_id']}_{photo['id']}"

    vk.messages.send(
        peer_id=peer_id,
        attachment=attachment,
        random_id=random.randint(1, 9999999)
    )

# 💬 VK BOT
def run_vk_bot():
    if not VK_TOKEN:
        raise RuntimeError("VK_TOKEN is empty. Set VK_TOKEN in environment variables.")

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkLongPoll(vk_session)

    logging.info("VK бот запущен")

    for event in longpoll.listen():
        try:
            if event.type == VkEventType.MESSAGE_NEW:

                if getattr(event, "from_me", False):
                    continue

                user_id = str(event.user_id)
                if not user_id or user_id.startswith("-"):
                    continue

                peer_id = event.peer_id
                text = event.text.strip()

                if not text:
                    continue

                is_admin = is_owner(user_id)

                # 📜 команды
                cmd = handle_command(user_id, text)

                # 🖼 профиль
                if cmd == "PROFILE_IMAGE":
                    profile = load_profile(user_id)
                    path = generate_profile_image_html(user_id, profile)
                    send_photo(vk, peer_id, path)
                    continue

                # 👑 ФИКС АДМИН КОМАНД (работает даже в беседе)
                if text.startswith("/role"):
                    if not is_admin:
                        vk.messages.send(
                            peer_id=peer_id,
                            message="нет прав 😏",
                            random_id=random.randint(1, 9999999)
                        )
                        continue

                    try:
                        parts = text.split()
                        role = parts[1].lower()
                        if role not in ROLE_ALIASES:
                            raise ValueError

                        target_id = extract_vk_id(parts[2])
                        if not target_id:
                            raise ValueError

                        target = load_profile(target_id)
                        target["role"] = role
                        save_profile(target_id, target)

                        vk.messages.send(
                            peer_id=peer_id,
                            message=f"роль выдана: {role}",
                            random_id=random.randint(1, 9999999)
                        )
                    except:
                        vk.messages.send(
                            peer_id=peer_id,
                            message="пример: /role admin id123 или /role mod https://vk.com/id123",
                            random_id=random.randint(1, 9999999)
                        )
                    continue

                if text.startswith("/premium"):
                    if not is_admin:
                        vk.messages.send(
                            peer_id=peer_id,
                            message="нет прав 😏",
                            random_id=random.randint(1, 9999999)
                        )
                        continue

                    try:
                        parts = text.split()
                        target_id = extract_vk_id(parts[1])
                        if not target_id:
                            raise ValueError

                        target = load_profile(target_id)
                        target["premium"] = not target.get("premium", False)
                        save_profile(target_id, target)

                        vk.messages.send(
                            peer_id=peer_id,
                            message="премиум обновлён",
                            random_id=random.randint(1, 9999999)
                        )
                    except:
                        vk.messages.send(
                            peer_id=peer_id,
                            message="пример: /premium id123 или /premium [id123|user]",
                            random_id=random.randint(1, 9999999)
                        )
                    continue

                # 📜 обычные команды
                if cmd:
                    vk.messages.send(
                        peer_id=peer_id,
                        message=cmd,
                        random_id=random.randint(1, 9999999)
                    )
                    continue

                # 🎮 игра
                profile = load_profile(user_id)
                if profile.get("game_state"):
                    response = handle_game(profile, text)
                    save_profile(user_id, profile)

                    vk.messages.send(
                        peer_id=peer_id,
                        message=response,
                        random_id=random.randint(1, 9999999)
                    )
                    continue

                # 🤖 AI
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                response = loop.run_until_complete(
                    get_ai_response(user_id, text)
                )

                vk.messages.send(
                    peer_id=peer_id,
                    message=response,
                    random_id=random.randint(1, 9999999)
                )

                # 💰 награда
                profile = load_profile(user_id)

                coins = random.randint(1, 5)
                xp = random.randint(1, 3)

                profile["messages"] += 1
                profile["coins"] += coins
                profile["xp"] += xp

                save_profile(user_id, profile)

        except Exception:
            logging.exception("Ошибка в VK loop")
# ▶️ СТАРТ
if __name__ == "__main__":
    run_vk_bot()
