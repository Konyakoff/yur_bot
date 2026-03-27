import google.generativeai as genai
import json
import re
import os
from data_loader import JSON_DB, GEMINI_MODELS
from styles import STYLES

# Настройка API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Путь к файлу закона
LAW_FILE_PATH = os.path.join("data", "1. Статьи 1 - 35.5. Федеральный закон от 28.03.98 N 53-ФЗ О воинской обязанности и военной службе.rtf")

def get_model_info(model_name: str) -> dict:
    for m in GEMINI_MODELS:
        if m["model_name"] == model_name:
            return m
    return None

def calculate_cost(input_tokens: int, output_tokens: int, model_name: str) -> tuple:
    info = get_model_info(model_name)
    if not info:
        return 0.0, 0.0
    
    input_cost = (input_tokens / 1_000_000) * info["price_per_1m_input"]
    output_cost = (output_tokens / 1_000_000) * info["price_per_1m_output"]
    return input_cost, output_cost

async def get_top_ids(question: str, selected_model: str) -> tuple:
    """Шаг 1: Получаем ТОП-10 статей закона."""
    model = genai.GenerativeModel(selected_model)
    
    # Загружаем файл через File API
    try:
        sample_file = genai.upload_file(path=LAW_FILE_PATH, display_name="53-FZ_Law")
    except Exception as e:
        print(f"File upload error: {e}")
        # Возможный фолбэк, если RTF не поддерживается
        return [], None, 0, 0
    
    prompt = f"""
Ты — юридический эксперт.
ЗАДАЧА:
Выбери статьи прилагаемого закона, которые с наибольшей вероятностью содержат ответ или полезную информацию для дачи ответа на поставленный вопрос.

Вопрос пользователя: "{question}"

Выведи топ-10 статей в порядке убывания релевантности в виде JSON.
Ожидаемый формат JSON:
[
  {{"article_number": "1", "percent": 95}},
  {{"article_number": "24", "percent": 80}}
]
"""
    try:
        response = await model.generate_content_async(
            [sample_file, prompt],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
            )
        )
        
        # Очистка и парсинг JSON
        raw_response = re.sub(r'^```json\s*', '', response.text.strip())
        raw_response = re.sub(r'\s*```$', '', raw_response)
        data = json.loads(raw_response)
        
        # Удаляем файл с серверов Google
        genai.delete_file(sample_file.name)
        
        # Извлекаем данные
        top_articles = []
        for item in data[:10]:
            art_num = item.get("article_number")
            if art_num:
                top_articles.append({
                    "id": f"53FZ_St_{art_num}",
                    "number": str(art_num),
                    "percent": item.get("percent", 0)
                })
                
        usage = response.usage_metadata
        return top_articles, usage, usage.prompt_token_count, usage.candidates_token_count
        
    except Exception as e:
        print(f"Error in get_top_ids: {e}")
        try:
            genai.delete_file(sample_file.name)
        except:
            pass
        return [], None, 0, 0

async def get_expert_analysis(question: str, top_articles: list, style: str = "telegram_yur") -> tuple:
    """Шаг 2: Собираем контекст и получаем экспертный ответ (всегда gemini-3.1-pro-preview)."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    contexts = []
    found_ids = set()
    
    for art in top_articles:
        item_id = art["id"]
        if item_id in JSON_DB:
            found_ids.add(item_id)
            contexts.append(f"--- RAG Контекст для Статьи {art['number']} ---\n{JSON_DB[item_id]}")
            
    if not contexts:
        return "К сожалению, не удалось найти юридический контекст (rag_context) для выбранных статей.", None, 0, 0
        
    combined_context = "\n\n".join(contexts)
    
    system_prompt = STYLES.get(style, STYLES["telegram_yur"])
    
    prompt = f"""{system_prompt}

Вопрос пользователя: "{question}"

Юридический контекст для анализа:
{combined_context}

Дай максимально качественный ответ на поставленный вопрос, аргументируя ответ точными цитатами из юридического контекста.
"""
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return response.text, usage, usage.prompt_token_count, usage.candidates_token_count
    except Exception as e:
        print(f"Error in get_expert_analysis: {e}")
        return f"Ошибка при генерации ответа: {e}", None, 0, 0