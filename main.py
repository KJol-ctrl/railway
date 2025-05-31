
import logging
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ChatPermissions, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import random
import requests
import os
from functools import lru_cache
import json

# Импортируем базу данных
from db import db

# Базовые настройки с оптимизированным логированием
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%H:%M:%S')

# Константы для оптимизации
TOKEN = os.environ['BOT_TOKEN']
ADMIN_IDS = tuple(int(id) for id in os.environ['ADMIN_IDS'].split(','))
GROUP_ID = int(os.environ['GROUP_ID'])
GROUP_LINK = os.environ['GROUP_LINK']
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GOOGLE_CX_ID = os.environ.get('GOOGLE_CX_ID')
LIST_ADMIN_ID = tuple(
    int(id) for id in os.environ.get('LIST_ADMIN_ID', '').split(
        ',')) if os.environ.get('LIST_ADMIN_ID') else ()

# Оптимизированная инициализация бота
from aiogram.client.default import DefaultBotProperties

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Временное хранение для сообщений (антиспам)
message_counts = {}
MAX_MESSAGES = 5

# Система викторин - теперь загружается из БД
quiz_data = {}
quiz_participants = {}


# Кэширование клавиатур
@lru_cache(maxsize=2)
def get_menu():
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[[KeyboardButton(text="Рест"),
                   KeyboardButton(text="Жалоба")],
                  [KeyboardButton(text="Не могу влиться")]])


@lru_cache(maxsize=1)
def get_cant_join_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True,
                               keyboard=[[
                                   KeyboardButton(text="Назад"),
                                   KeyboardButton(text="Не могу выбрать")
                               ]])


@lru_cache(maxsize=1)
def get_back_button():
    return ReplyKeyboardMarkup(resize_keyboard=True,
                               keyboard=[[KeyboardButton(text="Назад")]])


class Form(StatesGroup):
    role = State()
    age_verify = State()
    reason = State()
    duration = State()
    complaint = State()

class QuizCreation(StatesGroup):
    waiting_for_question = State()
    waiting_for_answers = State()
    waiting_for_correct = State()


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


# Функция для назначения эмодзи с автоматическим сохранением
async def assign_emoji_to_user(user_id: int) -> str:
    """Назначает эмодзи пользователю и сохраняет в БД"""
    emojis = [
        "⭐️", "🌟", "💫", "⚡️", "🔥", "❤️", "💞", "💕", "❣️", "💌", "🌈", "✨",
        "🎯", "🎪", "🎨", "🎭", "🎪", "🎢", "🎡", "🎠", "🎪", "🌸", "🌺", "🌷",
        "🌹", "🌻", "🌼", "💐", "🌾", "🌿", "☘️", "🍀", "🍁", "🍂", "🍃", "🌵",
        "🌴", "🌳", "🌲", "🎄", "🌊", "🌈", "☀️", "🌤", "⛅️", "☁️", "🌦", "🌨",
        "❄️", "☃️", "🌬", "💨", "🌪", "🌫", "🌈", "☔️", "⚡️", "❄️", "🔮",
        "🎮", "🎲", "🎯", "🎳", "🎪", "🎭", "🎨", "🎬", "🎤", "🎧", "🎼", "🎹",
        "🥁", "🎷", "🎺", "🎸", "🪕", "🎻", "🎲", "♟", "🎯", "🎳", "🎮", "🎰",
        "🧩", "🎪", "🎭", "🎨", "🖼", "🎨", "🧵", "🧶", "👑", "💎", "⚜️"
    ]
    
    # Проверяем, есть ли уже эмодзи у пользователя
    existing_emoji = await db.get_emoji(user_id)
    if existing_emoji:
        return existing_emoji
    
    # Получаем уже используемые эмодзи
    used_emojis = await db.get_used_emojis()
    available_emojis = [e for e in emojis if e not in used_emojis]
    
    if available_emojis:
        selected_emoji = random.choice(available_emojis)
        await db.save_emoji(user_id, selected_emoji)
        return selected_emoji
    
    # Если все эмодзи заняты, возвращаем дефолтный
    return "👤"


# Обработчик callback для викторин
@dp.callback_query(lambda c: c.data and c.data.startswith("quiz_"))
async def quiz_callback_handler(callback: CallbackQuery):
    try:
        _, quiz_id_str, answer_index_str = callback.data.split("_")
        quiz_id = int(quiz_id_str)
        answer_index = int(answer_index_str)
        user_id = callback.from_user.id
        
        # Проверяем, что викторина существует и активна в БД
        quiz = await db.get_quiz(quiz_id)
        if not quiz or not quiz['active']:
            await callback.answer("Эта викторина уже завершена.", show_alert=True)
            return
        
        # Проверяем, что пользователь участник группы
        if not await is_member(user_id):
            await callback.answer("Только участники группы могут участвовать в викторине.", show_alert=True)
            return
        
        # Сохраняем ответ пользователя в БД
        await db.save_quiz_answer(quiz_id, user_id, answer_index)
        
        # Получаем выбранный ответ
        selected_answer = quiz['answers'][answer_index]
        
        await callback.answer(f"Ваш ответ: {selected_answer}", show_alert=False)
        
        logging.info(f"Пользователь {user_id} ответил на викторину {quiz_id}: вариант {answer_index}")
        
    except (ValueError, IndexError) as e:
        logging.error(f"Ошибка обработки callback викторины: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)
    except Exception as e:
        logging.error(f"Неожиданная ошибка в callback викторины: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)


# Handlers
@dp.message(F.text.casefold() == "/start")
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    if not await is_member(user_id) and not check_message_limit(user_id):
        await message.answer(
            "Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/alren15'>администратору</a>."
        )
        return

    member = await bot.get_chat_member(GROUP_ID, user_id)
    if member.status in {"member", "administrator", "creator"}:
        await message.answer(
            " <b>Вы уже являетесь участником группы</b>\n\n🎮 Используйте меню для навигации:",
            reply_markup=get_menu())
    else:
        # Проверяем количество участников в группе
        chat_members = await bot.get_chat_member_count(GROUP_ID)
        if chat_members >= 50:
            await message.answer(
                "<b> В группе сейчас максимальное количество участников.</b>\n\n Оставьте заявку и вас примут при освобождении места."
            )

        await message.answer(
            f''' <b>Что бы вступить:</b>\n\n🏠 Ознакомьтесь с <a href='https://telegra.ph/%F0%9D%99%B5%F0%9D%9A%95%F0%9D%9A%98%F0%9D%9A%98%F0%9D%9A%8D-%F0%9D%9A%83%F0%9D%9A%91%F0%9D%9A%8E-%F0%9D%99%BB%F0%9D%9A%98%F0%9D%9A%9D%F0%9D%9A%9E%F0%9D%9A%9C-%F0%9D%9A%9B%F0%9D%9A%9E%F0%9D%9A%95%F0%9D%9A%8E%F0%9D%9A%9C-03-28'>правилами</a>\n🎭 Выберите свободную роль из <a href='https://t.me/info_TheMeiver/7'>списка</a>\n\n Напишите <b>только роль</b> без точки и с большой буквы. Пример: <b>Зеле</b>''',
            disable_web_page_preview=True,
            reply_markup=types.ReplyKeyboardRemove())
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

️ <b>Не пишите просто свой возраст.</b> При возникновении ошибок обращайтесь к <a href='https://t.me/alren15'>администратору</a>'''
                         )
    await state.set_state(Form.age_verify)


@dp.message(Form.age_verify, F.text)
async def age_verify_text_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    data = await state.get_data()
    role = data.get('role')
    
    # Сохраняем данные пользователя в БД
    await db.save_user_data(user_id, role=role)

    await message.answer(
        f' Перейдите по <a href="{GROUP_LINK}"><b>ссылке (нажать)</b></a>. Ваша заявка будет рассмотрена в ближайшее время.\n\n Для повторного заполнения - /start',
        disable_web_page_preview=True,
        reply_markup=get_menu())

    username = f" (@{message.from_user.username})" if message.from_user.username else ""
    admin_message = (
        f"<b>Заявка на вступление!</b>\n\n"
        f"#️⃣ ID: <code>{user_id}</code>\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>\n"
        f"📌 Роль: <b>{role}</b>\n"
        f"Подтверждение: {message.text}\n\n")

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
    
    # Сохраняем данные пользователя в БД
    await db.save_user_data(user_id, role=role)

    await message.answer(
        f' Перейдите по <a href="{GROUP_LINK}"><b>ссылке (нажать)</b></a>. Ваша заявка будет рассмотрена в ближайшее время. <b>Не удаляйте чат.</b>\n\n Для повторного заполнения - /start',
        disable_web_page_preview=True,
        reply_markup=get_menu())

    username = f" (@{message.from_user.username})" if message.from_user.username else ""
    admin_message = (
        f"<b>Заявка на вступление!</b>\n\n"
        f"#️⃣ ID: <code>{user_id}</code>\n"
        f"👤 От: <a href='tg://user?id={user_id}'>{message.from_user.full_name}{username}</a>\n"
        f"📌 Роль: <b>{role}</b>")

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)
        # Пересылаем любой тип сообщения
        await bot.forward_message(admin_id, message.chat.id,
                                  message.message_id)
    await state.clear()


@dp.message(
    lambda message: message.text and message.text.lower().startswith("найди "))
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
            import aiohttp
            
            search_url = f"https://www.googleapis.com/customsearch/v1"
            params = {
                'key': GOOGLE_API_KEY,
                'cx': GOOGLE_CX_ID,
                'q': query,
                'searchType': 'image',
                'num': 5,  # Уменьшаем количество для быстроты
                'safe': 'active',
                'imgType': 'photo',
                'fileType': 'jpg,png,gif'
            }
            
            # Асинхронный запрос с коротким таймаутом
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(search_url, params=params) as response:
                    if response.status != 200:
                        await message.answer("Извини, по запросу ничего не нашлось.")
                        return
                    
                    data = await response.json()

            if data.get('items'):
                # Проверяем только первые 3 изображения для скорости
                for item in data['items'][:5]:
                    image_url = item.get('link')
                    if image_url:
                        try:
                            # Быстрая проверка изображения с коротким таймаутом
                            timeout = aiohttp.ClientTimeout(total=2)
                            async with aiohttp.ClientSession(timeout=timeout) as session:
                                async with session.head(image_url) as img_response:
                                    content_type = img_response.headers.get('content-type', '')
                                    
                                    if img_response.status == 200 and content_type.startswith('image/'):
                                        await bot.send_photo(message.chat.id, image_url)
                                        return
                        except Exception as e:
                            # Быстро пропускаем проблемные изображения
                            logging.debug(f"Пропускаем изображение {image_url}: {e}")
                            continue

                await message.answer("Извини, по запросу ничего не нашлось.")
            else:
                await message.answer("Извини, по запросу ничего не нашлось.")
                
        except asyncio.TimeoutError:
            await message.answer("Поиск занял слишком много времени, попробуйте еще раз.")
        except Exception as e:
            logging.error(f"Ошибка в функции поиска: {e}")
            await message.answer("Извини, произошла ошибка при поиске.")


@dp.message(F.text.lower().startswith("эмодзи"))
async def set_custom_emoji(message: types.Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    user_id = message.from_user.id
    emoji = message.text.split(
        maxsplit=1)[1].strip() if len(message.text.split()) > 1 else None

    if not emoji:
        await message.reply("Пожалуйста, укажите эмодзи после команды.")
        return

    # Сохраняем эмодзи в БД
    await db.save_emoji(user_id, emoji)
    await message.reply(f"Ваш персональный эмодзи установлен на {emoji}")


@dp.message(lambda message: message.text and message.text.lower() in
            {"ауф", "бот", "ауф бот"})
async def handle_keywords(message: types.Message):
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.reply("Все мои волки делают ауф ☝️🐺")


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
        await message.answer("Вы не являетесь участником.",
                             reply_markup=get_menu())
        return
    await message.answer("Пожалуйста, напишите причину реста:",
                         reply_markup=get_back_button())
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
        await message.answer("Пожалуйста, напишите причину реста заново:",
                             reply_markup=get_back_button())
        return

    user_id = message.from_user.id
    data = await state.get_data()
    role = await bot.get_chat_member(GROUP_ID, user_id)
    username = f" (@{message.from_user.username})" if message.from_user.username else ""

    admin_message = f'''<b>Заявка на рест</b>

#️⃣ ID: <code>{user_id}</code>
📌 Роль: <b>{role.custom_title if role.custom_title else 'неизвестно'}</b>
⌛️ Срок: {message.text}
Причина: {data['reason']}'''

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)

    await message.answer(
        "Заявка на рест отправлена. Ожидайте ответа от администраторов.",
        reply_markup=get_menu())
    await state.clear()


@dp.message(F.text == "Жалоба")
async def complaint(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    if not await is_member(user_id):
        await message.answer("Вы не являетесь участником.",
                             reply_markup=get_menu())
        return
    await message.answer("Опишите вашу жалобу:",
                         reply_markup=get_back_button())
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
        await bot.send_message(admin_id, f'''🔔 <b>Новая жалоба:</b>

{message.text}''')

    await message.answer("Жалоба отправлена администраторам. Ожидайте ответ.",
                         reply_markup=get_menu())
    await state.clear()


class CantJoinState(StatesGroup):
    waiting_for_admin = State()
    waiting_for_info = State()


@dp.message(F.text == "Не могу влиться")
async def cant_join_handler(message: types.Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    user_id = message.from_user.id
    if not await is_member(user_id):
        await message.answer("Вы не являетесь участником.",
                             reply_markup=get_menu())
        return
    await message.answer(
        "<b> Если вы не можете начать общение или найти собеседника, то вам поможет администрация.</b>\n\n Выберите из <a href=\"https://telegra.ph/Ankety-Administracii-Flood-The-Meiver-05-14\"><b>списка</b></a> анкету админа который поможет вам.",
        reply_markup=get_cant_join_keyboard())
    await state.set_state(CantJoinState.waiting_for_admin)


@dp.message(CantJoinState.waiting_for_admin)
async def handle_admin_choice(message: types.Message, state: FSMContext):
    if message.text == "Назад":
        await back_to_menu(message, state)
        return
    elif message.text == "Не могу выбрать":
        await message.answer(
            "<b> Пожалуйста, напишите о себе.</b>\n\n Например: интересы, увлечения, фандомы, характер или отправьте любое сообщение."
        )
        await state.set_state(CantJoinState.waiting_for_info)
    else:
        await state.update_data(admin_choice=message.text)
        await message.answer(
            "<b> Пожалуйста, напишите о себе.</b>\n\n Например: интересы, увлечения, фандомы, характер или отправьте любое сообщение."
        )
        await state.set_state(CantJoinState.waiting_for_info)


@dp.message(CantJoinState.waiting_for_info)
async def handle_user_info(message: types.Message, state: FSMContext):
    if message.text == "Назад":
        await back_to_menu(message, state)
        return

    data = await state.get_data()
    admin_choice = data.get('admin_choice', 'не выбран')

    user_id = message.from_user.id
    username = f" (@{message.from_user.username})" if message.from_user.username else ""

    # Получаем роль пользователя из БД
    user_data_db = await db.get_user_data(user_id)
    user_role = user_data_db.get("custom_title", "неизвестно")

    admin_message = f'''<b>Не может влиться!</b>\n
#️⃣ ID: <code>{user_id}</code>
📌 Роль: <b>{user_role}</b>{username}
⭐️ Фаворит: <b>{admin_choice}</b>
О себе: {message.text}'''

    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_message)

    await message.answer("Ваша заявка отправлена.", reply_markup=get_menu())
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

    logging.info(
        f"Обновление участника: {old_status} -> {new_status} для пользователя {user_id}"
    )

    # Проверяем выход участника
    if (old_status == "member"
            and new_status == "left") or (old_status == "administrator"
                                          and new_status == "left"):
        # Получаем данные из БД
        user_data_db = await db.get_user_data(user_id)
        custom_title = user_data_db.get("custom_title", "Неизвестно")
        
        if custom_title != "Неизвестно":
            username = f" (@{update.new_chat_member.user.username})" if update.new_chat_member.user.username else ""
            leave_message = f"😢 Пользователь <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a> с ролью <b>{custom_title}</b> покинул группу"
            await bot.send_message(chat_id, leave_message)

            admin_message = f'''<b>Участник покинул группу</b>\n
😢 Пользователь: <a href='tg://user?id={user_id}'>{update.new_chat_member.user.full_name}{username}</a>\n🎭 Роль: <b>{custom_title}</b>'''
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, admin_message)

            # Send notification to LIST_ADMIN_ID
            for admin_id in LIST_ADMIN_ID:
                await bot.send_message(
                    admin_id, f"Освободилась роль: <b>{custom_title}</b>")

            # Удаляем данные пользователя из БД
            await db.remove_emoji(user_id)
            await db.remove_user_data(user_id)
            return

    # Обработка вступления в группу
    if new_status == "member" and not update.new_chat_member.user.is_bot:
        try:
            # Получаем данные пользователя из БД
            user_data_db = await db.get_user_data(user_id)
            role = user_data_db.get("role")
            
            if not role:
                return

            # Проверяем права бота
            bot_member = await bot.get_chat_member(chat_id, (await
                                                             bot.me()).id)
            if not bot_member.can_promote_members:
                logging.error(
                    f"Бот не имеет прав администратора в группе {chat_id}")
                for admin_id in ADMIN_IDS:
                    await bot.send_message(
                        admin_id,
                        f"Бот не имеет необходимых прав администратора в группе {chat_id}"
                    )
                return

            await bot.promote_chat_member(chat_id,
                                          user_id,
                                          can_change_info=False,
                                          can_delete_messages=False,
                                          can_invite_users=False,
                                          can_restrict_members=False,
                                          can_pin_messages=True,
                                          can_promote_members=False)
            await bot.set_chat_administrator_custom_title(
                chat_id, user_id, role)
            
            # Сохраняем custom_title в БД
            await db.save_user_data(user_id, custom_title=role)

            # Получаем всех админов и назначаем им эмодзи
            members = await bot.get_chat_administrators(chat_id)
            tags = []

            # Назначаем эмодзи новому участнику и другим админам
            for member in members:
                if not member.user.is_bot:
                    member_id = member.user.id
                    emoji = await assign_emoji_to_user(member_id)
                    tag = f"<a href='tg://user?id={member_id}'>{emoji}</a>"
                    tags.append(tag)

            # Разбиваем теги на группы по 10
            tag_chunks = [tags[i:i + 10] for i in range(0, len(tags), 10)]

            # Отправляем сначала приветственное сообщение
            await bot.send_message(
                chat_id,
                f'''📢 Новый участник: <a href='tg://user?id={update.new_chat_member.user.id}'>{update.new_chat_member.user.full_name}</a>
🎭 Роль: <b>{role}</b>''')

            # Отправляем все чанки с эмодзи с задержкой
            for chunk in tag_chunks:
                chunk_text = " ".join(chunk)
                await bot.send_message(chat_id, chunk_text)
                await asyncio.sleep(
                    1)  # Добавляем задержку между всеми сообщениями с тегами
            await bot.send_message(user_id,
                                   f'''🌟 <b>Добро пожаловать!</b>

Ваша заявка одобрена. Теперь вы можете взаимодействовать с меню.''',
                                   reply_markup=get_menu())

            # Send notification to LIST_ADMIN_ID
            for admin_id in LIST_ADMIN_ID:
                await bot.send_message(admin_id, f"Занята роль: {role}")
        except Exception as e:
            logging.error(f"Ошибка при назначении роли: {e}")
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"Ошибка при назначении роли пользователю {update.new_chat_member.user.full_name}: {str(e)}"
                )
    elif update.new_chat_member.status in {"left", "kicked"}:
        # Получаем данные из БД
        user_data_db = await db.get_user_data(user_id)
        custom_title = user_data_db.get("custom_title", "Неизвестно")
        
        if custom_title != "Неизвестно":
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
                await bot.send_message(
                    admin_id, f"Освободилась роль:<b>{custom_title}</b>")

            # Удаляем данные пользователя из БД
            await db.remove_emoji(user_id)
            await db.remove_user_data(user_id)


# Загрузка данных из БД при запуске
async def load_data_from_db():
    """Загружает данные из БД в память при запуске бота"""
    try:
        # Загружаем викторины
        global quiz_data, quiz_participants
        active_quizzes = await db.get_all_active_quizzes()
        quiz_data = active_quizzes
        
        # Загружаем участников викторин
        for quiz_id in active_quizzes.keys():
            participants = await db.get_quiz_participants(quiz_id)
            quiz_participants[quiz_id] = participants
        
        logging.info(f"Загружено {len(active_quizzes)} активных викторин")
        
    except Exception as e:
        logging.error(f"Ошибка при загрузке данных из БД: {e}")


# Оптимизированная проверка лимита сообщений
def check_message_limit(user_id: int) -> bool:
    count = message_counts.get(user_id, 0) + 1
    message_counts[user_id] = count
    return count <= MAX_MESSAGES


# Обработчик ответов админов на заявки пользователей
@dp.message(lambda m: m.text and m.text.lower().startswith("счёт ") and m.
            reply_to_message)
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


@dp.message(lambda m: m.chat.type == ChatType.PRIVATE and m.from_user.id in
            ADMIN_IDS and m.text and m.text.lower().startswith("сказать "))
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


@dp.message(lambda m: m.chat.type == ChatType.PRIVATE and m.from_user.id in
            ADMIN_IDS and m.text and m.text.lower() == "создать викторину")
async def create_quiz_start(message: types.Message, state: FSMContext):
    await message.reply("Напишите вопрос для викторины.")
    await state.set_state(QuizCreation.waiting_for_question)


@dp.message(QuizCreation.waiting_for_question)
async def quiz_question_handler(message: types.Message, state: FSMContext):
    await state.update_data(question=message.text)
    await message.reply("Теперь напишите варианты ответов, каждый с новой строки.")
    await state.set_state(QuizCreation.waiting_for_answers)


@dp.message(QuizCreation.waiting_for_answers)
async def quiz_answers_handler(message: types.Message, state: FSMContext):
    answers = [answer.strip() for answer in message.text.split('\n') if answer.strip()]
    
    if len(answers) < 2:
        await message.reply("Нужно минимум 2 варианта ответа. Попробуйте снова.")
        return
    
    if len(answers) > 6:
        await message.reply("Максимум 6 вариантов ответа. Попробуйте снова.")
        return
    
    await state.update_data(answers=answers)
    
    # Показываем варианты с номерами
    answer_list = "\n".join([f"{i+1}. {answer}" for i, answer in enumerate(answers)])
    await message.reply(f"<b>Варианты ответов:</b>\n{answer_list}\n\nУкажите номера правильных ответов через запятую. <b>Например: 1,3.</b>")
    await state.set_state(QuizCreation.waiting_for_correct)


@dp.message(QuizCreation.waiting_for_correct)
async def quiz_correct_handler(message: types.Message, state: FSMContext):
    try:
        correct_indices = [int(x.strip()) - 1 for x in message.text.split(',')]
        data = await state.get_data()
        answers = data['answers']
        
        # Проверяем валидность индексов
        if any(idx < 0 or idx >= len(answers) for idx in correct_indices):
            await message.reply("Неверные номера ответов. Попробуйте снова.")
            return
        
        # Создаем викторину с уникальным ID
        quiz_id = len(quiz_data) + 1
        
        # Сохраняем викторину в БД
        await db.save_quiz(
            quiz_id=quiz_id,
            chat_id=GROUP_ID,
            question=data['question'],
            answers=answers,
            correct_indices=correct_indices,
            creator_id=message.from_user.id
        )
        
        # Также сохраняем в локальной памяти для работы бота
        quiz_data[quiz_id] = {
            'question': data['question'],
            'answers': answers,
            'correct_indices': correct_indices,
            'active': True,
            'creator_id': message.from_user.id
        }
        quiz_participants[quiz_id] = {}
        
        # Создаем inline клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=answer, callback_data=f"quiz_{quiz_id}_{i}")]
            for i, answer in enumerate(answers)
        ])
        
        # Отправляем викторину в группу
        quiz_message = f"📝 <b>Викторина\n\n{data['question']}</b>"
        await bot.send_message(GROUP_ID, quiz_message, reply_markup=keyboard)
        
        await message.reply(f"Викторина #{quiz_id} создана и отправлена в группу!\n\n<b>Для завершения викторины напишите: завершить викторину {quiz_id}</b>")
        await state.clear()
        
    except ValueError:
        await message.reply("Неверный формат. Укажите номера через запятую. <b>Например: 1,3.</b>")


@dp.message(lambda m: m.chat.type == ChatType.PRIVATE and m.from_user.id in
            ADMIN_IDS and m.text and m.text.lower().startswith("завершить викторину "))
async def end_quiz_command(message: types.Message):
    try:
        quiz_id = int(message.text.split()[-1])
        
        # Проверяем викторину в БД
        quiz = await db.get_quiz(quiz_id)
        if not quiz:
            await message.reply("Викторина с таким номером не найдена.")
            return
        
        if not quiz['active']:
            await message.reply("Эта викторина уже завершена.")
            return
        
        # Завершаем викторину в БД
        await db.deactivate_quiz(quiz_id)
        
        # Обновляем локальные данные
        if quiz_id in quiz_data:
            quiz_data[quiz_id]['active'] = False
        
        # Подсчитываем результаты
        participants = await db.get_quiz_participants(quiz_id)
        correct_users = []
        incorrect_users = []
        correct_indices = set(quiz['correct_indices'])
        
        for user_id, answer_index in participants.items():
            try:
                user = await bot.get_chat(user_id)
                user_name = user.full_name
                if user.username:
                    user_name += f" (@{user.username})"
                
                if answer_index in correct_indices:
                    correct_users.append(user_name)
                else:
                    incorrect_users.append(user_name)
            except Exception as e:
                logging.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
        
        # Формируем сообщение с результатами
        results_message = f"<b> Викторина завершена!</b>\n\n"
        results_message += f"📝 Вопрос: <b>{quiz['question']}</b>\n\n"
        
        correct_answers = [quiz['answers'][i] for i in correct_indices]
        results_message += f"✅  Правильный ответ: <b>{', '.join(correct_answers)}</b>\n\n"
        
        if correct_users:
            results_message += f" <b>Правильно ответили ({len(correct_users)}):</b>\n"
            for user in correct_users:
                results_message += f"• {user}"
        else:
            results_message += " Никто не ответил правильно"
        
        if incorrect_users:
            results_message += f"\n<b>Неправильно ответили ({len(incorrect_users)}):</b>\n"
            for user in incorrect_users:
                results_message += f"• {user}\n"
        
        
        # Отправляем результаты в группу
        await bot.send_message(GROUP_ID, results_message)
        
        # Формируем детальную статистику по вариантам ответов
        total_participants = len(participants)
        stats_message = "📊 <b>Детальная статистика:</b>\n\n"
        
        # Группируем участников по их ответам
        answer_stats = {}
        for user_id, answer_index in participants.items():
            if answer_index not in answer_stats:
                answer_stats[answer_index] = []
            answer_stats[answer_index].append(user_id)
        
        # Формируем статистику для каждого варианта ответа
        for i, answer in enumerate(quiz['answers']):
            users_who_chose = answer_stats.get(i, [])
            count = len(users_who_chose)
            percentage = (count / total_participants * 100) if total_participants > 0 else 0
            
            stats_message += f"<b>{answer}</b>\n"
            stats_message += f"└ {count} чел. ({percentage:.1f}%)\n"
            
            if users_who_chose:
                user_names = []
                for user_id in users_who_chose:
                    try:
                        user = await bot.get_chat(user_id)
                        user_name = user.full_name
                        if user.username:
                            user_name += f" (@{user.username})"
                        user_names.append(user_name)
                    except Exception as e:
                        logging.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
                        user_names.append(f"ID: {user_id}")
                
                stats_message += f"└ {', '.join(user_names)}\n"
            else:
                stats_message += "└ Никто не выбрал\n"
            
            stats_message += "\n"
        
        # Отправляем детальную статистику
        await bot.send_message(GROUP_ID, stats_message)
        
        # Уведомляем админа
        await message.reply(f"Викторина #{quiz_id} завершена. Результаты отправлены в группу.")
        
    except (ValueError, IndexError):
        await message.reply("Неверный формат команды. Используйте: завершить викторину [номер].")
    except Exception as e:
        logging.error(f"Ошибка при завершении викторины: {e}")
        await message.reply("Произошла ошибка при завершении викторины.")


@dp.message()
async def handle_admin_response(message: types.Message):
    try:
        # Антиспам проверка для пользователей не из группы
        if (message.chat.type == ChatType.PRIVATE 
            and message.from_user.id not in ADMIN_IDS):

            user_id = message.from_user.id
            if not await is_member(user_id) and not check_message_limit(user_id):
                await message.answer(
                    "Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/alren15'>администратору</a>."
                )
                return

        # Проверяем, не является ли это ответом пользователя на сообщение админа
        if (message.chat.type == ChatType.PRIVATE 
            and message.from_user.id not in ADMIN_IDS 
            and message.reply_to_message):
            
            reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            
            # Проверяем, что это ответ на сообщение от администратора
            if "Ответ администратора:" in reply_text:
                user = message.from_user
                user_id = user.id
                
                # Отправляем ответ пользователя всем админам
                admin_notification = f'''Пользователь <b>{user.full_name}</b> ответил:
                
<code>{message.text}</code>'''

                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, admin_notification, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.error(f"Ошибка отправки ответа пользователя админу {admin_id}: {e}")
                
                await message.reply("Ваш ответ отправлен администраторам.")
                return

        # Проверяем, что это ответ админа на заявку
        if not (message.chat.type == ChatType.PRIVATE and message.from_user.id
                in ADMIN_IDS and message.reply_to_message):
            return

        reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""

        # Проверяем, что это одна из заявок, на которые можно отвечать
        if not any(keyword in reply_text for keyword in [
            "Заявка на вступление!", 
            "Заявка на рест",
            "Не может влиться!",
            "ответил:"
        ]):
            return

        # Парсим ID пользователя из заявки на вступление
        user_id = None
        for line in reply_text.split('\n'):
            if line.startswith("#️⃣ ID:"):
                user_id_str = line.split(":")[1].strip().replace(
                    "<code>", "").replace("</code>", "")
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
                parse_mode=ParseMode.HTML)

            # Формируем текст уведомления для других админов в правильном формате

            notification_text = f"{admin.full_name} отправил ответ {target_user.full_name}:\n\n<code>{message.text}</code>"

            # Отправляем уведомление другим админам
            for admin_id in ADMIN_IDS:
                if admin_id != message.from_user.id:
                    try:
                        await bot.send_message(admin_id,
                                               notification_text,
                                               parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.error(
                            f"Ошибка отправки уведомления админу {admin_id}: {e}"
                        )

            await message.reply(f"Ответ успешно отправлен пользователю.")

        except Exception as e:
            error_msg = f"Не удалось отправить ответ: {str(e)}"
            if "user is deactivated" in str(
                    e) or "bot was blocked by the user" in str(e):
                error_msg = "Пользователь заблокировал бота или удалил аккаунт"
            await message.reply(error_msg)

    except Exception as e:
        logging.error(f"Ошибка в обработчике ответов: {str(e)}",
                      exc_info=True)
        await message.reply("Произошла системная ошибка. Проверьте логи.")


async def main():
    try:
        # Подключаемся к базе данных
        if not await db.connect():
            logging.error("Не удалось подключиться к базе данных. Остановка бота.")
            return
        
        # Загружаем данные из БД
        await load_data_from_db()
        
        logging.info("Bot started")
        await dp.start_polling(bot, allowed_updates=["message", "chat_member", "callback_query"])
    except Exception as e:
        logging.error(f"Error: {e}")
        raise
    finally:
        # Закрываем соединение с БД при остановке
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
