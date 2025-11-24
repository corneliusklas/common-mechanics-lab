# llm_service.py
import json
import os
import threading
import importlib.util
import sys
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) 
lock = threading.Lock() 

# --- CONFIG & STATE ---
MAX_LLM_REQUESTS = 500
DEFAULT_SYSTEM_MESSAGE = "Du bist ein freundlicher, hilfreicher Roboter PiBot."
current_system_message = DEFAULT_SYSTEM_MESSAGE
conversation_history = [{"role": "system", "content": current_system_message}]

session_state = {"llm_count": 0, "last_llm_prompt": None, "last_response": None}

# --- TOOL REGISTRY (Dynamisch) ---
REGISTERED_TOOL_FUNCTIONS = {} # Map: "name" -> func
LOADED_TOOL_MODULES = []       # Liste der geladenen Module (für State-Zugriffe)

def _load_tools_from_folder(folder="tools"):
    """
    Scannt den Ordner, importiert alle .py Dateien und registriert
    deren TOOL_FUNCTIONS und Schemas.
    """
    global REGISTERED_TOOL_FUNCTIONS, LOADED_TOOL_MODULES
    
    REGISTERED_TOOL_FUNCTIONS = {}
    LOADED_TOOL_MODULES = []
    
    if not os.path.exists(folder):
        print(f"⚠️ Tool folder '{folder}' not found.")
        return

    # Durchsuche den Ordner
    for filename in os.listdir(folder):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3] # .py entfernen
            file_path = os.path.join(folder, filename)
            
            try:
                # Dynamischer Import
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # Prüfen ob das Modul die nötigen Attribute hat
                if hasattr(module, "TOOL_FUNCTIONS"):
                    REGISTERED_TOOL_FUNCTIONS.update(module.TOOL_FUNCTIONS)
                    LOADED_TOOL_MODULES.append(module)
                    print(f"✅ Loaded tools from: {filename}")
            except Exception as e:
                print(f"❌ Error loading {filename}: {e}")

def _get_combined_schemas():
    """Ruft get_tool_schemas() von allen geladenen Modulen auf."""
    schemas = []
    for module in LOADED_TOOL_MODULES:
        if hasattr(module, "get_tool_schemas"):
            # Ruft die Funktion im Modul auf (ermöglicht dynamische Enums)
            schemas.extend(module.get_tool_schemas())
    return schemas

# Initiales Laden der Tools
_load_tools_from_folder()


# --- WRAPPER FÜR EMOTION STATE ---
# Da Emotionen jetzt in einem externen Modul leben, müssen wir
# sicherstellen, dass wir das richtige Modul finden, um den State zu ändern.

def _find_emotion_module():
    for mod in LOADED_TOOL_MODULES:
        if hasattr(mod, "set_allowed_emotions"):
            return mod
    return None

def set_allowed_emotions(emotion_list):
    mod = _find_emotion_module()
    if mod:
        res = mod.set_allowed_emotions(emotion_list)
        print(f"Allowed emotions updated via module: {mod.get_allowed_emotions()}")
        return res
    return False

def get_allowed_emotions():
    mod = _find_emotion_module()
    return mod.get_allowed_emotions() if mod else []

def get_last_emotion():
    mod = _find_emotion_module()
    return mod.get_last_emotion() if mod else "neutral"


# --- HISTORY MANAGEMENT (Unverändert) ---
def initialize_history():
    global conversation_history
    conversation_history = [{"role": "system", "content": current_system_message}]

def set_system_message(new_message):
    global current_system_message
    with lock:
        current_system_message = new_message
        initialize_history()

def clear_history():
    with lock:
        initialize_history()

def get_history():
    # Vereinfachte Version für die Anzeige
    return [m for m in conversation_history if m["role"] != "system"]

# -------------------------
# --- MAIN RESPONSE LOGIC ---
# -------------------------

def generate_response(prompt):
    global conversation_history
    
    # Tools jedes Mal neu abrufen, falls sich dynamische Schemas (Emotionen) geändert haben
    current_tools = _get_combined_schemas()

    with lock:
        if not OPENAI_API_KEY: return "Error: No API Key", []
        if prompt == session_state["last_llm_prompt"]: return session_state["last_response"], []

        conversation_history.append({"role": "user", "content": prompt})
        current_messages = conversation_history
        executed_tool_calls = []
        final_text = None

        for turn in range(5):
            try:
                print(f"-> LLM Request (Turn {turn+1})")
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=current_messages,
                    tools=current_tools, # Hier nutzen wir die automatisch geladenen Schemas
                    tool_choice="auto"
                )
            except Exception as e:
                return f"LLM Error: {e}", []

            msg = response.choices[0].message
            current_messages.append(msg)

            if msg.content:
                final_text = msg.content
                break
            
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fname = tc.function.name
                    args = json.loads(tc.function.arguments)
                    
                    # Wir suchen die Funktion in unserer Registry
                    if fname in REGISTERED_TOOL_FUNCTIONS:
                        print(f"-> Executing Tool: {fname}")
                        func = REGISTERED_TOOL_FUNCTIONS[fname]
                        try:
                            result = func(**args)
                            
                            # Metadaten speichern
                            if fname == "set_face_emotion":
                                executed_tool_calls.append({"name": fname, "args": args})
                                
                            current_messages.append({
                                "tool_call_id": tc.id,
                                "role": "tool",
                                "name": fname,
                                "content": str(result)
                            })
                        except Exception as e:
                            current_messages.append({
                                "tool_call_id": tc.id, 
                                "role": "tool", 
                                "name": fname, 
                                "content": f"Error: {e}"
                            })
                    else:
                        current_messages.append({
                            "tool_call_id": tc.id, 
                            "role": "tool", 
                            "name": fname, 
                            "content": "Error: Tool not found on server."
                        })
            else:
                final_text = "Error: Empty response."
                break

        if final_text:
            conversation_history[:] = current_messages
            session_state["last_llm_prompt"] = prompt
            session_state["last_response"] = final_text
            session_state["llm_count"] += 1
            return final_text, executed_tool_calls
        
        return "Error: Loop limit exceeded.", []

# --- INIT ---
initialize_history()

if __name__ == "__main__":
    # Testlauf
    print("--- Testing Autoloader ---")
    
    # Test 1: Config ändern (via Wrapper -> emotion_tools.py)
    set_allowed_emotions(["excited", "bored"])
    
    # Test 2: LLM Anfrage
    resp, tools = generate_response("Wie spät ist es in Tokio und schau dabei 'excited'!")
    print(f"\nAntwort: {resp}")
    print(f"Tools: {tools}")
    print(f"Letzte Emotion (aus Module): {get_last_emotion()}")