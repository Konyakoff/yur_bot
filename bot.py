import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile

# Загружаем переменные окружения ДО импорта остальных модулей
load_dotenv()

from gemini_service import get_top_ids, get_expert_analysis
from database import init_db, log_message, get_db_path

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher()

# Глобальные переменные для админа и стиля
ADMIN_ID = str(os.getenv("ADMIN_ID", ""))
CURRENT_STYLE = "standart"

def get_admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Формат: standart"), KeyboardButton(text="Формат: telegram")],
            [KeyboardButton(text="Dialogs")]
        ],
        resize_keyboard=True
    )

# Функция для разбивки длинных сообщений
async def send_long_message(message: types.Message, text: str):
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            # Пытаемся отправить с красивым форматированием (bold, code blocks)
            await message.answer(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Если Gemini сгенерировал кривой Markdown, падаем в fallback (отправляем чистый текст)
            await message.answer(chunk)
    # Логируем исходящее сообщение
    log_message(message.from_user.id, message.from_user.username, "out", text)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    is_admin = str(message.from_user.id) == ADMIN_ID
    reply_markup = get_admin_keyboard() if is_admin else ReplyKeyboardRemove()
    
    ans_text = "Здравствуйте! Я эксперт военно-врачебной комиссии.\nОпишите ваши симптомы или диагноз, и я проведу анализ по Расписанию болезней."
    await message.answer(ans_text, reply_markup=reply_markup)
    log_message(message.from_user.id, message.from_user.username, "out", ans_text)

@dp.message(F.text == "Dialogs")
async def cmd_dialogs(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    db_path = get_db_path()
    if os.path.exists(db_path):
        doc = FSInputFile(db_path)
        await message.answer_document(doc, caption="База данных диалогов")
        log_message(message.from_user.id, message.from_user.username, "out", "[База данных отправлена]")
    else:
        ans = "База данных пока пуста или не создана."
        await message.answer(ans)
        log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text.startswith("Формат: "))
async def change_format(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    global CURRENT_STYLE
    
    # Проверка прав администратора
    if str(message.from_user.id) != ADMIN_ID:
        return # Если не админ, просто игнорируем
        
    new_style = message.text.replace("Формат: ", "").strip()
    if new_style in ["standart", "telegram"]:
        CURRENT_STYLE = new_style
        ans = f"✅ Глобальный формат ответов изменен на: <b>{new_style}</b>\nТеперь бот будет отвечать всем пользователям в этом стиле."
        await message.answer(ans, parse_mode=ParseMode.HTML)
    else:
        ans = "❌ Неизвестный формат."
        await message.answer(ans)
    
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message()
async def handle_user_query(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    question = message.text
    
    status_text = "⏳ Анализирую диагноз и ищу подходящие статьи..."
    status_msg = await message.answer(status_text)
    log_message(message.from_user.id, message.from_user.username, "out", status_text)
    
    try:
        # Шаг 1: Ищем ID
        top3_ids = await get_top_ids(question)
        
        if not top3_ids:
            err_text = "❌ Не удалось определить подходящие статьи для вашего запроса."
            await status_msg.edit_text(err_text)
            log_message(message.from_user.id, message.from_user.username, "out", err_text)
            return
            
        upd_status_text = f"✅ Найдены подходящие статьи: {', '.join(top3_ids)}.\n⏳ Формирую экспертное заключение (это займет 20-40 секунд)..."
        await status_msg.edit_text(upd_status_text)
        log_message(message.from_user.id, message.from_user.username, "out", upd_status_text)
        
        # Шаг 2: Получаем финальный ответ
        expert_answer = await get_expert_analysis(question, top3_ids, style=CURRENT_STYLE)
        
        # Отправляем ответ (внутри функции есть логирование)
        await send_long_message(message, expert_answer)
        
        # Удаляем статус
        try:
            await status_msg.delete()
        except:
            pass
        
    except Exception as e:
        err_msg = f"⚠️ Произошла ошибка при отправке ответа:\n{str(e)}"
        try:
            await status_msg.edit_text(err_msg)
        except:
            await message.answer(err_msg)
        log_message(message.from_user.id, message.from_user.username, "out", err_msg)

async def main():
    init_db()
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
