import logging
import json
import os
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

# Бібліотека для виконання завдань за розкладом
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()  # Зчитує файл .env
# Токен вашого бота та ваш Admin ID
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = 418357645 

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

DATA_FILE = 'data_today.json'
USERS_FILE = 'subscribers.json'

# --- ФУНКЦІЇ ЗБЕРЕЖЕННЯ ТА ЗАВАНТАЖЕННЯ ДАНИХ ---

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {} if filename == DATA_FILE else []

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data_today = load_json(DATA_FILE)
subscribers = load_json(USERS_FILE)

class Form(StatesGroup):
    waiting_for_count = State()

# Ваш список класів
CLASSES = ["1 клас","2 клас","3 клас","4 клас","5 клас", "6 клас", "7 клас", "8 клас", "9 клас"]

# Генерація Inline-кнопок з галочками ✅ для вже зданих класів
def get_classes_inline_keyboard():
    buttons = []
    row = []
    for cls in CLASSES:
        status = " ✅" if cls in data_today else ""
        text = f"{cls}{status}"
        callback_data = f"select_class:{cls}"
        
        row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
        if len(row) == 2:  # По 2 кнопки в ряд для зручності
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# -------------------------------------------------------------
# АВТОМАТИЧНІ ЗАВДАННЯ ЗА РОЗКЛАДОМ (APSCHEDULER)
# -------------------------------------------------------------

# 1. Автоматичне нагадування старостам о 08:30 (Пн-Пт)
async def send_reminder_to_captains():
    if not subscribers:
        return

    text = (
        "⏰ <b>Доброго ранку! Час подати дані на обід.</b>\n\n"
        "Будь ласка, оберіть свій клас нижче та введіть кількість дітей на сьогодні:"
    )
    
    for user_id in subscribers:
        try:
            await bot.send_message(
                user_id, 
                text, 
                reply_markup=get_classes_inline_keyboard(), 
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не вдалося надіслати нагадування {user_id}: {e}")

# 2. Автоматичний підсумковий звіт (1-4 класи та 5-9 класи) о 09:10
async def send_daily_report():
    if not data_today:
        await bot.send_message(ADMIN_ID, "⚠️ <b>09:10 — Жоден клас ще не подав дані на обід!</b>", parse_mode="HTML")
        return

    # Списки для поділу класів
    junior_classes = ["1 клас", "2 клас", "3 клас", "4 клас"]
    senior_classes = ["5 клас", "6 клас", "7 клас", "8 клас", "9 клас"]

    total_junior = 0
    total_senior = 0
    
    text_junior = "🎒 <b>Молодша школа (1-4 класи):</b>\n"
    text_senior = "🎓 <b>Старша школа (5-9 класи):</b>\n"

    # Сортуємо та розділяємо дані
    for cls, count in sorted(data_today.items()):
        if cls in junior_classes:
            text_junior += f"• <b>{cls}</b>: {count} дітей\n"
            total_junior += count
        elif cls in senior_classes:
            text_senior += f"• <b>{cls}</b>: {count} дітей\n"
            total_senior += count

    # Перевірка класів, які НЕ подали дані
    missing_classes = [cls for cls in CLASSES if cls not in data_today]

    # Формуємо фінальний текст
    text = "📊 <b>Ранковий звіт по харчуванню (09:10)</b>\n\n"
    
    # Молодші
    if total_junior > 0:
        text += text_junior + f"<b>Всього (1-4 класи): {total_junior} порцій</b>\n\n"
    else:
        text += "🎒 <b>Молодша школа (1-4 класи):</b>\n<i>Дані відсутні</i>\n\n"

    # Старші
    if total_senior > 0:
        text += text_senior + f"<b>Всього (5-9 класи): {total_senior} порцій</b>\n\n"
    else:
        text += "🎓 <b>Старша школа (5-9 класи):</b>\n<i>Дані відсутні</i>\n\n"

    # Загальний підсумок та пропущені класи
    if missing_classes:
        text += f"⚠️ <b>Не подали дані:</b> {', '.join(missing_classes)}\n\n"

    grand_total = total_junior + total_senior
    text += f"👉 <b>ЗАГАЛОМ НА ШКОЛУ: {grand_total} порцій</b>"

    await bot.send_message(ADMIN_ID, text, parse_mode="HTML")

# 3. Автоматичне очищення даних о 00:00
async def reset_daily_data():
    global data_today
    data_today.clear()
    save_json(DATA_FILE, data_today)
    await bot.send_message(ADMIN_ID, "♻️ <i>Дані харчування автоматично скинуто на новий день.</i>", parse_mode="HTML")

# -------------------------------------------------------------
# ОБРОБНИКИ ПОВІДОМЛЕНЬ ТА КОМАНД
# -------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Зберігаємо Telegram ID користувача для ранкових нагадувань
    user_id = message.from_user.id
    if user_id not in subscribers:
        subscribers.append(user_id)
        save_json(USERS_FILE, subscribers)

    await message.answer(
        "Вітаю! Оберіть свій клас із списку нижче:",
        reply_markup=get_classes_inline_keyboard()
    )

@dp.callback_query(F.data.startswith("select_class:"))
async def process_class_callback(callback: types.CallbackQuery, state: FSMContext):
    selected_class = callback.data.split(":")[1]
    
    await state.update_data(selected_class=selected_class)
    await callback.message.edit_text(
        f"Ви обрали <b>{selected_class}</b>.\nТепер введіть кількість дітей на обід (лише число):",
        parse_mode="HTML"
    )
    await state.set_state(Form.waiting_for_count)
    await callback.answer()

@dp.message(Form.waiting_for_count)
async def process_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Будь ласка, введіть число цифрами (наприклад: 18):")
        return

    count = int(message.text)
    user_data = await state.get_data()
    selected_class = user_data['selected_class']

    # Зберігаємо дані у словник та у JSON-файл
    data_today[selected_class] = count
    save_json(DATA_FILE, data_today)
    
    await message.answer(f"✅ Успішно збережено: <b>{selected_class}</b> — {count} дітей.", parse_mode="HTML")
    await state.clear()

# Ручний виклик підсумків для вас у будь-який момент
@dp.message(Command("total"))
async def cmd_total(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Ця команда доступна лише адміністратору.")
        return
    await send_daily_report()

# Ручне скидання даних (якщо потрібно)
@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await reset_daily_data()

# -------------------------------------------------------------
# ЗАПУСК БОТА ТА ТАЙМЕРІВ
# -------------------------------------------------------------


async def handle(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    asyncio.create_task(start_web_server())
    # Нагадування старостам о 08:30 з понеділка по п'ятницю
    scheduler.add_job(send_reminder_to_captains, 'cron', hour=9, minute=00, day_of_week='mon-fri')

    # Звіт для вас о 09:00 з понеділка по п'ятницю
    scheduler.add_job(send_daily_report, 'cron', hour=9, minute=10, day_of_week='mon-fri')

    # Скидання даних о 00:00 щоночі
    scheduler.add_job(reset_daily_data, 'cron', hour=0, minute=0)

    scheduler.start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
