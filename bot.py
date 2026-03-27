import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile

# Загружаем переменные окружения ДО импорта остальных модулей
load_dotenv()

from gemini_service import get_top_ids, get_expert_analysis, calculate_cost, get_model_info
from database import init_db, log_message, get_db_path
from data_loader import GEMINI_MODELS

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher()

# Глобальные переменные
ADMIN_ID = str(os.getenv("ADMIN_ID", ""))
CURRENT_STYLE = "telegram_yur"
SELECTED_MODEL = "gemini-3.1-pro-preview"

def get_models_keyboard():
    keyboard = []
    # Создаем кнопки по 2 в ряд
    row = []
    for model in GEMINI_MODELS:
        row.append(KeyboardButton(text=f"Модель: {model['model_name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
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
    
    ans_text = "Здравствуйте! Я ИИ-юрист эксперт в области военного права.\nВыберите модель для анализа запроса, а затем задайте свой вопрос."
    await message.answer(ans_text, reply_markup=get_models_keyboard())
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

@dp.message(F.text.startswith("Модель: "))
async def select_model(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    global SELECTED_MODEL
    
    model_name = message.text.replace("Модель: ", "").strip()
    model_info = get_model_info(model_name)
    
    if model_info:
        SELECTED_MODEL = model_name
        ans = f"✅ Модель успешно применена: <b>{model_name}</b>\n\n"
        ans += f"🔹 Макс. контекст на вход: {model_info['max_input_tokens']} токенов\n"
        ans += f"🔹 Макс. контекст на выход: {model_info['max_output_tokens']} токенов\n"
        ans += f"🔹 Цена 1 млн токенов (вход): ${model_info['price_per_1m_input']}\n"
        ans += f"🔹 Цена 1 млн токенов (выход): ${model_info['price_per_1m_output']}\n\n"
        ans += "Теперь вы можете задать свой юридический вопрос."
        await message.answer(ans, parse_mode=ParseMode.HTML)
    else:
        ans = "❌ Неизвестная модель."
        await message.answer(ans)
    
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message()
async def handle_user_query(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    question = message.text
    
    status_text = f"⏳ Анализирую вопрос с помощью модели {SELECTED_MODEL} и ищу подходящие статьи..."
    status_msg = await message.answer(status_text)
    log_message(message.from_user.id, message.from_user.username, "out", status_text)
    
    try:
        # Шаг 1: Ищем статьи (выбранная модель)
        top_articles, _, in_tokens_1, out_tokens_1 = await get_top_ids(question, SELECTED_MODEL)
        
        if not top_articles:
            err_text = "❌ Не удалось определить подходящие статьи для вашего запроса."
            await status_msg.edit_text(err_text)
            log_message(message.from_user.id, message.from_user.username, "out", err_text)
            return
            
        # Формируем ответ по первому этапу
        in_cost_1, out_cost_1 = calculate_cost(in_tokens_1, out_tokens_1, SELECTED_MODEL)
        articles_list_str = "\n".join([f"Статья {a['number']} - {a['percent']}%" for a in top_articles])
        
        step1_text = f"✅ <b>Найденные статьи (ТОП-10):</b>\n{articles_list_str}\n\n"
        step1_text += f"📊 <b>Статистика 1 этапа ({SELECTED_MODEL}):</b>\n"
        step1_text += f"Входные токены: {in_tokens_1} (${in_cost_1:.6f})\n"
        step1_text += f"Выходные токены: {out_tokens_1} (${out_cost_1:.6f})\n\n"
        step1_text += "⏳ Формирую экспертное заключение (это займет немного времени)..."
        
        await status_msg.edit_text(step1_text, parse_mode=ParseMode.HTML)
        log_message(message.from_user.id, message.from_user.username, "out", step1_text)
        
        # Шаг 2: Получаем финальный ответ (всегда gemini-3.1-pro-preview)
        expert_answer, _, in_tokens_2, out_tokens_2 = await get_expert_analysis(question, top_articles, style=CURRENT_STYLE)
        
        # Формируем итоговую статистику для второго шага
        in_cost_2, out_cost_2 = calculate_cost(in_tokens_2, out_tokens_2, "gemini-3.1-pro-preview")
        
        stat_text = f"\n\n---\n📊 <b>Статистика 2 этапа (gemini-3.1-pro-preview):</b>\n"
        stat_text += f"Входные токены: {in_tokens_2} (${in_cost_2:.6f})\n"
        stat_text += f"Выходные токены: {out_tokens_2} (${out_cost_2:.6f})\n"
        
        final_answer = expert_answer + stat_text
        
        # Отправляем ответ (внутри функции есть логирование)
        await send_long_message(message, final_answer)
        
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
