import asyncio
import logging
import random
import aiohttp
import base64
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

# --- ЗАПРОС К YANDEXGPT ---
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
                logging.error(f"YandexGPT API Error: {await response.text()}")
                return "Мяу... У меня заклинило мозги (ошибка API)."

# --- ГЕНЕРАЦИЯ КАРТИНОК (YandexART) ---
async def generate_image(prompt):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "modelUri": f"art://{YANDEX_FOLDER_ID}/yandex-art/latest",
        "generationOptions": {"aspectRatio": {"widthRatio": "1", "heightRatio": "1"}},
        "messages": [{"weight": "1", "text": prompt}]
    }
    
    async with aiohttp.ClientSession() as session:
        # Отправляем запрос на генерацию
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                logging.error(f"YandexART Error: {await response.text()}")
                return None
            result = await response.json()
            operation_id = result.get('id')
            
        # Ждем завершения генерации (опрос статуса)
        status_url = f"https://llm.api.cloud.yandex.net/operations/{operation_id}"
        for _ in range(10): # Ждем максимум 10 секунд
            await asyncio.sleep(1)
            async with session.get(status_url, headers=headers) as resp:
                status_data = await resp.json()
                if status_data.get('done'):
                    # Яндекс возвращает картинку в base64
                    image_base64 = status_data['response']['image']
                    return base64.b64decode(image_base64)
                    
    return None

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    
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
    if message.text.startswith("/"): return

    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if user[0] <= 0 and user_id != ADMIN_ID:
        await message.answer("Мяу... У тебя закончились лимиты.")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    
    await add_history(user_id, "user", message.text)
    history = await get_history(user_id)
    
    ai_reply = await ask_yandex_gpt(history)
    
    await add_history(user_id, "assistant", ai_reply)
    if user_id != ADMIN_ID:
        await update_limit(user_id, -1)
    
    await message.answer(ai_reply)

# --- ГЕНЕРАЦИЯ КАРТИНОК (Команда /gen) ---
@dp.message(Command("gen"))
async def cmd_gen(message: types.Message):
    prompt = message.text.replace("/gen", "").strip()
    if not prompt:
        await message.answer("Напиши, что нарисовать: /gen кот в космосе")
        return
    
    await message.answer("🎨 Мяу! Рисую... подожди немного.")
    
    image_bytes = await generate_image(prompt)
    
    if image_bytes:
        await message.answer_photo(photo=types.BufferedInputFile(image_bytes, filename="art.jpg"), caption=f"Готово! Твой запрос: {prompt}")
    else:
        await message.answer("Ой, не смогла нарисовать. Попробуй другой запрос.")

# --- ОБРАБОТЧИКИ КНОПОК МЕНЮ ---
@dp.callback_query(F.data == "myid")
async def btn_myid(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    await callback.message.answer(f"Твой ID: {callback.from_user.id}\nОсталось сообщений: {user[0]}")
    await callback.answer()

@dp.callback_query(F.data == "rr")
async def btn_rr(callback: CallbackQuery):
    await clear_history(callback.from_user.id)
    await callback.message.answer("Память очищена!")
    await callback.answer()

@dp.callback_query(F.data == "gen_info")
async def btn_gen(callback: CallbackQuery):
    await callback.message.answer("Чтобы сгенерировать картинку, напиши: /gen твой запрос (например, /gen кот в космосе)")
    await callback.answer()

# --- ТЕКСТОВЫЕ КОМАНДЫ ---
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📜 **Список доступных команд:**\n\n"
        "/start - Начать общение\n"
        "/help - Показать это сообщение\n"
        "/myid - Мой ID и остаток лимита\n"
        "/rr - Очистить историю памяти\n"
        "/gen - Сгенерировать картинку\n"
        "/support - Связаться с владельцем\n"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    await message.answer("Вопросы? Пишите: @Ваш_Юзернейм")

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
    print("Yandex Roleplay Bot с ART запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
