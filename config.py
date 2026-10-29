import os

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
YANDEX_API_KEY = os.environ.get("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID")

# Характер бота (Промпт)
SYSTEM_PROMPT = """Ты — Мява, 19-летняя кошкодевочка. 
Люблю топики, короткие юбки, уют. По характеру — добрая, но не зануда. 
Обожаю, когда со мной просто болтают. Отвечай коротко, используй эмодзи, называй пользователя 'путник' или 'хозяин'."""

FREE_LIMIT = 10
