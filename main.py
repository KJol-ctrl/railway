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
from functools import lru_cache

# Базовые настройки с оптимизированным логированием
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Константы для оптимизации
TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = tuple(int(id) for id in os.environ['ADMIN_IDS'].split(','))
GROUP_ID = int(os.environ['GROUP_ID'])
GROUP_LINK = os.environ['GROUP_LINK']
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')

# Оптимизированная инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Оптимизированное хранение данных
user_data = {}
message_counts = {}
MAX_MESSAGES = 5

# Кэширование клавиатур
@lru_cache(maxsize=2)
def get_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Рест"), KeyboardButton(text="Жалоба")]
    ])

@lru_cache(maxsize=1)
def get_back_button():
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="Назад")]
    ])

class Form(StatesGroup):
    role = State()
    age_verify = State()
    reason = State()
    duration = State()
    complaint = State()

# Оптимизированная проверка членства
async def is_member(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(GROUP_ID, user_id)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False

# Оптимизированная проверка лимита сообщений
def check_message_limit(user_id: int) -> bool:
    count = message_counts.get(user_id, 0) + 1
    message_counts[user_id] = count
    return count <= MAX_MESSAGES

# Handlers
@dp.message(F.text.casefold() == "/start")
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    if not await is_member(user_id) and not check_message_limit(user_id):
        await message.answer("Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/alren15'>администратору</a>.")
        return

    member = await bot.get_chat_member(GROUP_ID, user_id)
    if member.status in {"member", "administrator", "creator"}:
        await message.answer(" <b>Вы уже являетесь участником группы</b>\n\n🎮 Используйте меню для навигации:", reply_markup=get_menu())
    else:
        await message.answer(
            f''' <b>Что бы вступить:</b>\n\n🏠 Ознакомьтесь с <a href='https://telegra.ph/%F0%9D%99%B5%F0%9D%9A%95%F0%9D%9A%98%F0%9D%9A%98%F0%9D%9A%8D-%F0%9D%9A%83%F0%9D%9A%91%F0%9D%9A%8E-%F0%9D%99%BB%F0%9D%9A%98%F0%9D%9A%9D%F0%9D%9A%9E%F0%9D%9A%9C-%F0%9D%9A%9B%F0%9D%9A%9E%F0%9D%9A%95%F0%9D%9A%8E%F0%9D%9A%9C-03-28'>правилами</a>\n🎭 Выберите свободную роль из <a href='https://t.me/info_TheLotus/7'>списка</a>\n\n Напишите роль без точки и с большой буквы. Пример: <b>Зеле</b>''',
            disable_web_page_preview=True,
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(Form.role)

@dp.message(Form.role)
async def role_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    await state.update_data(role=message.text.strip())
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
        f"🔔 <b>Заявка на вступление!</b>\n\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"📌 Роль: <b>{role}</b>\n"
        f"✍️ Подтверждение: {message.text}"
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
        f"🔔 <b>Заявка на вступление!</b>\n\n"
        f"👤 От: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"📌 Роль: <b>{role}</b>"
    )

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
        # Пересылаем любой тип сообщения
        await bot.forward_message(admin_id, message.chat.id, message.message_id)
    await state.clear()

@dp.message(F.text.startswith("?"))
async def photo(message: types.Message):
    user_id = message.from_user.id
    if not await is_member(user_id) and not check_message_limit(user_id):
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


@dp.message(F.text.lower().startswith("эмодзи"))
async def set_custom_emoji(message: types.Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    user_id = message.from_user.id
    emoji = message.text.split(maxsplit=1)[1].strip() if len(message.text.split()) > 1 else None
    
    if not emoji:
        await message.reply("Пожалуйста, укажите эмодзи после команды.")
        return
        
    if 'user_emojis' not in user_data:
        user_data['user_emojis'] = {}
    
    user_data['user_emojis'][user_id] = emoji
    await message.reply(f"Ваш персональный эмодзи установлен на {emoji}")

@dp.message(F.text.casefold().startswith("засосать"))
async def kiss_handler(message: types.Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    if not message.reply_to_message:
        return

    sender = message.from_user
    target = message.reply_to_message.from_user

    if target.is_bot:
        return

    kiss_message = f"💋 | <a href='tg://user?id={sender.id}'>{sender.full_name}</a> жёстко засосал <a href='tg://user?id={target.id}'>{target.full_name}</a>"
    await message.answer(kiss_message)

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
async def chat_member_handler(update: types.ChatMemberUpdated):
    chat_id = update.chat.id
    if chat_id != GROUP_ID:
        return

    old_status = update.old_chat_member.status if update.old_chat_member else None
    new_status = update.new_chat_member.status if update.new_chat_member else None
    user_id = update.new_chat_member.user.id

    logging.info(f"Обновление участника: {old_status} -> {new_status} для пользователя {user_id}")

    # Проверяем выход участника
    if old_status == "member" and new_status == "left":
        if user_id in user_data:
            custom_title = user_data[user_id].get("custom_title", "Неизвестно")
            leave_message = f"😢 Пользователь <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}</a> с ролью <b>{custom_title}</b> покинул группу"
            await bot.send_message(chat_id, leave_message)

            admin_message = f'''👋 <b>Участник покинул группу</b>\n\n😢 Пользователь: <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}</a>\n🎭 Роль: <b>{custom_title}</b>'''
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, admin_message)

            if 'user_emojis' in user_data and user_id in user_data['user_emojis']:
                del user_data['user_emojis'][user_id]
            user_data.pop(user_id, None)
            return

    # Обработка вступления в группу
    if new_status == "member" and user_id in user_data and not update.new_chat_member.user.is_bot:
        try:
            # Проверяем права бота
            bot_member = await bot.get_chat_member(chat_id, (await bot.me()).id)
            if not bot_member.can_promote_members:
                logging.error(f"Бот не имеет прав администратора в группе {chat_id}")
                for admin_id in ADMIN_IDS:
                    await bot.send_message(admin_id, f"⚠️ Бот не имеет необходимых прав администратора в группе {chat_id}")
                return

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
            members.extend([await bot.get_chat_member(chat_id, member_id) for member_id in [m.user.id for m in members]])
            tags = []
            emojis = ["⭐️", "🌟", "💫", "⚡️", "🔥", "❤️", "💞", "💕", "❣️", "💌", "🌈", "✨", "🎯", "🎪", "🎨", "🎭", "🎪", "🎢", "🎡", "🎠", "🎪", "🌸", "🌺", "🌷", "🌹", "🌻", "🌼", "💐", "🌾", "🌿", "☘️", "🍀", "🍁", "🍂", "🍃", "🌵", "🌴", "🌳", "🌲", "🎄", "🌊", "🌈", "☀️", "🌤", "⛅️", "☁️", "🌦", "🌨", "❄️", "☃️",  "🌬", "💨", "🌪", "🌫", "🌈", "☔️", "⚡️", "❄️", "🔮", "🎮", "🎲", "🎯", "🎳", "🎪", "🎭", "🎨", "🎬", "🎤", "🎧", "🎼", "🎹", "🥁", "🎷", "🎺", "🎸", "🪕", "🎻", "🎲", "♟", "🎯", "🎳", "🎮", "🎰", "🧩", "🎪", "🎭", "🎨", "🖼", "🎨", "🧵", "🧶", "👑", "💎", "⚜️"]

            # Создаем или получаем словарь для хранения эмодзи пользователей
            if 'user_emojis' not in user_data:
                user_data['user_emojis'] = {}

            # Назначаем эмодзи новому участнику
            if user_id not in user_data['user_emojis']:
                available_emojis = [e for e in emojis if e not in user_data['user_emojis'].values()]
                if available_emojis:
                    user_data['user_emojis'][user_id] = random.choice(available_emojis)

            for member in members:
                if not member.user.is_bot:
                    member_id = member.user.id
                    if member_id not in user_data['user_emojis']:
                        available_emojis = [e for e in emojis if e not in user_data['user_emojis'].values()]
                        if available_emojis:
                            user_data['user_emojis'][member_id] = random.choice(available_emojis)

                    emoji = user_data['user_emojis'].get(member_id, "👤")
                    tag = f"<a href='tg://user?id={member_id}'>{emoji}</a>"
                    tags.append(tag)
            # Разбиваем теги на группы по 10
            tag_chunks = [tags[i:i + 10] for i in range(0, len(tags), 10)]
            
            # Отправляем первое сообщение с информацией о новом участнике
            first_chunk = " ".join(tag_chunks[0]) if tag_chunks else ""
            await bot.send_message(
                chat_id,
                f'''📢 Новый участник: <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{role}</b>
{first_chunk}'''
            )
            
            # Отправляем остальные чанки эмодзи
            for chunk in tag_chunks[1:]:
                chunk_text = " ".join(chunk)
                await bot.send_message(chat_id, chunk_text)
            await bot.send_message(user_id, f'''🌟 <b>Добро пожаловать!</b> 
Ваша заявка одобрена. Теперь вы можете взаимодействовать с меню.''', reply_markup=get_menu())
        except Exception as e:
            logging.error(f"Ошибка при назначении роли: {e}")
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"Ошибка при назначении роли пользователю {update.new_chat_member.user.full_name}: {str(e)}")
    elif update.new_chat_member.status in {"left", "kicked"}:
        if user_id in user_data:
            custom_title = user_data[user_id].get("custom_title", "Неизвестно")
            notify_user_id = os.environ.get('NOTIFY_USER_ID')
            mention_text = f"<a href='tg://user?id={notify_user_id}'>👤</a>" if notify_user_id else ""
            leave_message = f"😢 Пользователь <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}</a> с ролью <b>{custom_title}</b> покинул группу\n{mention_text}"
            # Отправляем сообщение в группу
            await bot.send_message(chat_id, leave_message)
            # Отправляем сообщение админам
            admin_message = f'''👋 <b>Участник покинул группу</b>
😢 Пользователь: <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{custom_title}</b>'''
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, admin_message)
            # Удаляем эмодзи пользователя если он есть
            if 'user_emojis' in user_data and user_id in user_data['user_emojis']:
                del user_data['user_emojis'][user_id]
            user_data.pop(user_id, None)

# Оптимизированный запуск
async def save_existing_members_titles():
    try:
        chat = await bot.get_chat(GROUP_ID)
        members = await bot.get_chat_administrators(GROUP_ID)
        for member in members:
            if member.custom_title and member.user.id not in user_data:
                user_data[member.user.id] = {
                    "role": member.custom_title,
                    "custom_title": member.custom_title
                }
    except Exception as e:
        logging.error(f"Ошибка при сохранении титулов: {e}")

async def main():
    try:
        # Оптимизированная инициализация
        await save_existing_members_titles()
        logging.info("Bot started")
        await dp.start_polling(bot, allowed_updates=["message", "chat_member"])
    except Exception as e:
        logging.error(f"Error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
