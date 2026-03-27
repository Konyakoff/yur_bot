import json
import os

def load_gemini_models() -> list:
    path = os.path.join("data", "gemini_models.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_json_db() -> dict:
    """
    Возвращает словарь формата { "ID": "rag_context" } 
    только для родительских объектов (parent_id = null)
    для быстрого поиска O(1).
    """
    path = os.path.join("data", "53-ФЗ All Articles.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    db_dict = {}
    for item in data:
        item_id = item.get("id")
        parent_id = item.get("parent_id")
        context = item.get("rag_context")
        # Берем только родительские статьи
        if item_id and context and parent_id is None:
            db_dict[item_id] = context
            
    return db_dict

# Предзагрузка данных при импорте модуля
GEMINI_MODELS = load_gemini_models()
JSON_DB = load_json_db()