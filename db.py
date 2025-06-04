import asyncpg
import json
import logging
import os
from typing import Dict, Optional, List, Tuple

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Подключение к базе данных"""
        try:
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logging.error("DATABASE_URL не найден в переменных окружения")
                return False

            # Добавляем таймаут для подключения
            self.pool = await asyncpg.create_pool(
                database_url, 
                min_size=1, 
                max_size=10,
                command_timeout=30,
                server_settings={
                    'application_name': 'telegram_bot',
                }
            )

            # Проверяем подключение
            async with self.pool.acquire() as conn:
                await conn.fetchval('SELECT 1')

            await self.create_tables()
            logging.info("Успешное подключение к базе данных")
            return True
        except asyncpg.exceptions.InvalidCatalogNameError:
            logging.error("База данных не существует")
            return False
        except asyncpg.exceptions.InvalidPasswordError:
            logging.error("Неверный пароль для базы данных")
            return False
        except Exception as e:
            logging.error(f"Ошибка подключения к базе данных: {e}")
            if self.pool:
                try:
                    await self.pool.close()
                    self.pool = None
                except:
                    pass
            return False

    async def create_tables(self):
        """Создание необходимых таблиц"""
        async with self.pool.acquire() as conn:
            # Таблица для эмодзи пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_emojis (
                    user_id BIGINT PRIMARY KEY,
                    emoji TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Таблица для данных пользователей (роли, титулы)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_data (
                    user_id BIGINT PRIMARY KEY,
                    role TEXT,
                    custom_title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Таблица для активных викторин
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_quizzes (
                    quiz_id BIGINT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    question TEXT NOT NULL,
                    answers TEXT NOT NULL,
                    correct_indices TEXT NOT NULL,
                    creator_id BIGINT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Таблица для ответов участников викторин
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_participants (
                    quiz_id BIGINT,
                    user_id BIGINT,
                    answer_index INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (quiz_id, user_id)
                );
            """)

            # Таблица для истории пребывания в группе
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_group_history (
                    user_id BIGINT,
                    join_time TIMESTAMP NOT NULL,
                    leave_time TIMESTAMP,
                    PRIMARY KEY (user_id, join_time)
                );
            """)

            # Таблица для активных заявок
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_applications (
                    user_id BIGINT PRIMARY KEY,
                    role TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '5 days')
                );
            """)

            # Таблица для истории входов/выходов пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_join_history (
                    user_id BIGINT,
                    joined_at TIMESTAMP,
                    left_at TIMESTAMP
                );
            """)

            # Таблица для ожидающих заявок
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_applications (
                    user_id BIGINT PRIMARY KEY,
                    role TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Таблица для сессий игры Жених
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_game_sessions (
                    session_id SERIAL PRIMARY KEY,
                    creator_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started BOOLEAN DEFAULT FALSE
                );
            """)

            # Таблица для участников сессий игры Жених
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_game_participants (
                    session_id INT,
                    user_id BIGINT,
                    user_number INT,
                    eliminated BOOLEAN DEFAULT FALSE,
                    is_bride BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (session_id, user_id)
                );
            """)

            # Таблица для игр "Жених"
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_games (
                    game_id BIGSERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    creator_id BIGINT NOT NULL,
                    status TEXT NOT NULL,
                    current_round INTEGER DEFAULT 1,
                    bride_id BIGINT,
                    message_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Таблица участников игры "Жених"
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_participants (
                    game_id BIGINT REFERENCES bride_games(game_id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    number INTEGER,
                    is_out BOOLEAN DEFAULT FALSE,
                    is_bride BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (game_id, user_id)
                );
            """)

            # Таблица раундов игры "Жених"
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_rounds (
                    round_id BIGSERIAL PRIMARY KEY,
                    game_id BIGINT REFERENCES bride_games(game_id) ON DELETE CASCADE,
                    round_number INTEGER NOT NULL,
                    question TEXT,
                    voted_out BIGINT
                );
            """)
            
            # Обновляем тип поля voted_out если таблица уже существует
            try:
                await conn.execute("""
                    ALTER TABLE bride_rounds 
                    ALTER COLUMN voted_out TYPE BIGINT
                """)
            except Exception:
                # Игнорируем ошибку если поле уже BIGINT
                pass

            # Таблица ответов в игре "Жених"
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_answers (
                    round_id BIGINT REFERENCES bride_rounds(round_id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    answer TEXT NOT NULL,
                    PRIMARY KEY (round_id, user_id)
                );
            """)

            # Таблица для отслеживания кто уже был женихом
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bride_history (
                    user_id BIGINT NOT NULL,
                    was_bride_count INTEGER DEFAULT 0,
                    last_bride_game TIMESTAMP,
                    PRIMARY KEY (user_id)
                );
            """)
            
            # Обновляем существующие таблицы для совместимости
            try:
                await conn.execute("ALTER TABLE active_quizzes ALTER COLUMN quiz_id TYPE BIGINT")
                await conn.execute("ALTER TABLE quiz_participants ALTER COLUMN quiz_id TYPE BIGINT")
                await conn.execute("ALTER TABLE bride_games ALTER COLUMN game_id TYPE BIGINT")
                await conn.execute("ALTER TABLE bride_participants ALTER COLUMN game_id TYPE BIGINT")
                await conn.execute("ALTER TABLE bride_rounds ALTER COLUMN round_id TYPE BIGINT")
                await conn.execute("ALTER TABLE bride_rounds ALTER COLUMN game_id TYPE BIGINT")
                await conn.execute("ALTER TABLE bride_answers ALTER COLUMN round_id TYPE BIGINT")
            except Exception:
                # Игнорируем ошибки если типы уже правильные
                pass

            logging.info("Таблицы созданы успешно")

    async def close(self):
        """Закрытие соединения с базой данных"""
        if self.pool:
            await self.pool.close()

    # Методы для работы с эмодзи
    async def save_emoji(self, user_id: int, emoji: str):
        """Сохранение эмодзи пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_emojis (user_id, emoji)
                VALUES ($1, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET emoji = EXCLUDED.emoji;
            """, user_id, emoji)

    async def get_emoji(self, user_id: int) -> Optional[str]:
        """Получение эмодзи пользователя"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT emoji FROM user_emojis WHERE user_id = $1", 
                user_id
            )
            return result

    async def get_all_emojis(self) -> Dict[int, str]:
        """Получение всех эмодзи"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, emoji FROM user_emojis")
            return {row['user_id']: row['emoji'] for row in rows}

    async def remove_emoji(self, user_id: int):
        """Удаление эмодзи пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM user_emojis WHERE user_id = $1", user_id)

    async def get_used_emojis(self) -> List[str]:
        """Получение списка уже используемых эмодзи"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT emoji FROM user_emojis")
            return [row['emoji'] for row in rows]

    # Методы для работы с данными пользователей
    async def save_user_data(self, user_id: int, role: str = None, custom_title: str = None):
        """Сохранение данных пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_data (user_id, role, custom_title, updated_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    role = COALESCE(EXCLUDED.role, user_data.role),
                    custom_title = COALESCE(EXCLUDED.custom_title, user_data.custom_title),
                    updated_at = CURRENT_TIMESTAMP;
            """, user_id, role, custom_title)

    async def get_user_data(self, user_id: int) -> Dict:
        """Получение данных пользователя"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role, custom_title FROM user_data WHERE user_id = $1", 
                user_id
            )
            if row:
                return {'role': row['role'], 'custom_title': row['custom_title']}
            return {}

    async def get_all_user_data(self) -> Dict[int, Dict]:
        """Получение всех данных пользователей"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, role, custom_title FROM user_data")
            return {
                row['user_id']: {
                    'role': row['role'], 
                    'custom_title': row['custom_title']
                } 
                for row in rows
            }

    async def remove_user_data(self, user_id: int):
        """Удаление данных пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM user_data WHERE user_id = $1", user_id)

    # Методы для работы с викторинами
    async def save_quiz(self, quiz_id: int, chat_id: int, question: str, answers: List[str], 
                       correct_indices: List[int], creator_id: int):
        """Сохранение викторины"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO active_quizzes (quiz_id, chat_id, question, answers, correct_indices, creator_id)
                VALUES ($1::BIGINT, $2::BIGINT, $3, $4, $5, $6::BIGINT)
                ON CONFLICT (quiz_id) 
                DO UPDATE SET 
                    question = EXCLUDED.question,
                    answers = EXCLUDED.answers,
                    correct_indices = EXCLUDED.correct_indices,
                    active = TRUE;
            """, quiz_id, chat_id, question, json.dumps(answers), json.dumps(correct_indices), creator_id)

    async def get_quiz(self, quiz_id: int) -> Optional[Dict]:
        """Получение данных викторины"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM active_quizzes WHERE quiz_id = $1", 
                quiz_id
            )
            if row:
                return {
                    'quiz_id': row['quiz_id'],
                    'chat_id': row['chat_id'],
                    'question': row['question'],
                    'answers': json.loads(row['answers']),
                    'correct_indices': json.loads(row['correct_indices']),
                    'creator_id': row['creator_id'],
                    'active': row['active']
                }
            return None

    async def get_all_active_quizzes(self) -> Dict[int, Dict]:
        """Получение всех активных викторин"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM active_quizzes WHERE active = TRUE")
            return {
                row['quiz_id']: {
                    'quiz_id': row['quiz_id'],
                    'chat_id': row['chat_id'],
                    'question': row['question'],
                    'answers': json.loads(row['answers']),
                    'correct_indices': json.loads(row['correct_indices']),
                    'creator_id': row['creator_id'],
                    'active': row['active']
                }
                for row in rows
            }

    async def deactivate_quiz(self, quiz_id: int):
        """Деактивация викторины"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_quizzes SET active = FALSE WHERE quiz_id = $1", 
                quiz_id
            )

    async def delete_quiz(self, quiz_id: int):
        """Полное удаление викторины"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM quiz_participants WHERE quiz_id = $1", quiz_id)
            await conn.execute("DELETE FROM active_quizzes WHERE quiz_id = $1", quiz_id)

    # Методы для работы с участниками викторин
    async def save_quiz_answer(self, quiz_id: int, user_id: int, answer_index: int):
        """Сохранение ответа участника викторины"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO quiz_participants (quiz_id, user_id, answer_index)
                VALUES ($1::BIGINT, $2::BIGINT, $3)
                ON CONFLICT (quiz_id, user_id) 
                DO UPDATE SET answer_index = EXCLUDED.answer_index;
            """, quiz_id, user_id, answer_index)

    async def get_quiz_participants(self, quiz_id: int) -> Dict[int, int]:
        """Получение всех участников викторины и их ответов"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, answer_index FROM quiz_participants WHERE quiz_id = $1", 
                quiz_id
            )
            return {row['user_id']: row['answer_index'] for row in rows}

    # Методы для работы с историей пользователей
    async def record_user_join(self, user_id: int):
        """Запись вступления пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_group_history (user_id, join_time)
                VALUES ($1, CURRENT_TIMESTAMP)
            """, user_id)

    async def record_user_leave(self, user_id: int):
        """Запись выхода пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_group_history
                SET leave_time = CURRENT_TIMESTAMP
                WHERE user_id = $1 AND leave_time IS NULL
            """, user_id)

    async def get_user_history(self, user_id: int) -> List[Dict]:
        """Получение истории пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT join_time, leave_time
                FROM user_group_history
                WHERE user_id = $1
                ORDER BY join_time
            """, user_id)
            return [dict(row) for row in rows]

    # Методы для работы с игрой "Жених"
    async def create_bride_game(self, group_id: int, creator_id: int) -> int:
        """Создание новой игры Жених"""
        async with self.pool.acquire() as conn:
            game_id = await conn.fetchval("""
                INSERT INTO bride_games (group_id, creator_id, status)
                VALUES ($1::BIGINT, $2::BIGINT, 'waiting')
                RETURNING game_id
            """, group_id, creator_id)
            return game_id

    async def join_bride_game(self, game_id: int, user_id: int) -> bool:
        """Присоединение к игре Жених"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO bride_participants (game_id, user_id)
                    VALUES ($1, $2)
                """, game_id, user_id)
                return True
            except:
                return False

    async def get_bride_game(self, game_id: int) -> Optional[Dict]:
        """Получение данных игры Жених"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM bride_games WHERE game_id = $1
            """, game_id)
            return dict(row) if row else None

    async def get_active_bride_game(self, group_id: int) -> Optional[Dict]:
        """Получение активной игры Жених в группе"""
        if not self.pool:
            logging.error("Нет подключения к базе данных")
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM bride_games 
                WHERE group_id = $1 AND status IN ('waiting', 'started')
                ORDER BY created_at DESC LIMIT 1
            """, group_id)
            return dict(row) if row else None

    async def add_bride_game_participant(self, game_id: int, user_id: int, number: int = None, is_bride: bool = False):
        """Добавление участника в игру Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bride_participants (game_id, user_id, number, is_bride)
                VALUES ($1::BIGINT, $2::BIGINT, $3, $4)
            """, game_id, user_id, number, is_bride)

    async def get_bride_rounds(self, game_id: int) -> List[Dict]:
        """Получение всех раундов игры"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bride_rounds 
                WHERE game_id = $1
                ORDER BY round_number
            """, game_id)
            return [dict(row) for row in rows]

    async def get_bride_participants(self, game_id: int) -> List[Dict]:
        """Получение участников игры Жених"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bride_participants 
                WHERE game_id = $1
                ORDER BY user_id
            """, game_id)
            return [dict(row) for row in rows]

    async def start_bride_game(self, game_id: int, bride_id: int):
        """Запуск игры Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE bride_games 
                SET status = 'started', bride_id = $2::BIGINT
                WHERE game_id = $1
            """, game_id, bride_id)

            await conn.execute("""
                UPDATE bride_participants 
                SET is_bride = TRUE
                WHERE game_id = $1 AND user_id = $2::BIGINT
            """, game_id, bride_id)

    async def create_bride_round(self, game_id: int, round_number: int, question: str) -> int:
        """Создание раунда игры Жених"""
        async with self.pool.acquire() as conn:
            round_id = await conn.fetchval("""
                INSERT INTO bride_rounds (game_id, round_number, question)
                VALUES ($1::BIGINT, $2, $3)
                RETURNING round_id
            """, game_id, round_number, question)
            return round_id

    async def save_bride_answer(self, round_id: int, user_id: int, answer: str):
        """Сохранение ответа в игре Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bride_answers (round_id, user_id, answer)
                VALUES ($1::BIGINT, $2::BIGINT, $3)
                ON CONFLICT (round_id, user_id)
                DO UPDATE SET answer = EXCLUDED.answer
            """, round_id, user_id, answer)

    async def get_bride_answers(self, round_id: int) -> List[Dict]:
        """Получение ответов раунда"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ba.*, bp.number
                FROM bride_answers ba
                JOIN bride_participants bp ON ba.user_id = bp.user_id
                JOIN bride_rounds br ON ba.round_id = br.round_id
                WHERE ba.round_id = $1 AND bp.game_id = br.game_id
            """, round_id)
            return [dict(row) for row in rows]

    async def vote_out_participant(self, game_id: int, user_id: int, round_id: int):
        """Исключение участника из игры"""
        async with self.pool.acquire() as conn:
            # Преобразуем user_id в int, если он передается как строка
            user_id = int(user_id) if isinstance(user_id, str) else user_id
            
            await conn.execute("""
                UPDATE bride_participants 
                SET is_out = TRUE
                WHERE game_id = $1::BIGINT AND user_id = $2::BIGINT
            """, game_id, user_id)

            await conn.execute("""
                UPDATE bride_rounds 
                SET voted_out = $2::BIGINT
                WHERE round_id = $1::BIGINT
            """, round_id, user_id)

    async def finish_bride_game(self, game_id: int):
        """Завершение игры Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE bride_games 
                SET status = 'finished'
                WHERE game_id = $1
            """, game_id)

    async def get_current_bride_round(self, game_id: int) -> Optional[Dict]:
        """Получение текущего раунда игры"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM bride_rounds 
                WHERE game_id = $1
                ORDER BY round_number DESC LIMIT 1
            """, game_id)
            return dict(row) if row else None

    # Методы для работы с историей входов/выходов
    async def save_join_history(self, user_id: int, joined_at, left_at):
        """Сохранение истории входов/выходов пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_join_history (user_id, joined_at, left_at)
                VALUES ($1, $2, $3)
            """, user_id, joined_at, left_at)

    async def get_user_join_periods(self, user_id: int) -> List[Tuple[str, str]]:
        """Получение периодов пребывания пользователя в группе"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT joined_at, left_at FROM user_join_history
                WHERE user_id = $1
                ORDER BY joined_at ASC
            """, user_id)
            result = []
            for r in rows:
                if r['joined_at'] and r['left_at']:
                    start = r['joined_at'].strftime('%d.%m.%y')
                    end = r['left_at'].strftime('%d.%m.%y')
                    result.append((start, end))
            return result

    # Методы для работы с ожидающими заявками
    async def save_pending_application(self, user_id: int, role: str):
        """Сохранение ожидающей заявки"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO pending_applications (user_id, role)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role, submitted_at = CURRENT_TIMESTAMP
            """, user_id, role)

    async def delete_old_applications(self):
        """Удаление старых заявок (старше 5 дней)"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM pending_applications WHERE submitted_at < NOW() - INTERVAL '5 days'
            """)

    async def get_application_role(self, user_id: int) -> Optional[str]:
        """Получение роли из ожидающей заявки"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT role FROM pending_applications WHERE user_id = $1", user_id)

    async def update_user_role(self, user_id: int, new_role: str):
        """Обновление роли пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_data SET role = $2, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = $1
            """, user_id, new_role)

    # Методы для работы с сессиями игры Жених
    async def create_bride_session(self, creator_id: int) -> int:
        """Создание новой сессии игры Жених"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO bride_game_sessions (creator_id) VALUES ($1) RETURNING session_id
            """, creator_id)

    async def add_bride_participant(self, session_id: int, user_id: int, number: int, is_bride: bool = False):
        """Добавление участника в сессию игры Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bride_game_participants (session_id, user_id, user_number, is_bride)
                VALUES ($1, $2::BIGINT, $3, $4)
            """, session_id, user_id, number, is_bride)

    async def get_bride_session_participants(self, session_id: int) -> List[Dict]:
        """Получение участников сессии игры Жених"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, user_number, eliminated, is_bride
                FROM bride_game_participants WHERE session_id = $1
            """, session_id)
            return [dict(row) for row in rows]

    async def eliminate_bride_participant(self, session_id: int, user_number: int):
        """Исключение участника из игры Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE bride_game_participants
                SET eliminated = TRUE
                WHERE session_id = $1 AND user_number = $2
            """, session_id, user_number)

    async def delete_bride_session(self, session_id: int):
        """Удаление сессии игры Жених"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM bride_game_participants WHERE session_id = $1", session_id)
            await conn.execute("DELETE FROM bride_game_sessions WHERE session_id = $1", session_id)

    async def start_bride_session(self, session_id: int):
        """Запускает сессию игры жених"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE bride_game_sessions 
                    SET started = TRUE
                    WHERE session_id = $1
                """, session_id)
                logging.info(f"Сессия {session_id} запущена")
        except Exception as e:
            logging.error(f"Ошибка при запуске сессии {session_id}: {e}")
            raise
    async def get_active_bride_session(self) -> Optional[Dict]:
        """Получение активной сессии игры Жених"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM bride_game_sessions WHERE started = FALSE LIMIT 1")
            return dict(row) if row else None

    # Методы для работы с заявками
    async def save_application(self, user_id: int, role: str):
        """Сохранение заявки пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO active_applications (user_id, role)
                VALUES ($1::BIGINT, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET role = EXCLUDED.role, 
                             created_at = CURRENT_TIMESTAMP,
                             expires_at = CURRENT_TIMESTAMP + INTERVAL '5 days'
            """, user_id, role)

    async def get_application(self, user_id: int) -> Optional[Dict]:
        """Получение заявки пользователя"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM active_applications 
                WHERE user_id = $1::BIGINT AND expires_at > CURRENT_TIMESTAMP
            """, user_id)
            return dict(row) if row else None

    async def update_application_role(self, user_id: int, new_role: str):
        """Обновление роли в заявке"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE active_applications 
                SET role = $2
                WHERE user_id = $1::BIGINT
            """, user_id, new_role)

    async def delete_application(self, user_id: int):
        """Удаление заявки"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM active_applications WHERE user_id = $1::BIGINT
            """, user_id)

    async def cleanup_expired_applications(self):
        """Очистка истекших заявок"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM active_applications 
                WHERE expires_at <= CURRENT_TIMESTAMP
            """)

    async def save_application_internal(self, user_id: int, role: str):
        """Внутренний метод сохранения заявки"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO active_applications (user_id, role)
                VALUES ($1::BIGINT, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET role = EXCLUDED.role, 
                             created_at = CURRENT_TIMESTAMP,
                             expires_at = CURRENT_TIMESTAMP + INTERVAL '5 days'
            """, user_id, role)

    async def get_bride_history(self, user_id: int) -> Optional[Dict]:
        """Получение истории пользователя как жениха"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM bride_history WHERE user_id = $1::BIGINT
            """, user_id)
            return dict(row) if row else None

    async def update_bride_history(self, user_id: int):
        """Обновление информации о том, что пользователь был женихом"""
        async with self.pool.acquire() as conn:
            existing_history = await self.get_bride_history(user_id)
            if existing_history:
                await conn.execute("""
                    UPDATE bride_history
                    SET was_bride_count = was_bride_count + 1,
                        last_bride_game = CURRENT_TIMESTAMP
                    WHERE user_id = $1::BIGINT
                """, user_id)
            else:
                await conn.execute("""
                    INSERT INTO bride_history (user_id, was_bride_count, last_bride_game)
                    VALUES ($1::BIGINT, 1, CURRENT_TIMESTAMP)
                """, user_id)

    async def can_be_bride(self, user_id: int) -> bool:
        """Проверка, может ли пользователь быть женихом"""
        history = await self.get_bride_history(user_id)
        if history:
            # Пользователь уже был женихом, проверяем условие
            return history['was_bride_count'] <= 1
        else:
            # Пользователь еще не был женихом
            return True

    async def get_eligible_bride_candidates(self, participants_ids: list) -> list:
        """Получение списка подходящих кандидатов в женихи"""
        eligible = []
        for user_id in participants_ids:
            if await self.can_be_bride(user_id):
                eligible.append(user_id)
        
        # Если все уже были женихами, возвращаем всех участников
        if not eligible:
            # Сбрасываем счетчики для всех участников
            for user_id in participants_ids:
                await self.reset_bride_status(user_id)
            eligible = participants_ids
        
        return eligible

    async def mark_as_bride(self, user_id: int):
        """Отмечает пользователя как бывшего жениха"""
        await self.update_bride_history(user_id)

    async def reset_bride_status(self, user_id: int):
        """Сбрасывает статус жениха для пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE bride_history
                SET was_bride_count = 0
                WHERE user_id = $1::BIGINT
            """, user_id)

    async def get_eligible_bride_candidates(self, participants_ids: list) -> list:
        """Получение списка подходящих кандидатов в женихи"""
        eligible = []
        for user_id in participants_ids:
            if await self.can_be_bride(user_id):
                eligible.append(user_id)
        
        # Если все уже были женихами, возвращаем всех участников
        if not eligible:
            # Сбрасываем счетчики для всех участников
            for user_id in participants_ids:
                await self.reset_bride_status(user_id)
            eligible = participants_ids
        
        return eligible

    async def mark_as_bride(self, user_id: int):
        """Отмечает пользователя как бывшего жениха"""
        await self.update_bride_history(user_id)

# Глобальный экземпляр базы данных
db = Database()