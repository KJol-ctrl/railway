import logging
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ChatPermissions, ReplyKeyboardMarkup, KeyboardButton
import random
import requests
import os

# Базовые настройки
TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = [int(id) for id in os.environ['ADMIN_IDS'].split(',')]
GROUP_ID = int(os.environ['GROUP_ID'])
GROUP_LINK = os.environ['GROUP_LINK']
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')

# Оптимизированная настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Инициализация бота с оптимизированными настройками
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Глобальные словари в памяти
user_data = {}
message_counts = {}
MAX_MESSAGES = 5

class Form(StatesGroup):
    role = State()
    age_verify = State()
    reason = State()
    duration = State()
    complaint = State()

def get_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Рест"), KeyboardButton(text="Жалоба")]
    ])

def get_back_button():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Назад")]
    ])

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

@dp.message(F.text == "Назад")
async def back_to_menu(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    await message.answer("Вы вернулись в меню.", reply_markup=get_menu())
    await state.clear()

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
                    f'''📢 Новый участник: <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{role}</b>
{mention_text}'''
                )
                await bot.send_message(user_id, f'''🌟 <b>Добро пожаловать!</b> 
Ваша заявка одобрена. Теперь вы можете взаимодействовать с меню.''', reply_markup=get_menu())
            except Exception as e:
                logging.error(f"Ошибка при назначении роли: {e}")
                for admin_id in ADMIN_IDS:
                    await bot.send_message(admin_id, f"Ошибка при назначении роли пользователю {update.new_chat_member.user.full_name}: {str(e)}")
        elif update.new_chat_member.status in ["left", "kicked"]:
            if user_id in user_data:
                custom_title = user_data[user_id].get("custom_title", "Неизвестно")
                leave_message = f"😢 Пользователь <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a> с ролью <b>{custom_title}</b> покинул группу"
                # Отправляем сообщение в группу
                await bot.send_message(chat_id, leave_message)
                # Отправляем сообщение админам
                admin_message = f'''👋 <b>Участник покинул группу</b>

😢 Пользователь: <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{custom_title}</b>'''
                for admin_id in ADMIN_IDS:
                    await bot.send_message(admin_id, admin_message)
                user_data.pop(user_id, None)

@dp.message(F.text.casefold() == "/start")
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    if not await is_member(user_id) and not await check_message_limit(user_id):
        await message.answer("Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/alren15'>администратору</a>.")
        return
    member = await bot.get_chat_member(GROUP_ID, user_id)
    if member.status in ["member", "administrator", "creator"]:
        await message.answer(" <b>Вы уже являетесь участником группы</b>\n\n🎮 Используйте меню для навигации:", reply_markup=get_menu())
    else:
        remove_keyboard = types.ReplyKeyboardRemove()
        await message.answer(
f''' <b>Что бы вступить:</b>
            
🏠 Ознакомьтесь с <a href='https://telegra.ph/%F0%9D%99%B5%F0%9D%9A%95%F0%9D%9A%98%F0%9D%9A%98%F0%9D%9A%8D-%F0%9D%9A%83%F0%9D%9A%91%F0%9D%9A%8E-%F0%9D%99%BB%F0%9D%9A%98%F0%9D%9A%9D%F0%9D%9A%9E%F0%9D%9A%9C-%F0%9D%9A%9B%F0%9D%9A%9E%F0%9D%9A%95%F0%9D%9A%8E%F0%9D%9A%9C-03-28'>правилами</a>

🎭 Выберите свободную роль из <a href='https://t.me/info_TheLotus/7'>списка</a>

 Напишите роль без точки и с большой буквы. Пример: <b>Зеле</b>''',
            disable_web_page_preview=True,
            reply_markup=remove_keyboard
        )
        await state.set_state(Form.role)

@dp.message(Form.role)
async def role_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return  
    user_id = message.from_user.id
    role = message.text.strip()
    await state.update_data(role=role)
    await message.answer('''
Подтвердите свой возраст одним из способов:

   • 📸 Фотография документа
   • 🎤 Голосовое сообщение
   • 🎥 Видеосообщение
   • ✍️ Текстовое сообщение

️ При возникновении ошибок обращайтесь к <a href='https://t.me/alren15'>администратору</a>''')
    await state.set_state(Form.age_verify)

@dp.message(Form.age_verify, F.text)
async def age_verify_text_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    data = await state.get_data()
    role = data.get('role')
    user_data[user_id] = {"role": role}
    
    await message.answer(
        f'Перейдите по <a href="{GROUP_LINK}">ссылке</a>. Ваша заявка будет рассмотрена в ближайшее время.',
        disable_web_page_preview=True,
        reply_markup=get_menu()
    )
    
    admin_message = (
        f"🔔 <b>Заявка на вступление!</b>\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"📌 Роль: {role}\n"
        f" Подтверждение: {message.text}"
    )
    
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
    await state.clear()

@dp.message(Form.age_verify)
async def age_verify_any_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    data = await state.get_data()
    role = data.get('role')
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
        # Пересылаем любой тип сообщения
        await bot.forward_message(admin_id, message.chat.id, message.message_id)
    await state.clear()

@dp.message(F.text.startswith("/"))
async def photo(message: types.Message):
    user_id = message.from_user.id
    if not await is_member(user_id) and not await check_message_limit(user_id):
        await message.answer("Извините, ничего не нашлось.")
        return
    query = message.text[1:].lower()
    if UNSPLASH_ACCESS_KEY:
        try:
            response = requests.get(f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_ACCESS_KEY}")
            response.raise_for_status()
            data = response.json()
            if data['results']:
                random_photo = random.choice(data['results'])
                await bot.send_photo(message.chat.id, random_photo['urls']['regular'])
            else:
                await message.answer("Извини, ничего не нашлось.")
        except requests.exceptions.RequestException as e:
            await message.answer(f"Ошибка при запросе к Unsplash: {e}")
        except (KeyError, IndexError) as e:
            await message.answer(f"Ошибка обработки данных Unsplash: {e}")
    else:
        await message.answer("API ключ Unsplash не установлен.")


# Оптимизированный запуск
async def main():
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
        dp.message.register(photo, F.text.startswith("/"))

        logging.info("Bot started")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
