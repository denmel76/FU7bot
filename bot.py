import asyncio
import logging
import random
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN, ADMIN_ID, YANDEX_API_KEY, YANDEX_FOLDER_ID, SYSTEM_PROMPT
from database import init_db, get_user, update_limit, verify_user, add_history, get_history, clear_history

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotStates(StatesGroup):
    waiting_for_captcha = State()
    chatting = State()

# --- ФУНКЦИЯ ЗАПРОСА К YANDEXGPT ---
async def ask_yandex_gpt(messages):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    yandex_messages = [{"role": "system", "text": SYSTEM_PROMPT}]
    for msg in messages:
        yandex_messages.append({"role": msg["role"], "text": msg["content"]})
        
    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {"stream": False, "temperature": 0.6, "maxTokens": 300},
        "messages": yandex_messages
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                return result['result']['alternatives'][0]['message']['text']
            else:
                logging.error(f"Yandex API Error: {await response.text()}")
                return "Мяу... У меня заклинило мозги (ошибка API)."

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    
    # Создаем меню с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Мой ID и лимит", callback_data="myid")],
        [InlineKeyboardButton(text="🧹 Очистить память", callback_data="rr")],
        [InlineKeyboardButton(text="🖼 Генерация картинок", callback_data="gen_info")]
    ])

    if user[1] == 0:
        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        await state.update_data(captcha_answer=num1 + num2)
        await message.answer(f"Ауууф! Напиши любое сообщение, или отправь медиа, путник.\n\n[Проверка, что вы не бот.]\nСколько будет {num1} + {num2}?")
        await state.set_state(BotStates.waiting_for_captcha)
    else:
        await message.answer("Мява! С возвращением, хозяин. Выбери действие в меню ниже или просто напиши сообщение.", reply_markup=keyboard)
        await state.set_state(BotStates.chatting)

# --- ОБРАБОТКА КАПЧИ ---
@dp.message(BotStates.waiting_for_captcha)
async def process_captcha(message: types.Message, state: FSMContext):
    data = await state.get_data()
    correct = data.get("captcha_answer")
    if message.text and message.text.isdigit() and int(message.text) == correct:
        await verify_user(message.from_user.id)
        await message.answer("Мява! Проверка пройдена. Теперь мы можем общаться~")
        await state.set_state(BotStates.chatting)
        
        # Показываем меню после капчи
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ℹ️ Мой ID и лимит", callback_data="myid")],
            [InlineKeyboardButton(text="🧹 Очистить память", callback_data="rr")],
            [InlineKeyboardButton(text="🖼 Генерация картинок", callback_data="gen_info")]
        ])
        await message.answer("Вот твое меню:", reply_markup=keyboard)
    else:
        await message.answer("Ой, неправильно. Попробуй еще раз: /start")

# --- ОБЩЕНИЕ С AI ---
@dp.message(BotStates.chatting, F.text)
async def chat_handler(message: types.Message):
    # Игнорируем команды, чтобы они не улетали в ИИ
    if message.text.startswith("/"): return

    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if user[0] <= 0 and user_id != ADMIN_ID:
        await message.answer("Мяу... У тебя закончились лимиты. Напиши /unlimit, чтобы сбросить (только для админа).")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    
    await add_history(user_id, "user", message.text)
    history = await get_history(user_id)
    
    ai_reply = await ask_yandex_gpt(history)
    
    await add_history(user_id, "assistant", ai_reply)
    if user_id != ADMIN_ID:
        await update_limit(user_id, -1)
    
    await message.answer(ai_reply)

# --- ОБРАБОТЧИКИ КНОПОК МЕНЮ ---
@dp.callback_query(F.data == "myid")
async def btn_myid(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    await callback.message.answer(f"Твой ID: {callback.from_user.id}\nОсталось сообщений: {user[0]}")
    await callback.answer()

@dp.callback_query(F.data == "rr")
async def btn_rr(callback: CallbackQuery):
    await clear_history(callback.from_user.id)
    await callback.message.answer("Память очищена! Забыла всё, о чём мы говорили.")
    await callback.answer()

@dp.callback_query(F.data == "gen_info")
async def btn_gen(callback: CallbackQuery):
    await callback.message.answer("Генерация картинок через YandexART находится в разработке. Скоро я научусь рисовать! 🎨")
    await callback.answer()

# --- ТЕКСТОВЫЕ КОМАНДЫ (Дублируют кнопки) ---
@dp.message(Command("rr"))
async def cmd_rr(message: types.Message):
    await clear_history(message.from_user.id)
    await message.answer("Память очищена!")

@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    user = await get_user(message.from_user.id)
    await message.answer(f"Твой ID: {message.from_user.id}\nОсталось сообщений: {user[0]}")

@dp.message(Command("unlimit"))
async def cmd_unlimit(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await update_limit(message.from_user.id, 9999)
        await message.answer("Лимиты сброшены (Админ).")
    else:
        await message.answer("У тебя нет прав на эту команду.")

async def main():
    await init_db()
    print("Yandex Roleplay Bot запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
