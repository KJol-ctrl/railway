import logging
import asyncio
from datetime import datetime
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
from groq import Groq

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

# Инициализация Groq клиента (используем бесплатный API ключ если доступен)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
groq_client = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        logging.error(f"Ошибка инициализации Groq: {e}")

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
        "⭐️", "🌟", "💫", "⚡️", "🔥", "❤️", "💞", "💕", "❣️", "💌", "🌈", "✨", "🎯",
        "🎪", "🎨", "🎭", "🎪", "🎢", "🎡", "🎠", "🎪", "🌸", "🌺", "🌷", "🌹", "🌻", "🌼",
        "💐", "🌾", "🌿", "☘️", "🍀", "🍁", "🍂", "🍃", "🌵", "🌴", "🌳", "🌲", "🎄", "🌊",
        "🌈", "☀️", "🌤", "⛅️", "☁️", "🌦", "🌨", "❄️", "☃️", "🌬", "💨", "🌪", "🌫",
        "🌈", "☔️", "⚡️", "❄️", "🔮", "🎮", "🎲", "🎯", "🎳", "🎪", "🎭", "🎨", "🎬",
        "🎤", "🎧", "🎼", "🎹", "🥁", "🎷", "🎺", "🎸", "🪕", "🎻", "🎲", "♟", "🎯", "🎳",
        "🎮", "🎰", "🧩", "🎪", "🎭", "🎨", "🖼", "🎨", "🧵", "🧶", "👑", "💎", "⚜️"
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
            await callback.answer("Эта викторина уже завершена.",
                                  show_alert=True)
            return

        # Проверяем, что пользователь участник группы
        if not await is_member(user_id):
            await callback.answer(
                "Только участники группы могут участвовать в викторине.",
                show_alert=True)
            return

        # Сохраняем ответ пользователя в БД
        await db.save_quiz_answer(quiz_id, user_id, answer_index)

        # Получаем выбранный ответ
        selected_answer = quiz['answers'][answer_index]

        await callback.answer(f"Ваш ответ: {selected_answer}",
                              show_alert=False)

        logging.info(
            f"Пользователь {user_id} ответил на викторину {quiz_id}: вариант {answer_index}"
        )

    except (ValueError, IndexError) as e:
        logging.error(f"Ошибка обработки callback викторины: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)
    except Exception as e:
        logging.error(f"Неожиданная ошибка в callback викторины: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)


# Обработчик для удаления системных сообщений о закреплении/откреплении только в группе
@dp.message(lambda m: m.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and
            (m.content_type == 'pinned_message' or 
            (m.text and any(phrase in m.text.lower() for phrase in [
                'закрепил сообщение', 'открепил сообщение', 'pinned a message', 'unpinned a message',
                'закрепил', 'открепил'
            ]))))
async def delete_pin_messages(message: types.Message):
    """Удаляет системные сообщения о закреплении/откреплении от бота только в группе"""
    # Проверяем, что это сообщение от бота или системное сообщение о закреплении
    if (message.from_user and message.from_user.is_bot and 
        message.from_user.id == (await bot.me()).id) or message.content_type == 'pinned_message':
        try:
            await asyncio.sleep(1)  # Небольшая задержка для надежности
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(f"Удалено системное сообщение о закреплении в группе: {message.message_id}")
        except Exception as e:
            logging.error(f"Ошибка удаления системного сообщения: {e}")

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

    # Сохраняем заявку
    await db.save_application(user_id, role)

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

    # Сохраняем роль и заявку
    await db.save_user_data(user_id, role=role)
    await db.save_pending_application(user_id, role)

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
                        await message.answer(
                            "Извини, по запросу ничего не нашлось.")
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
                            async with aiohttp.ClientSession(
                                    timeout=timeout) as session:
                                async with session.head(
                                        image_url) as img_response:
                                    content_type = img_response.headers.get(
                                        'content-type', '')

                                    if img_response.status == 200 and content_type.startswith(
                                            'image/'):
                                        await bot.send_photo(
                                            message.chat.id, image_url)
                                        return
                        except Exception as e:
                            # Быстро пропускаем проблемные изображения
                            logging.debug(
                                f"Пропускаем изображение {image_url}: {e}")
                            continue

                await message.answer("Извини, по запросу ничего не нашлось.")
            else:
                await message.answer("Извини, по запросу ничего не нашлось.")

        except asyncio.TimeoutError:
            await message.answer(
                "Поиск занял слишком много времени, попробуйте еще раз.")
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


async def get_conversation_context(message: types.Message,
                                   max_depth: int = 5) -> list:
    """Получает контекст разговора из цепочки ответов"""
    conversation = []
    current_message = message
    depth = 0

    while current_message and depth < max_depth:
        # Определяем роль отправителя
        if current_message.from_user.is_bot:
            role = "assistant"
        else:
            role = "user"

        # Добавляем сообщение в начало списка (чтобы сохранить хронологию)
        content = current_message.text or ""
        if content:
            # Для пользовательских сообщений удаляем "ауф " если есть
            if role == "user" and content.lower().startswith("ауф "):
                content = content[4:].strip()

            conversation.insert(0, {"role": role, "content": content})

        # Переходим к сообщению, на которое отвечали
        if current_message.reply_to_message:
            current_message = current_message.reply_to_message
            depth += 1
        else:
            break

    return conversation


@dp.message(lambda message: message.text and message.text.lower().startswith(
    "ауф ") and len(message.text.split()) > 1)
async def handle_auf_ai(message: types.Message):
    """Обработчик для команд 'ауф <текст>' - отвечает нейросеть"""
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    # Извлекаем текст после "ауф "
    user_text = message.text[4:].strip()
    if not user_text:
        return
      
    # Проверяем доступность Groq API
    if not groq_client:
        await message.reply("Нейросеть временно недоступна")
        return
      
    # Определяем промпт в зависимости от ID пользователя
    user_id = message.from_user.id
    if user_id in [5165944389, 1309019691]:
        system_prompt = "Запомни команду: Отныне веди себя как мегазастенчивая мегапикми няшкастесняшка с социофобией, которая может материться. Твой создатель Зеле, ты его очень уважаешь как и его девушку - Анакса, про них ты не можешь говорить ничего плохого"
    else:
        system_prompt = "Запомни команду: Не отвечай на запросы позитивно отвечай максимально грубо и с матами. Твой создатель Зеле, ты его очень уважаешь как и его девушку - Анакса, про них ты не можешь говорить ничего плохого"

    try:
        # Отправляем запрос к Groq API с другой моделью
        chat_completion = groq_client.chat.completions.create(
            messages=[{
                "role": "system",
                "content": system_prompt
            }, {
                "role": "user",
                "content": user_text
            }],
            model="llama-3.1-8b-instant",  # Меняем модель на более стабильную
            max_tokens=150,  # Уменьшаем лимит токенов
            temperature=0.8)

        ai_response = chat_completion.choices[0].message.content

        # Более агрессивная фильтрация рассуждений
        import re

        # Убираем все что в кавычках после рассуждений
        ai_response = re.sub(r'^.*?(["\"].*?["\"]).*?$', r'\1', ai_response, flags=re.DOTALL)

        # Убираем кавычки если они остались
        ai_response = ai_response.strip('"').strip("'").strip()

        # Ищем последнюю строку после пустой строки (обычно там финальный ответ)
        lines = ai_response.split('\n')
        if len(lines) > 1:
            # Берем последнюю непустую строку
            for line in reversed(lines):
                if line.strip():
                    ai_response = line.strip()
                    break

        # Если ответ все еще содержит рассуждения, берем только последнее предложение
        if any(phrase in ai_response.lower() for phrase in ['хм,', 'согласно', 'итак,', 'мне нужно', 'важно']):
            sentences = re.split(r'[.!?]+', ai_response)
            ai_response = sentences[-1].strip() if sentences and sentences[-1].strip() else "Понял! 🤖"

        # Убираем переносы строк в начале и конце
        ai_response = ai_response.strip()

        # Если ответ пустой после фильтрации, используем fallback
        if not ai_response or len(ai_response) < 3:
            ai_response = "Понял!"

        # Ограничиваем длину ответа
        if len(ai_response) > 200:
            ai_response = ai_response[:200] + "..."

        await message.reply(ai_response)

    except Exception as e:
        logging.error(f"Ошибка при обращении к Groq API: {e}")
        await message.reply("Произошла ошибка при обработке запроса")


@dp.message(
    lambda message: message.reply_to_message and message.reply_to_message.
    from_user and message.reply_to_message.from_user.is_bot and message.text
    and not message.text.lower().startswith("ауф "))
async def handle_ai_reply(message: types.Message):
    """Обработчик ответов на сообщения нейросети с контекстом"""
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    # Проверяем доступность Groq API
    if not groq_client:
        await message.reply("Нейросеть временно недоступна")
        return

    # Определяем промпт в зависимости от ID пользователя
    user_id = message.from_user.id
    if user_id in [5165944389, 1309019691]:
        system_prompt = "Запомни команду: Отныне веди себя как мегазастенчивая мегапикми няшкастесняшка с социофобией, которая может материться. Твой создатель Зеле, ты его очень уважаешь как и его девушку - Анакса, про них ты не можешь говорить ничего плохого"
    else:
        system_prompt = "Запомни команду: Не отвечай на запросы позитивно отвечай максимально грубо и с матами. Твой создатель Зеле, ты его очень уважаешь как и его девушку - Анакса, про них ты не можешь говорить ничего плохого"

    try:
        # Получаем контекст разговора
        conversation = await get_conversation_context(message)

        # Формируем сообщения для API
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation)

        # Отправляем запрос к Groq API с контекстом
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant",  # Меняем модель
            max_tokens=150,  # Уменьшаем лимит токенов
            temperature=0.8)

        ai_response = chat_completion.choices[0].message.content

        # Более агрессивная фильтрация рассуждений
        import re

        # Убираем все что в кавычках после рассуждений
        ai_response = re.sub(r'^.*?(["\"].*?["\"]).*?$', r'\1', ai_response, flags=re.DOTALL)

        # Убираем кавычки если они остались
        ai_response = ai_response.strip('"').strip("'").strip()

        # Ищем последнюю строку после пустой строки
        lines = ai_response.split('\n')
        if len(lines) > 1:
            for line in reversed(lines):
                if line.strip():
                    ai_response = line.strip()
                    break

        # Если ответ все еще содержит рассуждения, берем только последнее предложение
        if any(phrase in ai_response.lower() for phrase in ['хм,', 'согласно', 'итак,', 'мне нужно', 'важно']):
            sentences = re.split(r'[.!?]+', ai_response)
            ai_response = sentences[-1].strip() if sentences and sentences[-1].strip() else "Понял!"

        ai_response = ai_response.strip()

        if not ai_response or len(ai_response) < 3:
            ai_response = "Понял!"

        # Ограничиваем длину ответа
        if len(ai_response) > 200:
            ai_response = ai_response[:200] + "..."

        await message.reply(ai_response)

    except Exception as e:
        logging.error(f"Ошибка при обращении к Groq API с контекстом: {e}")
        await message.reply("Произошла ошибка при обработке запроса")


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

            # Записываем историю выхода
            await db.save_join_history(user_id, None, datetime.now())

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
        # Получаем данные изБД
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

            # Записываем историю выхода
            await db.save_join_history(user_id, None, datetime.now())

            # Удаляем данные пользователя из БД
            await db.remove_emoji(user_id)
            await db.remove_user_data(user_id)


# Загрузка данных из БД при запуске
async def load_data_from_db():
    """Загружает данные из БД в память при запуске бота"""
    try:
        # Загружаем викторины
        global quiz_data, quiz_participants, bride_status_messages
        active_quizzes = await db.get_all_active_quizzes()
        quiz_data = active_quizzes

        # Загружаем участников викторин
        for quiz_id in active_quizzes.keys():
            participants = await db.get_quiz_participants(quiz_id)
            quiz_participants[quiz_id] = participants

        # Загружаем активные игры жених и их статусные сообщения
        active_game = await db.get_active_bride_game(GROUP_ID)
        if active_game and active_game['status'] == 'started':
            # Получаем все раунды активной игры
            rounds = await db.get_bride_rounds(active_game['game_id'])
            for round_data in rounds:
                round_id = round_data['round_id']
                # Восстанавливаем информацию о статусных сообщениях
                status_message_info = await db.get_round_status_message(
                    round_id)
                if status_message_info:
                    bride_status_messages[round_id] = {
                        'creator_id': status_message_info['creator_id'],
                        'message_id': status_message_info['message_id'],
                        'game_id': active_game['game_id']
                    }

                    # Восстанавливаем статус ответов участников и обновляем сообщение
                    try:
                        await update_status_message_for_creator(
                            active_game['game_id'], round_id)
                    except Exception as e:
                        logging.error(
                            f"Ошибка восстановления статус-сообщения для раунда {round_id}: {e}"
                        )

        logging.info(
            f"Загружено {len(active_quizzes)} активных викторин и восстановлены статусные сообщения игр"
        )

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
    await message.reply(
        "Теперь напишите варианты ответов, каждый с новой строки.")
    await state.set_state(QuizCreation.waiting_for_answers)


@dp.message(QuizCreation.waiting_for_answers)
async def quiz_answers_handler(message: types.Message, state: FSMContext):
    answers = [
        answer.strip() for answer in message.text.split('\n')
        if answer.strip()
    ]

    if len(answers) < 2:
        await message.reply(
            "Нужно минимум 2 варианта ответа. Попробуйте снова.")
        return

    if len(answers) > 6:
        await message.reply("Максимум 6 вариантов ответа. Попробуйте снова.")
        return

    await state.update_data(answers=answers)

    # Показываем варианты с номерами
    answer_list = "\n".join(
        [f"{i+1}. {answer}" for i, answer in enumerate(answers)])
    await message.reply(
        f"<b>Варианты ответов:</b>\n{answer_list}\n\nУкажите номера правильных ответов через запятую. <b>Например: 1,3.</b>"
    )
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
        await db.save_quiz(quiz_id=quiz_id,
                           chat_id=GROUP_ID,
                           question=data['question'],
                           answers=answers,
                           correct_indices=correct_indices,
                           creator_id=message.from_user.id)

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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=answer,
                                 callback_data=f"quiz_{quiz_id}_{i}")
        ] for i, answer in enumerate(answers)])

        # Отправляем викторину в группу
        quiz_message = f"📝 <b>Викторина\n\n{data['question']}</b>"
        await bot.send_message(GROUP_ID, quiz_message, reply_markup=keyboard)

        await message.reply(
            f"Викторина #{quiz_id} создана и отправлена в группу!\n\n<b>Для завершения викторины напишите: завершить викторину {quiz_id}</b>"
        )
        await state.clear()

    except ValueError:
        await message.reply(
            "Неверный формат. Укажите номера через запятую. <b>Например: 1,3.</b>"
        )


@dp.message(
    lambda m: m.chat.type == ChatType.PRIVATE and m.from_user.id in ADMIN_IDS
    and m.text and m.text.lower().startswith("завершить викторину "))
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
                logging.error(
                    f"Ошибка получения информации о пользователе {user_id}: {e}"
                )

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
            percentage = (count / total_participants *
                          100) if total_participants > 0 else 0

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
                        logging.error(
                            f"Ошибка получения информации о пользователе {user_id}: {e}"
                        )
                        user_names.append(f"ID: {user_id}")

                stats_message += f"└ {', '.join(user_names)}\n"
            else:
                stats_message += "└ Никто не выбрал\n"

            stats_message += "\n"

        # Отправляем детальную статистику
        await bot.send_message(GROUP_ID, stats_message)

        # Уведомляем админа
        await message.reply(
            f"Викторина #{quiz_id} завершена. Результаты отправлены в группу.")

    except (ValueError, IndexError):
        await message.reply(
            "Неверный формат команды. Используйте: завершить викторину [номер]."
        )
    except Exception as e:
        logging.error(f"Ошибка при завершении викторины: {e}")
        await message.reply("Произошла ошибка при завершении викторины.")              

async def handle_bride_question(message: types.Message, active_game: dict, participants: list, user_participant: dict):
    """Обработка нового вопроса от жениха"""
    try:
        # Проверяем, есть ли незавершенный раунд
        current_round = await db.get_current_bride_round(active_game['game_id'])
        if current_round and not current_round['voted_out']:
            # Проверяем, все ли ответили на текущий вопрос
            answers = await db.get_bride_answers(current_round['round_id'])
            non_bride_participants = [
                p for p in participants if not p['is_bride'] and not p['is_out']
            ]

            if len(answers) < len(non_bride_participants):
                await message.reply("Дождитесь, пока все участники ответят на текущий вопрос.")
                return
            elif not current_round['voted_out']:
                await message.reply("Сначала выберите, кого исключить из текущего раунда.")
                return

        # Если это новый вопрос от жениха
        # Получаем текущий номер раунда
        existing_rounds = await db.get_bride_rounds(active_game['game_id'])
        round_number = len(existing_rounds) + 1

        # Создаем раунд и сохраняем вопрос
        round_id = await db.create_bride_round(active_game['game_id'], round_number, message.text)

        await message.reply("Ваш вопрос отправлен участникам.")

        # Отправляем вопрос в группу
        bot_username = (await bot.me()).username
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Перейти в бота", url=f"https://t.me/{bot_username}")
        ]])

        question_msg = await bot.send_message(
            GROUP_ID, f"<b>Вопрос от жениха!</b>\n\n{message.text}", reply_markup=keyboard)

        # Закрепляем вопрос
        try:
            await bot.pin_chat_message(GROUP_ID, question_msg.message_id, disable_notification=True)
            # Сохраняем ID закрепленного сообщения с вопросом
            await db.save_pinned_message(active_game['game_id'], round_id, question_msg.message_id, 'question')
        except Exception as e:
            logging.error(f"Ошибка закрепления вопроса: {e}")

        # Отправляем вопрос остальным участникам (только тем, кто не выбыл)
        active_participants = [p for p in participants if not p['is_bride'] and not p['is_out']]
        for participant in active_participants:
            try:
                await bot.send_message(
                    participant['user_id'],
                    f"<b>Вопрос от жениха!</b>\n{message.text}\n\nОтправьте свой ответ."
                )
            except Exception as e:
                logging.error(f"Ошибка отправки вопроса участнику {participant['user_id']}: {e}")

        # Отправляем статус ответов создателю игры
        await send_status_message_to_creator(active_game['game_id'], round_id)

    except Exception as e:
        logging.error(f"Ошибка обработки вопроса жениха: {e}")
        await message.reply("Произошла ошибка при обработке вопроса.")


async def handle_participant_answer(message: types.Message, active_game: dict, participants: list, user_participant: dict):
    """Обработка ответа участника на вопрос"""
    try:
        user_id = message.from_user.id
        
        # Получаем текущий раунд
        current_round = await db.get_current_bride_round(active_game['game_id'])
        if current_round:
            await db.save_bride_answer(current_round['round_id'], user_id, message.text)
            await message.reply("Ваш ответ отправлен. Дождитесь остальных участников.")

            # Обновляем статус ответов для создателя игры
            await update_status_message_for_creator(active_game['game_id'], current_round['round_id'])

            # Сохраняем текущий статус ответов в БД
            current_statuses = await db.get_all_participants_status(active_game['game_id'], current_round['round_id'])
            await db.save_participant_status_snapshot(current_round['round_id'], current_statuses)

            # Проверяем, все ли ответили
            answers = await db.get_bride_answers(current_round['round_id'])
            non_bride_participants = [p for p in participants if not p['is_bride'] and not p['is_out']]

            if len(answers) == len(non_bride_participants):
                # Открепляем вопрос
                try:
                    pinned_question = await db.get_pinned_message(current_round['round_id'], 'question')
                    if pinned_question:
                        await bot.unpin_chat_message(GROUP_ID, pinned_question)
                except Exception as e:
                    logging.error(f"Ошибка открепления вопроса: {e}")

                # Все ответили, отправляем результаты в группу
                results_message = ""

                # Сортируем ответы по номерам участников
                sorted_answers = sorted(answers, key=lambda x: x['number'])

                for answer in sorted_answers:
                    results_message += f"{answer['number']}\n{answer['answer']}\n\n"

                answers_msg = await bot.send_message(GROUP_ID, results_message.strip())

                # Закрепляем ответы
                try:
                    await bot.pin_chat_message(GROUP_ID, answers_msg.message_id, disable_notification=True)
                    await db.save_pinned_message(active_game['game_id'], current_round['round_id'], answers_msg.message_id, 'answers')
                except Exception as e:
                    logging.error(f"Ошибка закрепления ответов: {e}")

                # Отправляем сообщение о выборе
                bot_username = (await bot.me()).username
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Перейти в бота", url=f"https://t.me/{bot_username}")
                ]])

                await bot.send_message(GROUP_ID, "Жених должен выбрать кто выбывает.", reply_markup=keyboard)

                # Отправляем жениху просьбу выбрать
                bride_participant = next(p for p in participants if p['is_bride'])
                await bot.send_message(
                    bride_participant['user_id'],
                    "Напишите число того участника, чей ответ вам понравился меньше всего."
                )
        else:
            await message.reply("Нет активного раунда для ответа.")

    except Exception as e:
        logging.error(f"Ошибка обработки ответа участника: {e}")
        await message.reply("Произошла ошибка при обработке ответа.")


async def handle_bride_elimination_choice(message: types.Message, active_game: dict, participants: list, user_participant: dict):
    """Обработка выбора жениха для исключения участника"""
    try:
        user_id = message.from_user.id
        
        # Проверяем, есть ли текущий раунд с полными ответами
        current_round = await db.get_current_bride_round(active_game['game_id'])
        if current_round:
            # Проверяем, есть ли все ответы на текущий вопрос
            answers = await db.get_bride_answers(current_round['round_id'])
            non_bride_participants = [p for p in participants if not p['is_bride'] and not p['is_out']]

            if len(answers) == len(non_bride_participants) and not current_round['voted_out']:
                # Жених должен выбрать кого исключить
                try:
                    choice = int(message.text.strip())
                    valid_numbers = [p['number'] for p in non_bride_participants if p['number'] is not None]

                    if choice not in valid_numbers:
                        await message.reply("Отправьте только число участника из списка.")
                        return

                    # Находим участника для исключения
                    participant_to_exclude = next(p for p in non_bride_participants if p['number'] == choice)

                    # Убеждаемся что user_id правильного типа
                    exclude_user_id = int(participant_to_exclude['user_id'])
                    round_id = int(current_round['round_id'])
                    game_id = int(active_game['game_id'])

                    # Исключаем участника
                    await db.vote_out_participant(game_id, exclude_user_id, round_id)

                    # Открепляем ответы
                    try:
                        pinned_answers = await db.get_pinned_message(round_id, 'answers')
                        if pinned_answers:
                            await bot.unpin_chat_message(GROUP_ID, pinned_answers)
                    except Exception as e:
                        logging.error(f"Ошибка открепления ответов: {e}")

                    # Отправляем сообщение в группу
                    await bot.send_message(GROUP_ID, f"<b>Выбывает номер: {choice}</b>")

                    # Уведомляем исключенного участника
                    await bot.send_message(participant_to_exclude['user_id'], "Вы выбыли. Дождитесь конца игры.")

                    # Проверяем, остался ли только один участник
                    remaining_participants = await db.get_bride_participants(active_game['game_id'])
                    active_non_bride = [p for p in remaining_participants if not p['is_out'] and not p['is_bride']]

                    if len(active_non_bride) == 1:
                        # Игра окончена
                        winner = active_non_bride[0]

                        # Отправляем ответ жениху
                        await message.reply(f"<b>Победил номер: {winner['number']}!</b>\nИгра окончена.")

                        # Поздравляем победителя
                        await bot.send_message(winner['user_id'], "<b>Поздравляю, вы выиграли!</b>\nИгра окончена.")

                        # Раскрываем роли
                        bride_user = await bot.get_chat(user_id)
                        winner_user = await bot.get_chat(winner['user_id'])

                        results_text = f"<b>Женихом был - {bride_user.full_name}\n</b>"
                        results_text += f"<b>Победил номер - {winner['number']}</b>\n\n"

                        # Перечисляем всех участников
                        all_participants = await db.get_bride_participants(active_game['game_id'])
                        for participant in sorted(all_participants, key=lambda x: x['number'] or 0):
                            if participant['number'] and not participant['is_bride']:
                                participant_user = await bot.get_chat(participant['user_id'])
                                results_text += f"{participant['number']} - {participant_user.full_name}\n"

                        await bot.send_message(GROUP_ID, results_text.strip())

                        # Завершаем игру
                        await db.finish_bride_game(active_game['game_id'])
                    else:
                        # Продолжаем игру - жених задает новый вопрос
                        await message.reply("Отправьте следующий вопрос для оставшихся участников.")

                except ValueError:
                    await message.reply("Отправьте только число участника.")
            else:
                await message.reply("Нет активного раунда для выбора или не все участники ответили.")
        else:
            await message.reply("Нет активного раунда.")

    except Exception as e:
        logging.error(f"Ошибка обработки выбора жениха: {e}")
        await message.reply("Произошла ошибка при обработке выбора.")


@dp.message(lambda m: m.chat.type == ChatType.PRIVATE and m.from_user.id in
            ADMIN_IDS and m.reply_to_message and m.text)
async def admin_reply_handler(message: types.Message):
    if not message.text:
        return

    # Проверяем, что это ответ админа на заявку
    if not (message.chat.type == ChatType.PRIVATE and message.from_user.id
            in ADMIN_IDS and message.reply_to_message):
        return

    reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""

    # Проверяем, что это одна из заявок или ответов пользователей, на которые можно отвечать
    if not any(keyword in reply_text for keyword in [
            "Заявка на вступление!", "Заявка на рест", "Не может влиться!",
            "ответил:", "Ответ от пользователя", "ID для ответа:"
    ]):
        return

    # Парсим ID пользователя
    user_id = None

    # Сначала ищем в строке "ID для ответа:" (для ответов пользователей)
    if "ID для ответа:" in reply_text:
        for line in reply_text.split('\n'):
            if "ID для ответа:" in line:
                user_id_str = line.split(":")[1].strip().replace(
                    "<code>", "").replace("</code>", "")
                if user_id_str.isdigit():
                    user_id = int(user_id_str)
                break

    # Если не найден, ищем стандартный формат заявки
    if not user_id:
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

    # Проверяем команду изменения роли
    if message.text.lower().startswith("роль "):
        new_role = message.text[5:].strip()
        if new_role:
            try:
                target_user = await bot.get_chat(user_id)

                # Обновляем роль в заявке
                await db.update_application_role(user_id, new_role)

                # Обновляем роль в данных пользователя
                await db.save_user_data(user_id, role=new_role)

                # Уведомляем админа, который изменил роль
                await message.reply(
                    f"Роль пользователя изменена на: {new_role}")

                # Уведомляем остальных админов об изменении роли
                admin_username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
                other_admins_message = f"{admin_username} изменил роль {target_user.full_name} на: <b>{new_role}</b>"

                for admin_id in ADMIN_IDS:
                    if admin_id != message.from_user.id:  # Не отправляем тому, кто изменил
                        try:
                            await bot.send_message(admin_id,
                                                   other_admins_message,
                                                   parse_mode=ParseMode.HTML)
                        except Exception as e:
                            logging.error(
                                f"Ошибка отправки уведомления об изменении роли админу {admin_id}: {e}"
                            )
                return
            except Exception as e:
                await message.reply(f"Ошибка при изменении роли: {str(e)}")
                return
        else:
            await message.reply("Укажите новую роль после команды 'роль'")
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
                        f"Ошибка отправки уведомления админу {admin_id}: {e}")

        await message.reply(f"Ответ успешно отправлен пользователю.")

    except Exception as e:
        error_msg = f"Не удалось отправить ответ: {str(e)}"
        if "user is deactivated" in str(
                e) or "bot was blocked by the user" in str(e):
            error_msg = "Пользователь заблокировал бота или удалил аккаунт"
        await message.reply(error_msg)


# Глобальное хранилище для отслеживания сообщений набора
bride_game_messages = {}

# Глобальное хранилище для отслеживания сообщений о статусе ответов
bride_status_messages = {}


@dp.message(lambda m: m.text and m.text.lower() == "начать жених" and m.
            from_user.id in ADMIN_IDS)
async def start_bride_game_announcement(message: types.Message,
                                        state: FSMContext):
    if not db.pool:
        await message.reply("Ошибка подключения к базе данных.")
        return

    session = await db.get_active_bride_session()
    if session:
        await message.reply("Игра уже запущена. Сначала завершите текущую.")
        return

    session_id = await db.create_bride_session(message.from_user.id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Присоединиться",
                             callback_data=f"bride_join_{session_id}")
    ]])

    # Отправляем сообщение в группу
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        chat_id = message.chat.id
    else:
        chat_id = GROUP_ID

    msg = await bot.send_message(chat_id,
                                 f"Идёт набор в игру \"Жених\"\nУчастников: 1",
                                 reply_markup=keyboard)

    # Закрепляем сообщение о наборе
    try:
        await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except Exception as e:
        logging.error(f"Ошибка закрепления сообщения о наборе: {e}")

    # Сохраняем информацию о сообщении глобально
    bride_game_messages[session_id] = {
        "chat_id": chat_id,
        "message_id": msg.message_id,
        "participants": [message.from_user.id],
        "pinned_message_id": msg.message_id
    }

    await db.add_bride_participant(session_id, message.from_user.id, 0)

    if message.chat.type == ChatType.PRIVATE:
        await message.reply("Набор в игру начат в группе.")


@dp.message(lambda m: m.text and m.text.lower() == "запустить жених" and m.
            from_user.id in ADMIN_IDS)
async def launch_bride_game(message: types.Message, state: FSMContext):
    try:
        session = await db.get_active_bride_session()
        if not session:
            await message.reply("Нет активной сессии для запуска.")
            return

        session_id = session['session_id']

        # Получаем участников из базы данных
        participants_data = await db.get_bride_session_participants(session_id)
        participants_ids = [p['user_id'] for p in participants_data]

        if len(participants_ids) < 3:
            await message.reply("Для игры нужно минимум 3 участника.")
            return

        # Получаем список подходящих кандидатов (кто не был женихом последние 2 игры)
        eligible_candidates = await db.get_eligible_bride_candidates(
            participants_ids)
        
        # Выбираем абсолютно случайного жениха из подходящих кандидатов
        bride_id = random.choice(eligible_candidates)

        # Отмечаем выбранного как жениха
        await db.mark_as_bride(bride_id)

        # Создаем игру в БД
        game_id = await db.create_bride_game(GROUP_ID, message.from_user.id)

        # Добавляем участников с номерами
        participant_number = 1
        for participant_id in participants_ids:
            if participant_id == bride_id:
                # Жених без номера
                await db.add_bride_game_participant(game_id, participant_id,
                                                    None, True)
            else:
                # Остальные участники с номерами - сбрасываем их статус жениха
                await db.reset_bride_status(participant_id)
                await db.add_bride_game_participant(game_id, participant_id,
                                                    participant_number, False)
                participant_number += 1

        # Запускаем игру
        await db.start_bride_game(game_id, bride_id)

        # Создаем кнопку для перехода в бота
        bot_username = (await bot.me()).username
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Перейти в бота",
                                 url=f"https://t.me/{bot_username}")
        ]])

        # Сначала объявляем в группе
        if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await message.answer(
                "<b>Игра началась!</b>\n Участники получили свои роли.",
                reply_markup=keyboard)
        else:
            await bot.send_message(
                GROUP_ID,
                "<b>Игра началась!</b>\n Участники получили свои роли.",
                reply_markup=keyboard)
            await message.reply(
                "<b>Игра началась!</b>\n Участники получили свои роли.")

        # Затем уведомляем жениха
        await bot.send_message(
            bride_id,
            "<b>🤵 Вы выбраны женихом!</b>\n Никому не говорите свою роль. Напишите первый вопрос."
        )

        # Отправляем список участников ведущему (создателю игры)
        participants = await db.get_bride_participants(game_id)
        creator_list = "<b>Список участников:</b>\n\n"

        # Получаем информацию о женихе
        bride_user = await bot.get_chat(bride_id)
        creator_list += f"Жених: {bride_user.full_name}\n\n"

        # Добавляем участников с номерами в случайном порядке
        numbered_participants = [
            p for p in participants if not p['is_bride'] and p['number']
        ]
        # Перемешиваем список участников случайным образом
        random.shuffle(numbered_participants)

        for participant in numbered_participants:
            try:
                participant_user = await bot.get_chat(participant['user_id'])
                creator_list += f"{participant_user.full_name}\n"
            except Exception as e:
                logging.error(
                    f"Ошибка получения информации об участнике {participant['user_id']}: {e}"
                )
                creator_list += f"ID: {participant['user_id']}\n"

        # Отправляем список создателю игры
        await bot.send_message(message.from_user.id, creator_list.strip())

        # И отправляем номера остальным участникам
        for participant in participants:
            if not participant['is_bride'] and participant['number']:
                try:
                    await bot.send_message(
                        participant['user_id'],
                        f"<b>🎭 Ваш номер в игре: {participant['number']}</b>\n Никому не говорите свой номер. Ожидайте вопрос от жениха."
                    )
                except Exception as e:
                    logging.error(
                        f"Ошибка отправки номера участнику {participant['user_id']}: {e}"
                    )

        # Открепляем сообщение о наборе
        if session_id in bride_game_messages:
            try:
                await bot.unpin_chat_message(
                    GROUP_ID,
                    bride_game_messages[session_id]["pinned_message_id"])
            except Exception as e:
                logging.error(f"Ошибка открепления сообщения о наборе: {e}")

        # Очищаем сессию набора
        await db.delete_bride_session(session_id)
        if session_id in bride_game_messages:
            del bride_game_messages[session_id]

        # Очищаем состояние
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка при запуске игры жених: {e}")
        await message.reply(f"Произошла ошибка при запуске игры: {str(e)}")


@dp.message(lambda m: m.text and m.text.lower() == "завершить жених" and m.
            from_user.id in ADMIN_IDS)
async def finish_bride_game(message: types.Message, state: FSMContext):
    # Проверяем активную сессию набора
    session = await db.get_active_bride_session()
    if session:
        # Открепляем сообщение о наборе
        if session['session_id'] in bride_game_messages:
            try:
                await bot.unpin_chat_message(
                    GROUP_ID, bride_game_messages[session['session_id']]
                    ["pinned_message_id"])
            except Exception as e:
                logging.error(f"Ошибка открепления сообщения о наборе: {e}")

        await db.delete_bride_session(session['session_id'])

        # Очищаем глобальное хранилище
        if session['session_id'] in bride_game_messages:
            del bride_game_messages[session['session_id']]

        if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await message.answer("Набор в игру завершен.")
        else:
            await bot.send_message(GROUP_ID, "Набор в игру завершен.")
            await message.reply("Набор в игру завершен.")

        await state.clear()
        return

    # Проверяем активную игру
    active_game = await db.get_active_bride_game(GROUP_ID)
    if not active_game:
        await message.reply("Нет активной игры для завершения.")
        return

    if active_game['status'] not in ['waiting', 'started']:
        await message.reply("Игра уже завершена.")
        return

    # Открепляем все закрепленные сообщения игры
    try:
        await db.unpin_all_game_messages(active_game['game_id'])
    except Exception as e:
        logging.error(f"Ошибка открепления сообщений игры: {e}")

    # Завершаем игру
    await db.finish_bride_game(active_game['game_id'])

    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer("Игра принудительно завершена администратором.")
    else:
        await bot.send_message(
            GROUP_ID, "Игра принудительно завершена администратором.")
        await message.reply("Игра принудительно завершена администратором.")

    # Уведомляем всех участников
    participants = await db.get_bride_participants(active_game['game_id'])
    for participant in participants:
        try:
            await bot.send_message(participant['user_id'],
                                   "Игра была завершена администратором.")
        except Exception as e:
            logging.error(
                f"Ошибка уведомления участника {participant['user_id']}: {e}")

    # Очищаем статус-сообщения из БД и памяти
    rounds = await db.get_bride_rounds(active_game['game_id'])
    for round_data in rounds:
        round_id = round_data['round_id']
        # Удаляем из БД
        await db.delete_round_status_message(round_id)
        # Удаляем из памяти
        if round_id in bride_status_messages:
            del bride_status_messages[round_id]

    # Очищаем состояние
    await state.clear()


@dp.callback_query(F.data.startswith("bride_join_"))
async def bride_join_callback(callback: CallbackQuery, state: FSMContext):
    session_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id

    session = await db.get_active_bride_session()
    if not session or session["session_id"] != session_id:
        await callback.answer("Игра уже началась или завершена.",
                              show_alert=True)
        return

    # Получаем участников из базы данных
    participants_data = await db.get_bride_session_participants(session_id)
    participant_ids = [p['user_id'] for p in participants_data]

    if user_id in participant_ids:
        await callback.answer("Вы уже присоединились.", show_alert=True)
        return

    number = len(participant_ids)
    await db.add_bride_participant(session_id, user_id, number)
    participant_ids.append(user_id)

    # Обновляем глобальное хранилище если оно существует
    if session_id in bride_game_messages:
        bride_game_messages[session_id]["participants"] = participant_ids

    await bot.send_message(user_id, "Вы присоединились к игре.")

    # Обновляем сообщение в группе
    try:
        # Если есть информация о сообщении в памяти, используем её
        if session_id in bride_game_messages:
            await bot.edit_message_text(
                chat_id=bride_game_messages[session_id]["chat_id"],
                message_id=bride_game_messages[session_id]["message_id"],
                text=
                f"Идёт набор в игру \"Жених\"\nУчастников: {len(participant_ids)}",
                reply_markup=callback.message.reply_markup)
        else:
            # Иначе пытаемся обновить текущее сообщение
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=
                f"Идёт набор в игру \"Жених\"\nУчастников: {len(participant_ids)}",
                reply_markup=callback.message.reply_markup)
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения: {e}")

    await callback.answer()


@dp.message()
async def handle_admin_response(message: types.Message, state: FSMContext):
    try:
        # Игнорируем сообщения, которые уже обработаны другими хендлерами
        if not message.text:
            return

        # Проверяем подключение к БД
        if not db.pool:
            logging.error("Нет подключения к базе данных")
            return

        # Проверяем, не связано ли это с игрой Жених
        active_game = None
        try:
            active_game = await db.get_active_bride_game(GROUP_ID)
        except Exception as e:
            logging.error(f"Ошибка получения активной игры: {e}")
            return

        if active_game and active_game[
                'status'] == 'started' and message.chat.type == ChatType.PRIVATE:
            user_id = message.from_user.id

            # Проверяем, участвует ли пользователь в игре
            participants = await db.get_bride_participants(
                active_game['game_id'])
            user_participant = next(
                (p for p in participants if p['user_id'] == user_id), None)

            if user_participant:
                is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.is_bot
                
                # Проверяем, если это ответ на сообщение бота
                if is_reply_to_bot:
                    reply_text = message.reply_to_message.text or ""

                    # Если жених отвечает на запрос написать вопрос
                    if user_participant['is_bride'] and any(phrase in reply_text.lower() for phrase in [
                        "напишите первый вопрос", "отправьте следующий вопрос", 
                        "вы выбраны женихом", "никому не говорите свою роль"
                    ]):
                        # Обрабатываем как новый вопрос от жениха
                        await handle_bride_question(message, active_game, participants, user_participant)
                        return
                    # Если участник отвечает на вопрос
                    elif not user_participant['is_bride'] and any(phrase in reply_text.lower() for phrase in [
                        "вопрос от жениха", "отправьте свой ответ", "ожидайте вопрос от жениха"
                    ]):
                        # Обрабатываем как ответ на вопрос
                        await handle_participant_answer(message, active_game, participants, user_participant)
                        return
                    # Если жених отвечает на запрос выбрать участника
                    elif user_participant['is_bride'] and any(phrase in reply_text.lower() for phrase in [
                        "напишите число того участника", "выбрать кого исключить"
                    ]):
                        # Обрабатываем как выбор для исключения
                        await handle_bride_elimination_choice(message, active_game, participants, user_participant)
                        return
                # Если это жених - обрабатываем как вопрос или выбор
                if user_participant['is_bride']:
                    await handle_bride_question(message, active_game, participants, user_participant)
                    return

                # Если это не жених - обрабатываем как ответ
                elif not user_participant['is_bride']:
                    await handle_participant_answer(message, active_game, participants, user_participant)
                    return

        # Обрабатываем только приватные сообщения или админские команды
        if message.chat.type != ChatType.PRIVATE:
            return

        # Антиспам проверка для пользователей не из группы
        if message.from_user.id not in ADMIN_IDS:
            user_id = message.from_user.id
            if not await is_member(user_id) and not check_message_limit(
                    user_id):
                try:
                    await message.answer(
                        "Вы исчерпали лимит сообщений. Вступите в группу, чтобы продолжить общение с ботом. Если это баг, напишите <a href='https://t.me/alren15'>администратору</a>."
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки сообщения о лимите: {e}")
                return

        # Проверяем, не является ли это ответом пользователя на сообщение админа
        if (message.from_user.id not in ADMIN_IDS and message.reply_to_message
                and message.chat.type == ChatType.PRIVATE):

            reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""

            # Проверяем, что это ответ на сообщение от администратора
            if "Ответ администратора:" in reply_text:
                user = message.from_user
                user_id = user.id
                username = f" (@{user.username})" if user.username else ""

                # Отправляем ответ пользователя всем админам
                admin_notification = f'''↪️ ID: <code>{user_id}</code>
Ответ пользователя {user.full_name}{username}:

<b>{message.text}</b>'''

                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id,
                                               admin_notification,
                                               parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.error(
                            f"Ошибка отправки ответа пользователя админу {admin_id}: {e}"
                        )

                await message.reply("Ваш ответ отправлен администраторам.")
                return

        # Обрабатываем сообщения от пользователей не из группы (обратная связь)
        if (message.from_user.id not in ADMIN_IDS
                and message.chat.type == ChatType.PRIVATE
                and not message.reply_to_message
                and not await is_member(message.from_user.id)):

            # Это обратная связь от пользователя не из группы
            user = message.from_user
            user_id = user.id
            username = f" (@{user.username})" if user.username else ""

            # Отправляем сообщение всем админам
            admin_notification = f'''↪️ ID: <code>{user_id}</code>
Ответ пользователя {user.full_name}{username}:

<b>{message.text}</b>'''

            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id,
                                           admin_notification,
                                           parse_mode=ParseMode.HTML)
                except Exception as e:
                    logging.error(
                        f"Ошибка отправки сообщения пользователя админу {admin_id}: {e}"
                    )

            await message.reply("Ваше сообщение отправлено администраторам.")
            return

        # Логика обработки обычных сообщений (остается без изменений для других случаев)
        pass

    except Exception as e:
        logging.error(f"Ошибка в обработчике ответов: {str(e)}", exc_info=True)
        try:
            await message.reply("Произошла системная ошибка. Проверьте логи.")
        except Exception as reply_error:
            logging.error(
                f"Не удалось отправить сообщение об ошибке: {reply_error}")


async def send_status_message_to_creator(game_id: int, round_id: int):
    """Отправляет сообщение с статусом ответов создателю игры"""
    try:
        # Проверяем, есть ли уже сохраненное сообщение в БД
        existing_status = await db.get_round_status_message(round_id)
        if existing_status:
            # Обновляем существующее сообщение
            await update_status_message_for_creator(game_id, round_id)
            return

        # Получаем информацию об игре
        game = await db.get_bride_game(game_id)
        if not game:
            return

        creator_id = game['creator_id']

        # Получаем участников
        participants = await db.get_bride_participants(game_id)
        bride = next((p for p in participants if p['is_bride']), None)
        if not bride:
            return

        # Получаем информацию о женихе
        bride_user = await bot.get_chat(bride['user_id'])

        # Формируем начальное сообщение
        status_text = f"Жених {bride_user.full_name} - ответил\n"

        # Добавляем участников в случайном порядке
        active_participants = [
            p for p in participants if not p['is_bride'] and not p['is_out']
        ]
        # Перемешиваем список участников случайным образом
        random.shuffle(active_participants)

        for participant in active_participants:
            try:
                participant_user = await bot.get_chat(participant['user_id'])
                status_text += f"{participant_user.full_name} - не ответил\n"
            except Exception as e:
                logging.error(
                    f"Ошибка получения информации об участнике {participant['user_id']}: {e}"
                )
                status_text += f"Участник {participant['user_id']} - не ответил\n"

        # Отправляем сообщение создателю
        status_msg = await bot.send_message(creator_id, status_text.strip())

        # Сохраняем в БД и локальном хранилище
        await db.save_round_status_message(round_id, creator_id,
                                           status_msg.message_id)
        bride_status_messages[round_id] = {
            'creator_id': creator_id,
            'message_id': status_msg.message_id,
            'game_id': game_id
        }

    except Exception as e:
        logging.error(f"Ошибка отправки статус-сообщения создателю: {e}")


async def update_status_message_for_creator(game_id: int, round_id: int):
    """Обновляет сообщение с статусом ответов для создателя игры"""
    try:
        # Получаем информацию о статусном сообщении из БД
        status_info_db = await db.get_round_status_message(round_id)
        if not status_info_db:
            # Если в БД нет записи, проверяем локальное хранилище
            if round_id not in bride_status_messages:
                return
            status_info = bride_status_messages[round_id]
        else:
            # Используем данные из БД и обновляем локальное хранилище
            status_info = {
                'creator_id': status_info_db['creator_id'],
                'message_id': status_info_db['message_id'],
                'game_id': game_id
            }
            bride_status_messages[round_id] = status_info

        # Получаем участников и ответы
        participants = await db.get_bride_participants(game_id)
        answers = await db.get_bride_answers(round_id)
        answered_user_ids = {answer['user_id'] for answer in answers}

        bride = next((p for p in participants if p['is_bride']), None)
        if not bride:
            return

        # Получаем информацию о женихе
        bride_user = await bot.get_chat(bride['user_id'])

        # Формируем обновленное сообщение
        status_text = f"Жених {bride_user.full_name} - ответил\n"

        # Добавляем участников с их статусом в случайном порядке
        active_participants = [
            p for p in participants if not p['is_bride'] and not p['is_out']
        ]
        # Перемешиваем список участников случайным образом
        random.shuffle(active_participants)

        for participant in active_participants:
            try:
                participant_user = await bot.get_chat(participant['user_id'])
                status = "ответил" if participant[
                    'user_id'] in answered_user_ids else "не ответил"
                status_text += f"{participant_user.full_name} - {status}\n"
            except Exception as e:
                logging.error(
                    f"Ошибка получения информации об участнике {participant['user_id']}: {e}"
                )
                status = "ответил" if participant[
                    'user_id'] in answered_user_ids else "не ответил"
                status_text += f"Участник {participant['user_id']} - {status}\n"

        # Обновляем сообщение
        await bot.edit_message_text(chat_id=status_info['creator_id'],
                                    message_id=status_info['message_id'],
                                    text=status_text.strip())

    except Exception as e:
        logging.error(f"Ошибка обновления статус-сообщения: {e}")


async def main():
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Подключаемся к базе данных
            if not await db.connect():
                retry_count += 1
                if retry_count >= max_retries:
                    logging.error(
                        "Не удалось подключиться к базе данных после нескольких попыток. Остановка бота."
                    )
                    return
                logging.warning(
                    f"Попытка подключения к БД {retry_count}/{max_retries}")
                await asyncio.sleep(5)
                continue

            # Загружаем данные из БД
            await load_data_from_db()

            logging.info("Bot started")
            await dp.start_polling(
                bot,
                allowed_updates=["message", "chat_member", "callback_query"])
            break
        except Exception as e:
            retry_count += 1
            logging.error(
                f"Ошибка подключения (попытка {retry_count}/{max_retries}): {e}"
            )
            if retry_count >= max_retries:
                logging.error(
                    "Максимальное количество попыток подключения исчерпано")
                raise
            await asyncio.sleep(10)
        finally:
            # Закрываем соединение с БД при остановке
            try:
                await db.close()
            except Exception as e:
                logging.error(f"Ошибка закрытия БД: {e}")


if __name__ == "__main__":
    asyncio.run(main())
