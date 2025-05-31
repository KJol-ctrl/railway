import asyncpg
import json
import logging
import os
from typing import Dict, Optional, List

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
            
            self.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
            await self.create_tables()
            logging.info("Успешное подключение к базе данных")
            return True
        except Exception as e:
            logging.error(f"Ошибка подключения к базе данных: {e}")
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
                    quiz_id INTEGER PRIMARY KEY,
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
                    quiz_id INTEGER,
                    user_id BIGINT,
                    answer_index INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (quiz_id, user_id)
                );
            """)
            
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
                VALUES ($1, $2, $3, $4, $5, $6)
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
                VALUES ($1, $2, $3)
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

# Глобальный экземпляр базы данных
db = Database()

