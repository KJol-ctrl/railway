import logging
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
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
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_CX_ID = os.environ.get('GOOGLE_CX_ID')
LIST_ADMIN_ID = tuple(int(id) for id in os.environ.get('LIST_ADMIN_ID', '').split(',')) if os.environ.get('LIST_ADMIN_ID') else ()

# Оптимизированная инициализация бота
from aiogram.client.default import DefaultBotProperties
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
        # Проверяем количество участников в группе
        chat_members = await bot.get_chat_member_count(GROUP_ID)
        if chat_members >= 50:
            await message.answer("<b> В группе сейчас максимальное количество участников.</b>\n\n Оставьте заявку и вас примут при освобождении места.")

        await message.answer(
            f''' <b>Что бы вступить:</b>\n\n🏠 Ознакомьтесь с <a href='https://telegra.ph/%F0%9D%99%B5%F0%9D%9A%95%F0%9D%9A%98%F0%9D%9A%98%F0%9D%9A%8D-%F0%9D%9A%83%F0%9D%9A%91%F0%9D%9A%8E-%F0%9D%99%BB%F0%9D%9A%98%F0%9D%9A%9D%F0%9D%9A%9E%F0%9D%9A%9C-%F0%9D%9A%9B%F0%9D%9A%9E%F0%9D%9A%95%F0%9D%9A%8E%F0%9D%9A%9C-03-28'>правилами</a>\n🎭 Выберите свободную роль из <a href='https://t.me/info_TheMeiver/7'>списка</a>\n\n Напишите <b>только роль</b> без точки и с большой буквы. Пример: <b>Зеле</b>''',
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
<b>Подтвердите свой возраст одним из способов:</b>

📸 Фотография документа
🎥 Видеосообщение

️ <b>Не пишите просто свой возраст.</b> При возникновении ошибок обращайтесь к <a href='https://t.me/alren15'>администратору</a>''')
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
        f'Перейдите по <a href="{GROUP_LINK}"><b>ссылке (нажать)</b></a>. Ваша заявка будет рассмотрена в ближайшее время.\n\n Для повторного заполнения - /start',
        disable_web_page_preview=True,
        reply_markup=get_menu()
    )

    username = f" (@{message.from_user.username})" if message.from_user.username else ""
    admin_message = (
        f"<b>Заявка на вступление!</b>\n\n"
        f"#️⃣ ID: <code>{user_id}</code>\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>\n"
        f"📌 Роль: <b>{role}</b>\n"
        f"Подтверждение: {message.text}\n\n"
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
        f'Перейдите по <a href="{GROUP_LINK}"><b>ссылке (нажать)</b></a>. Ваша заявка будет рассмотрена в ближайшее время.\n\n Для повторного заполнения - /start',
        disable_web_page_preview=True,
        reply_markup=get_menu()
    )

    username = f" (@{message.from_user.username})" if message.from_user.username else ""
    admin_message = (
        f"<b>Заявка на вступление!</b>\n\n"

        f"👤 От: <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>\n"
        f"📌 Роль: <b>{role}</b>"
    )

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
        # Пересылаем любой тип сообщения
        await bot.forward_message(admin_id, message.chat.id, message.message_id)
    await state.clear()

@dp.message(lambda message: message.text and message.text.lower().startswith("найди "))
async def photo(message: types.Message):
    user_id = message.from_user.id
    if not await is_member(user_id) and not check_message_limit(user_id):
        await message.answer("Извините, ничего не нашлось.")
        return

    query = message.text[6:].lower()
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
    GOOGLE_CX_ID = os.environ.get('GOOGLE_CX_ID')

    if GOOGLE_API_KEY and GOOGLE_CX_ID:
        try:
            search_url = f"https://www.googleapis.com/customsearch/v1"
            params = {
                'key': GOOGLE_API_KEY,
                'cx': GOOGLE_CX_ID,
                'q': query,
                'searchType': 'image',
                'num': 10,  # Количество изображений в результате
                'safe': 'active'  # Включаем безопасный поиск
            }
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get('items'):
                # Храним уже отправленные изображения
                if user_id not in message_counts:
                    message_counts[user_id] = []

                for item in data['items']:
                    image_url = item.get('link')
                    # Проверяем, было ли это изображение отправлено раньше
                    if image_url not in message_counts[user_id]:
                        await bot.send_photo(message.chat.id, image_url)
                        message_counts[user_id].append(image_url)  # Добавляем изображение в список отправленных
                        return

                await message.answer("Извини, по запросу ничего не нашлось.")
            else:
                await message.answer("Извини, по запросу ничего не нашлось.")
        except requests.exceptions.RequestException as e:
            await message.answer(f"Ошибка при запросе к Google API: {e}")

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

    user_id = message.from_user.id
    data = await state.get_data()
    role = await bot.get_chat_member(GROUP_ID, user_id)
    username = f" (@{message.from_user.username})" if message.from_user.username else ""

    admin_message = f'''<b>Заявка на рест</b>

От: <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>
📌 Роль: {role.custom_title if role.custom_title else 'Неизвестно'}
⚙️ Причина: {data['reason']}
⌛️ Срок: {message.text}'''

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)

    await message.answer("Заявка на рест отправлена. Ожидайте ответа от администраторов.", reply_markup=get_menu())
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

    user_id = message.from_user.id
    username = f" (@{message.from_user.username})" if message.from_user.username else ""

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f'''🔔 <b>Новая жалоба от</b> <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>:
{message.text}''')

    await message.answer("Жалоба отправлена администраторам. Ожидайте ответ.", reply_markup=get_menu())
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
    if (old_status == "member" and new_status == "left") or (old_status == "administrator" and new_status == "left"):
        if user_id in user_data:
            custom_title = user_data[user_id].get("custom_title", "Неизвестно")
            username = f" (@{update.new_chat_member.user.username})" if update.new_chat_member.user.username else ""
            leave_message = f"😢 Пользователь <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a> с ролью <b>{custom_title}</b> покинул группу"
            await bot.send_message(chat_id, leave_message)

            admin_message = f'''<b>Участник покинул группу</b>\n
😢 Пользователь: <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a>\n🎭 Роль: <b>{custom_title}</b>'''
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, admin_message)

            # Send notification to LIST_ADMIN_ID
            for admin_id in LIST_ADMIN_ID:
                await bot.send_message(admin_id, f"Освободилась роль: {custom_title}")

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
                    await bot.send_message(admin_id, f"Бот не имеет необходимых прав администратора в группе {chat_id}")
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

            # Отправляем сначала приветственное сообщение
            await bot.send_message(
                chat_id,
                f'''📢 Новый участник: <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{role}</b>'''
            )

            # Отправляем все чанки с эмодзи с задержкой
            for chunk in tag_chunks:
                chunk_text = " ".join(chunk)
                await bot.send_message(chat_id, chunk_text)
                await asyncio.sleep(1)  # Добавляем задержку между всеми сообщениями с тегами
            await bot.send_message(user_id, f'''🌟 <b>Добро пожаловать!</b>

Ваша заявка одобрена. Теперь вы можете взаимодействовать с меню.''', reply_markup=get_menu())

            # Send notification to LIST_ADMIN_ID
            for admin_id in LIST_ADMIN_ID:
                await bot.send_message(admin_id, f"Занята роль: {role}")
        except Exception as e:
            logging.error(f"Ошибка при назначении роли: {e}")
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"Ошибка при назначении роли пользователю {update.new_chat_member.user.full_name}: {str(e)}")
    elif update.new_chat_member.status in {"left", "kicked"}:
        if user_id in user_data:
            custom_title = user_data[user_id].get("custom_title", "Неизвестно")
            username = f" (@{update.new_chat_member.user.username})" if update.new_chat_member.user.username else ""
            leave_message = f"😢 Пользователь <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a> с ролью <b>{custom_title}</b> покинул группу"
            # Отправляем сообщение в группу
            await bot.send_message(chat_id, leave_message)
            # Отправляем сообщение админам
            admin_message = f'''<b>Участник покинул группу</b>\n
😢 Пользователь: <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a>
🎭 Роль: <b>{custom_title}</b>'''
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, admin_message)

            # Отправляем уведомление о свободной роли в LIST_ADMIN_ID
            for admin_id in LIST_ADMIN_ID:
                await bot.send_message(admin_id, f"Освободилась роль: {custom_title}")

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

# Обработчик ответов админов на заявки пользователей
@dp.message(lambda m: m.text and m.text.lower().startswith("счёт ") and m.reply_to_message)
async def count_symbols(message: types.Message):
    # Получаем символ для подсчета (берем первый символ после команды)
    symbol = message.text[5:].strip()
    if not symbol:
        await message.reply("Укажите символ для подсчета после команды.")
        return
        
    # Получаем текст из сообщения, на которое ответили
    target_text = message.reply_to_message.text or message.reply_to_message.caption
    if not target_text:
        await message.reply("В сообщении нет текста для подсчета символов.")
        return
        
    # Считаем количество символов
    count = target_text.count(symbol)
    await message.reply(f'Количество указанного символа: {count}')

@dp.message(lambda m: m.chat.type == ChatType.PRIVATE and 
           m.from_user.id in ADMIN_IDS and 
           m.text and m.text.lower().startswith("сказать "))
async def admin_say_command(message: types.Message):
    try:
        # Получаем текст после команды "сказать"
        text_to_say = message.text[7:].strip()
        if not text_to_say:
            await message.reply("Укажите текст сообщения после команды.")
            return
            
        # Отправляем сообщение в группу
        await bot.send_message(GROUP_ID, text_to_say)
        await message.reply("Сообщение отправлено в группу.")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения в группу: {e}")
        await message.reply("Произошла ошибка при отправке сообщения.")

@dp.message()
async def handle_admin_response(message: types.Message):
    try:
        # Проверяем, что это ответ админа на заявку
        if not (message.chat.type == ChatType.PRIVATE and 
                message.from_user.id in ADMIN_IDS and 
                message.reply_to_message):
            return

        reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""

        if "Заявка на вступление!" not in reply_text:
            return

        # Парсим ID пользователя из заявки на вступление
        user_id = None
        for line in reply_text.split('\n'):
            if line.startswith("#️⃣ ID:"):
                user_id_str = line.split(":")[1].strip().replace("<code>", "").replace("</code>", "")
                if user_id_str.isdigit():
                    user_id = int(user_id_str)
                break

        # Альтернативный парсинг если ID не найден
        if not user_id and "tg://user?id=" in reply_text:
            user_id = int(reply_text.split("tg://user?id=")[1].split("'")[0])

        if not user_id:
            await message.reply("Не удалось определить ID пользователя.")
            return

        # Получаем информацию об админе и пользователе
        try:
            admin = message.from_user
            target_user = await bot.get_chat(user_id)

            # Отправляем ответ пользователю
            await bot.send_message(
                user_id,
                f"<b>Ответ администратора:</b>\n\n{message.text}",
                parse_mode=ParseMode.HTML
            )

            # Формируем текст уведомления для других админов
            admin_name = f"<b>{admin.full_name}</b>"
            if admin.username:
                admin_name += f" (@{admin.username})"

            user_name = f"<b>{target_user.full_name}</b>"
            if target_user.username:
                user_name += f" (@{target_user.username})"

            notification_text = (
                f"{admin_name} отправил ответ пользователю {user_name}:\n"
                f"<code>{message.text}</code>"
            )

            # Отправляем уведомление другим админам
            for admin_id in ADMIN_IDS:
                if admin_id != message.from_user.id:
                    try:
                        await bot.send_message(
                            admin_id,
                            notification_text,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logging.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")

            await message.reply(f"Ответ успешно отправлен пользователю.")

        except Exception as e:
            error_msg = f"Не удалось отправить ответ: {str(e)}"
            if "user is deactivated" in str(e) or "bot was blocked by the user" in str(e):
                error_msg = "Пользователь заблокировал бота или удалил аккаунт"
            await message.reply(error_msg)

    except Exception as e:
        logging.error(f"Ошибка в обработчике ответов админа: {str(e)}", exc_info=True)
        await message.reply("Произошла системная ошибка. Проверьте логи.")

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
