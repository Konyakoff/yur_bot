import json
import os
import glob

def load_gemini_models() -> list:
    path = os.path.join("data", "gemini_models.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def load_json_db() -> dict:
    """
    Загружает все JSON-файлы из папки data/Zakony_json/
    и возвращает словарь формата:
    {
      "название_файла_без_расширения": {
        "номер_статьи_или_пункта": "rag_context"
      }
    }
    """
    db_dict = {}
    json_dir = os.path.join("data", "Zakony_json")
    
    if not os.path.exists(json_dir):
        return db_dict
        
    for file_path in glob.glob(os.path.join(json_dir, "*.json")):
        file_name = os.path.basename(file_path)
        base_name = os.path.splitext(file_name)[0]
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                file_dict = {}
                for item in data:
                    item_number = item.get("number")
                    context = item.get("rag_context")
                    parent_id = item.get("parent_id")
                    item_id = item.get("id")
                    
                    # Берем только родительские статьи (parent_id = null или его нет)
                    if item_number and context and parent_id is None:
                        file_dict[str(item_number)] = {
                            "context": context,
                            "id": item_id
                        }
                        
                db_dict[base_name] = file_dict
            except Exception as e:
                print(f"Ошибка загрузки {file_path}: {e}")
                
    return db_dict

def find_rag_context(file_name: str, item_number: str) -> dict:
    """
    Умный скрипт поиска rag_context по имени файла и номеру статьи/пункта.
    Возвращает словарь {"context": "...", "id": "..."} или None.
    """
    if file_name in JSON_DB:
        # Проверяем точное совпадение
        if str(item_number) in JSON_DB[file_name]:
            return JSON_DB[file_name][str(item_number)]
    return None

# Предзагрузка данных при импорте модуля
GEMINI_MODELS = load_gemini_models()
JSON_DB = load_json_db()
