import json
import os

def load_categories_text() -> str:
    path = os.path.join("data", "CATEGORIES_TEXT.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_json_db() -> dict:
    """
    Возвращает словарь формата { "ID": "rag_context" } 
    для быстрого поиска O(1).
    """
    path = os.path.join("data", "PP565_All_Art.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    db_dict = {}
    for item in data:
        item_id = item.get("id")
        context = item.get("rag_context")
        if item_id and context:
            db_dict[item_id] = context
            
    return db_dict

# Предзагрузка данных при импорте модуля
CATEGORIES_TEXT = load_categories_text()
JSON_DB = load_json_db()