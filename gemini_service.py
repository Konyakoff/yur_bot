import google.generativeai as genai
import json
import re
import os
import glob
from data_loader import JSON_DB, GEMINI_MODELS, find_rag_context
from styles import STYLES

# Настройка API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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
    """Шаг 1: Получаем ТОП-15 статей/пунктов закона из выжимок."""
    model = genai.GenerativeModel(selected_model)
    
    # Читаем все txt файлы из папки выжимок
    vyzhimka_dir = os.path.join("data", "Short_Zakony_Vyzhimka")
    all_contexts = []
    
    for file_path in glob.glob(os.path.join(vyzhimka_dir, "*.txt")):
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                all_contexts.append(f"--- НАЧАЛО ДОКУМЕНТА: {file_name} ---\n{content}\n--- КОНЕЦ ДОКУМЕНТА: {file_name} ---\n")
        except Exception as e:
            print(f"Ошибка чтения {file_path}: {e}")
            
    combined_vyzhimki = "\n".join(all_contexts)
    
    prompt = f"""
Ты — юридический эксперт.
ЗАДАЧА:
Изучи предоставленные короткие выжимки статей и пунктов нормативно-правовых актов (НПА).
Выбери топ-15 статей/пунктов, которые с наибольшей вероятностью могут содержать ответ на поставленный вопрос.

Вопрос пользователя: "{question}"

Выведи топ-15 в порядке убывания релевантности (от самой подходящей к менее подходящим) строго в виде JSON.
Имя файла должно быть строго без ".txt" в конце. 
Указывай четкий номер статьи или пункта из выжимки.

Ожидаемый формат JSON:
[
  {{"file_name": "4.PP_663_Pologenie_o_Prizyve", "item_number": "3.1", "percent": 95}},
  {{"file_name": "1.St_1-35.5.FZ_53", "item_number": "24", "percent": 80}}
]

ВЫЖИМКИ:
{combined_vyzhimki}
"""
    try:
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
        
        # Извлекаем данные
        top_articles = []
        for item in data[:15]:
            file_name = item.get("file_name", "").replace(".txt", "")
            item_number = str(item.get("item_number", ""))
            percent = item.get("percent", 0)
            
            if file_name and item_number:
                top_articles.append({
                    "file_name": file_name,
                    "item_number": item_number,
                    "percent": percent
                })
                
        usage = response.usage_metadata
        return top_articles, usage, usage.prompt_token_count, usage.candidates_token_count, prompt
        
    except Exception as e:
        print(f"Error in get_top_ids: {e}")
        # Возвращаем ошибку в виде строки
        return [], str(e), 0, 0, ""

def prepare_expert_context(top_articles: list) -> tuple:
    """Подготавливает контекст для второго шага и возвращает (combined_context, used_ids)."""
    # Фильтруем статьи: берем только те, где вероятность >= 70%
    filtered_articles = [art for art in top_articles if art.get("percent", 0) >= 70]
    
    # Если ни одна статья не достигла 70%, берем просто топ-3
    if not filtered_articles:
        filtered_articles = top_articles[:3]
    
    contexts = []
    used_ids = []
    
    for art in filtered_articles:
        file_name = art["file_name"]
        item_number = art["item_number"]
        
        rag_data = find_rag_context(file_name, item_number)
        if rag_data:
            contexts.append(f"--- RAG Контекст ({file_name}, статья/пункт {item_number}) ---\n{rag_data['context']}")
            used_ids.append(rag_data['id'])
            
    combined_context = "\n\n".join(contexts) if contexts else ""
    return combined_context, used_ids

async def get_expert_analysis(question: str, combined_context: str, style: str = "telegram_yur") -> tuple:
    """Шаг 2: Получаем экспертный ответ на основе подготовленного контекста."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    if not combined_context:
        return "К сожалению, не удалось найти детальный юридический контекст для выбранных статей.", None, 0, 0
        
    system_prompt = STYLES.get(style, STYLES["telegram_yur"])
    
    prompt = f"""{system_prompt}

Вопрос пользователя: "{question}"

Юридический контекст для анализа (выдержки из НПА):
{combined_context}

Дай максимально качественный ответ на поставленный вопрос, аргументируя ответ точными цитатами из предоставленного юридического контекста. Если в контексте нет ответа на вопрос, честно скажи об этом.
"""
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return response.text, usage, usage.prompt_token_count, usage.candidates_token_count, prompt
    except Exception as e:
        print(f"Error in get_expert_analysis: {e}")
        return f"Ошибка при генерации ответа: {e}", None, 0, 0, ""
