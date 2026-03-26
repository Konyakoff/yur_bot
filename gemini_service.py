import google.generativeai as genai
import json
import re
import os
from data_loader import CATEGORIES_TEXT, JSON_DB
from styles import STYLES

# Настройка API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-3.1-pro-preview')

async def get_top_ids(question: str) -> list:
    """Шаг 1: Получаем ТОП-5 статей и возвращаем ТОП-3 ID."""
    prompt = f"""
Ты — медицинский эксперт военно-врачебной комиссии.
Ниже представлен строгий список рубрик "Расписания болезней":
{CATEGORIES_TEXT}

Симптомы/Вопрос пользователя: "{question}"

ЗАДАЧА:
1. Проанализируй вопрос пользователя.
2. Выбери ТОП-5 наиболее подходящих статей из предоставленного списка.
3. Оцени в процентах вероятность того, что случай пользователя относится к данной статье. Сортировка строго по убыванию.

Ожидаемый формат JSON:
[
  {{"id": "PP565_RaspBolezney_StX", "percent": 95, "title": "Название группы"}}
]
"""
    response = await model.generate_content_async(
        prompt,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )
    )
    
    # Очистка и парсинг JSON
    raw_response = re.sub(r'^```json\s*', '', response.text.strip())
    raw_response = re.sub(r'\s*```$', '', raw_response)
    data = json.loads(raw_response)
    
    # Извлекаем ТОП-3 ID
    top3_ids = [item.get("id") for item in data[:3] if item.get("id")]
    return top3_ids

async def get_expert_analysis(question: str, top3_ids: list, style: str = "standart") -> str:
    """Шаг 2: Собираем контекст и получаем экспертный ответ."""
    contexts = []
    found_ids = set()
    
    for item_id in top3_ids:
        if item_id in JSON_DB:
            found_ids.add(item_id)
            contexts.append(f"--- RAG Контекст для {item_id} ---\n{JSON_DB[item_id]}")
            
    if not contexts:
        return "К сожалению, не удалось найти юридический контекст (rag_context) для выбранных статей."
        
    combined_context = "\n\n".join(contexts)
    
    system_prompt = STYLES.get(style, STYLES["standart"])
    
    prompt = f"""{system_prompt}

Вопрос пользователя: "{question}"

Юридический контекст для анализа:
{combined_context}
"""
    response = await model.generate_content_async(prompt)
    
    usage = response.usage_metadata
    token_info = f"\n\n---\n*Статистика ИИ:* Входные: {usage.prompt_token_count} | Выходные: {usage.candidates_token_count} | Всего: {usage.total_token_count}"
    
    return response.text + token_info