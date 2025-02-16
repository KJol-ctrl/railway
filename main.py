import pip

pip.main(['install', 'flask'])
pip.main(['install', 'pytelegrambotapi'])

import logging
import asyncio
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ChatPermissions, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
import threading
import datetime
import requests
import json
import re

import os

# Токен бота и настройки
TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(id) for id in os.environ['ADMIN_IDS'].split(',')]
GROUP_ID = int(os.environ['GROUP_ID'])
GROUP_LINK = os.environ['GROUP_LINK']
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Глобальные словари для хранения данных пользователей
user_data = {}
message_counts = {}  # Словарь для подсчета сообщений пользователей
MAX_MESSAGES = 5  # Максимальное количество сообщений

# Класс состояний
class Form(StatesGroup):
    role = State()
    reason = State()
    duration = State()
    complaint = State()

# Функция создания меню
def get_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Рест"), KeyboardButton(text="Жалоба")]
    ])

# Функция создания кнопки "Назад"
def get_back_button():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Назад")]
    ])

# Проверка участия в группе
async def is_member(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(GROUP_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

async def check_message_limit(user_id: int) -> bool:
    if user_id not in message_counts:
        message_counts[user_id] = 0
    message_counts[user_id] += 1
    return message_counts[user_id] <= MAX_MESSAGES

# Обработчик кнопки "Рест"
@dp.message(F.text == "Рест")
async def request_rest(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    if not await is_member(user_id):
        await message.answer("Вы не являетесь участником.", reply_markup=get_menu())
        return
    await message.answer("Пожалуйста, напишите причину реста:", reply_markup=get_back_button())
    await state.set_state(Form.reason)

# Обработчик причины реста
@dp.message(Form.reason)
async def rest_reason(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    if message.text == "Назад":
        await back_to_menu(message, state)
        return
    await state.update_data(reason=message.text)
    await message.answer("Напишите срок реста:")
    await state.set_state(Form.duration)

# Обработчик срока реста
@dp.message(Form.duration)
async def rest_duration(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    if message.text == "Назад":
        await state.set_state(Form.reason)
        await message.answer("Пожалуйста, напишите причину реста заново:", reply_markup=get_back_button())
        return
    data = await state.get_data()
    role = await bot.get_chat_member(GROUP_ID, message.from_user.id)
    admin_message = f'''🔔 <b>Заявка на рест</b>
📌 Роль: {role.custom_title if role.custom_title else 'Неизвестно'}
⚙️ Причина: {data['reason']}
⌛️ Срок: {message.text}'''
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
    await message.answer("Вы отправили заявку.", reply_markup=get_menu())
    await state.clear()

# Обработчик кнопки "Жалоба"
@dp.message(F.text == "Жалоба")
async def complaint(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    if not await is_member(user_id):
        await message.answer("Вы не являетесь участником.", reply_markup=get_menu())
        return
    await message.answer("Опишите вашу жалобу:", reply_markup=get_back_button())
    await state.set_state(Form.complaint)

# Обработчик жалобы
@dp.message(Form.complaint)
async def handle_complaint(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    if message.text == "Назад":
        await back_to_menu(message, state)
        return
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f'''🔔 <b>Новая жалоба от</b> {message.from_user.full_name}:
{message.text}''')
    await message.answer("Вы отправили жалобу.", reply_markup=get_menu())
    await state.clear()

# Обработчик кнопки "Назад"
@dp.message(F.text == "Назад")
async def back_to_menu(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    await message.answer("Вы вернулись в меню.", reply_markup=get_menu())
    await state.clear()

# Обработчик присоединения к чату
@dp.chat_member()
async def user_joins_chat(update: types.ChatMemberUpdated):
    user_id = update.new_chat_member.user.id
    chat_id = update.chat.id
    if chat_id == GROUP_ID:
        if update.new_chat_member.status == "member" and user_id in user_data and not update.new_chat_member.user.is_bot:
            try:
                role = user_data[user_id]["role"]
                await bot.promote_chat_member(chat_id, user_id, 
                    can_change_info=False,
                    can_delete_messages=False,
                    can_invite_users=False,
                    can_restrict_members=False,
                    can_pin_messages=True,
                    can_promote_members=False
                )
                await bot.set_chat_administrator_custom_title(chat_id, user_id, role)
                user_data[user_id]["custom_title"] = role
                
                members = await bot.get_chat_administrators(chat_id)
                tags = []
                emojis = ["⭐️", "🌟", "💫", "⚡️", "🔥", "❤️", "💞", "💕", "❣️", "💌", "🌈", "✨", "🎯", "🎪", "🎨", "🎭", "🎪", "🎢", "🎡", "🎠", "🎪", "🌸", "🌺", "🌷", "🌹", "🌻", "🌼", "💐", "🌾", "🌿", "☘️", "🍀", "🍁", "🍂", "🍃", "🌵", "🌴", "🌳", "🌲", "🎄", "🌊", "🌈", "☀️", "🌤", "⛅️", "☁️", "🌦", "🌨", "❄️", "☃️",  "🌬", "💨", "🌪", "🌫", "🌈", "☔️", "⚡️", "❄️", "🔮", "🎮", "🎲", "🎯", "🎳", "🎪", "🎭", "🎨", "🎬", "🎤", "🎧", "🎼", "🎹", "🥁", "🎷", "🎺", "🎸", "🪕", "🎻", "🎲", "♟", "🎯", "🎳", "🎮", "🎰", "🧩", "🎪", "🎭", "🎨", "🖼", "🎨", "🧵", "🧶", "👑", "💎", "⚜️"]
                
                # Создаем или получаем словарь для хранения эмодзи пользователей
                if 'user_emojis' not in user_data:
                    user_data['user_emojis'] = {}
                
                for member in members:
                    if not member.user.is_bot and member.user.id != user_id and member.status in ["member", "administrator"]:
                        if member.user.username:
                            # Получаем или назначаем уникальный эмодзи для пользователя
                            if member.user.id not in user_data['user_emojis']:
                                available_emojis = [e for e in emojis if e not in user_data['user_emojis'].values()]
                                if available_emojis:
                                    user_data['user_emojis'][member.user.id] = random.choice(available_emojis)
                            
                            emoji = user_data['user_emojis'].get(member.user.id, "👤")
                            tag = f"<a href='tg://user?id={member.user.id}'>{emoji}</a>"
                            tags.append(tag)
                mention_text = " ".join(tags)
                await bot.send_message(
                    chat_id,
                    f'''📢 Новый участник: <b>{update.new_chat_member.user.full_name}</b>
🎭 Роль: <b>{role}</b>
{mention_text}'''
                )
                await bot.send_message(user_id, "Ваша заявка одобрена. Теперь вы можете взаимодействовать с меню.", reply_markup=get_menu())
            except Exception as e:
                logging.error(f"Ошибка при назначении роли: {e}")
                for admin_id in ADMIN_IDS:
                    await bot.send_message(admin_id, f"Ошибка при назначении роли пользователю {update.new_chat_member.user.full_name}: {str(e)}")
        elif update.new_chat_member.status in ["left", "kicked"]:
            if user_id in user_data:
                custom_title = user_data[user_id].get("custom_title", "Неизвестно")
                leave_message = f"😢 Пользователь <b>{update.new_chat_member.user.full_name}</b> с ролью: <b>{custom_title}</b> покинул группу"
                # Отправляем сообщение в группу
                await bot.send_message(chat_id, leave_message)
                # Отправляем сообщение админам
                for admin_id in ADMIN_IDS:
                    await bot.send_message(admin_id, leave_message)
                user_data.pop(user_id, None)

# Обработчик команды /start
@dp.message(F.text.casefold() == "/start")
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    if not await is_member(user_id) and not await check_message_limit(user_id):
        await message.answer("Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом.")
        return
    member = await bot.get_chat_member(GROUP_ID, user_id)
    if member.status in ["member", "administrator", "creator"]:
        await message.answer("Вы уже состоите в группе.", reply_markup=get_menu())
    else:
        remove_keyboard = types.ReplyKeyboardRemove()
        await message.answer(
            "Запустив бота, вы подтверждаете ознакомление с <a href='https://telegra.ph/Pravila-02-08-160'>правилами</a>. Напишите свободную роль, занятые указаны в <a href='https://t.me/stellarpassion/9'>списке</a>. Она должна быть без точки и с большой буквы. Например: Мона",
            disable_web_page_preview=True,
            reply_markup=remove_keyboard
        )
        await state.set_state(Form.role)

# Обработчик выбора роли
@dp.message(Form.role)
async def role_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    role = message.text.strip()
    user_data[user_id] = {"role": role}
    await message.answer(
        f'Перейдите по <a href="{GROUP_LINK}">ссылке</a>. Ваша заявка будет рассмотрена в ближайшее время.',
        disable_web_page_preview=True,
        reply_markup=get_menu()
    )
    admin_message = (
        f"🔔 <b>Заявка на вступление!</b>\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"📌 Роль: {role}"
    )
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
    await state.clear()

# Обработчик команд с животными
@dp.message(F.text.startswith("/"))
async def animal_photo(message: types.Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    if not await is_member(user_id) and not await check_message_limit(user_id):
        await message.answer("Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/stellarpassion/6'>администрации</a>.")
        return
    animal = message.text[1:].lower()
    if UNSPLASH_ACCESS_KEY:
        try:
            response = requests.get(f"https://api.unsplash.com/search/photos?query={animal}&client_id={UNSPLASH_ACCESS_KEY}")
            response.raise_for_status()
            data = response.json()
            if data['results']:
                random_photo = random.choice(data['results'])
                await bot.send_photo(message.chat.id, random_photo['urls']['regular'])
            else:
                await message.answer("Извини, я ничего не нашлось.")
        except requests.exceptions.RequestException as e:
            await message.answer(f"Ошибка при запросе к Unsplash: {e}")
        except (KeyError, IndexError) as e:
            await message.answer(f"Ошибка обработки данных Unsplash: {e}")
    else:
        await message.answer("API ключ Unsplash не установлен.")

# Оптимизированный Flask-сервер
app = Flask(__name__)

@app.route('/')
def home():
    logging.info("Uptime Robot checked the bot status")
    return f"""
    <html>
        <head><title>Bot Status</title></head>
        <body>
            <h1>Bot Status</h1>
            <p>Bot is running!</p>
            <p>Last update: {datetime.datetime.now()}</p>
        </body>
    </html>
    """

def run_flask():
    app.run(host="0.0.0.0", port=8080, threaded=True)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# Запуск бота
async def main():
    while True:
        try:
            # Register all message handlers
            dp.message.register(start_handler, F.text.casefold() == "/start")
            dp.message.register(request_rest, F.text == "Рест")
            dp.message.register(rest_reason, Form.reason)
            dp.message.register(rest_duration, Form.duration)
            dp.message.register(complaint, F.text == "Жалоба")
            dp.message.register(handle_complaint, Form.complaint)
            dp.message.register(back_to_menu, F.text == "Назад")
            dp.chat_member.register(user_joins_chat)
            dp.message.register(animal_photo, F.text.startswith("/"))

            logging.info("Бот запущен")
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            logging.info("Перезапуск бота через 5 секунд...")
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            logging.info("Бот остановлен вручную")
            break

if __name__ == "__main__":
    asyncio.run(main())
