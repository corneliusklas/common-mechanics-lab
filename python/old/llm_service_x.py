# llm_service.py - Kombinierte Version für Multimodalität (Bild) und Tools (Emotionen)
import json
import os
import threading
import importlib.util
import sys
from dotenv import load_dotenv
from openai import OpenAI
from typing import List, Dict, Any, Tuple, Optional, Union

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialisiere den OpenAI Client.
client: Optional[OpenAI] = None
try:
    # WICHTIG: Verwenden Sie gpt-4o für Multimodalität (Bild) und Tool Calls
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY) 
    else:
        print("FATAL: OPENAI_API_KEY is missing in .env. LLM functions will fail.")
except Exception as e:
    print(f"FATAL: OpenAI Client initialization failed: {e}")
    
lock = threading.Lock() 

# --- CONFIG & STATE ---
MAX_LLM_REQUESTS = 500
# Systemnachricht angepasst, um multimodale Funktionen zu signalisieren
DEFAULT_SYSTEM_MESSAGE = "Du bist ein freundlicher, hilfreicher Roboter PiBot. Du bist mit verschiedenen Tools ausgestattet, um Aufgaben in der physischen Welt auszuführen und multimodale Daten zu erfassen."
current_system_message: str = DEFAULT_SYSTEM_MESSAGE
conversation_history: List[Dict[str, Any]] = [{"role": "system", "content": current_system_message}]

session_state: Dict[str, Any] = {"llm_count": 0, "last_llm_prompt": None, "last_response": None}

# --- TOOL REGISTRY (Dynamisch) ---
REGISTERED_TOOL_FUNCTIONS: Dict[str, Any] = {} # Map: "name" -> func
LOADED_TOOL_MODULES: List[Any] = []       # Liste der geladenen Module (für State-Zugriffe)
TOOL_SCHEMAS: List[Dict[str, Any]] = []    # Liste der LLM Function Schemas (statische Schemas)

def _load_tools_from_folder(folder: str = "tools"):
    """
    Scannt den Ordner, importiert alle .py Dateien und registriert 
    deren TOOL_FUNCTIONS und Schemas.
    """
    global REGISTERED_TOOL_FUNCTIONS, LOADED_TOOL_MODULES, TOOL_SCHEMAS
    
    REGISTERED_TOOL_FUNCTIONS = {}
    LOADED_TOOL_MODULES = []
    TOOL_SCHEMAS = []
    
    if not os.path.exists(folder):
        print(f"⚠️ Tool folder '{folder}' not found. No tools registered.")
        return

    # Fügen Sie den Ordner zum Python-Pfad hinzu, um relative Importe zu ermöglichen
    if folder not in sys.path:
        sys.path.append(folder)

    # Durchsuche den Ordner
    for filename in os.listdir(folder):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                # Dynamisches Laden des Moduls
                spec = importlib.util.spec_from_file_location(module_name, os.path.join(folder, filename))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    # Löschen Sie das Modul, falls es bereits existiert, um Neuladen zu ermöglichen
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                    spec.loader.exec_module(module)
                    sys.modules[module_name] = module # Wieder hinzufügen
                    
                    # Funktionen und Schemas registrieren
                    if hasattr(module, "TOOL_FUNCTIONS"):
                        # Die Funktionen sollten jetzt die gesamte Struktur (Funktion + Schema) enthalten
                        REGISTERED_TOOL_FUNCTIONS.update(module.TOOL_FUNCTIONS)
                        LOADED_TOOL_MODULES.append(module)
                        print(f"✅ Loaded tool module: {module_name} with {len(module.TOOL_FUNCTIONS)} functions.")
                        
                        if hasattr(module, "get_tool_schemas"):
                            # Hinzufügen der Schemas (können dynamisch sein)
                            TOOL_SCHEMAS.extend(module.get_tool_schemas())
                            
            except Exception as e:
                print(f"❌ Error loading tool module {module_name}: {e}")
                
    # Pfad wieder entfernen
    if folder in sys.path:
        sys.path.remove(folder)

# --- EMOTION STATE WRAPPER (Für die API-Endpunkte in server.py) ---

def _find_emotion_module():
    """Findet das Modul, das die set_allowed_emotions Funktion enthält."""
    for mod in LOADED_TOOL_MODULES:
        if hasattr(mod, "set_allowed_emotions"):
            return mod
    return None

def set_allowed_emotions(emotion_list: List[str]):
    """Setzt die erlaubten Emotionen über das geladene Tool-Modul."""
    mod = _find_emotion_module()
    if mod:
        try:
            res = mod.set_allowed_emotions(emotion_list)
            print(f"Allowed emotions updated via module: {mod.get_allowed_emotions()}")
            return res
        except Exception as e:
            print(f"❌ Error in set_allowed_emotions: {e}")
            return False
    return False

def get_allowed_emotions() -> List[str]:
    """Holt die erlaubten Emotionen über das geladene Tool-Modul."""
    mod = _find_emotion_module()
    if mod:
        try:
            return mod.get_allowed_emotions()
        except Exception as e:
            print(f"❌ Error in get_allowed_emotions: {e}")
            return []
    return []

def get_last_emotion() -> str:
    """Holt die zuletzt vom Tool gesetzte Emotion."""
    mod = _find_emotion_module()
    if mod:
        try:
            return mod.get_last_emotion()
        except Exception as e:
            print(f"❌ Error in get_last_emotion: {e}")
            # Wenn das Tool-Modul fehlschlägt, geben wir neutral zurück, um einen 500er zu vermeiden.
            return "neutral"
    return "neutral"


# --- HISTORY MANAGEMENT (Unverändert) ---
def initialize_history():
    """Setzt den Verlauf mit der aktuellen Systemnachricht zurück und lädt Tools neu."""
    global conversation_history, current_system_message, session_state
    
    # Reload tools und Schemas
    _load_tools_from_folder()

    conversation_history.clear()
    conversation_history.append({"role": "system", "content": current_system_message})
    
    session_state["llm_count"] = 0
    session_state["last_llm_prompt"] = None
    session_state["last_response"] = None

def set_system_message(new_message: str):
    """Setzt die Systemnachricht und startet einen neuen Verlauf."""
    global current_system_message
    with lock:
        current_system_message = new_message
        initialize_history()

def clear_history():
    """Löscht den Gesprächsverlauf und startet neu."""
    with lock:
        initialize_history()

def get_history() -> List[Dict[str, Any]]:
    """Gibt den aktuellen Gesprächsverlauf (ohne Systemnachricht) zurück."""
    # Vereinfachte Version für die Anzeige
    return [m for m in conversation_history if m["role"] != "system"]

# -------------------------
# --- MAIN RESPONSE LOGIC ---
# -------------------------

def generate_response(prompt: str) -> Tuple[str, List[str]]:
    """
    Generiert eine Antwort vom LLM, einschließlich Tool-Nutzung und
    Verarbeitung von multimodalen Payloads.
    """
    global conversation_history, session_state
    
    if client is None:
        return "Error: LLM client not initialized (API Key missing or connection failed).", []

    # Prüfen, ob der Prompt derselbe ist, um Doppelanfragen zu vermeiden
    with lock:
        if prompt == session_state["last_llm_prompt"]: 
            return session_state.get("last_response", "Bitte stelle eine neue Frage."), []

    # Fügen Sie den neuen Benutzerprompt zur History hinzu
    new_user_message = {"role": "user", "content": prompt}
    
    # Temporäre Nachrichtenliste für den aktuellen Request
    current_messages = list(conversation_history)
    current_messages.append(new_user_message)
    
    executed_tool_calls: List[str] = []
    final_text: Optional[str] = None 
    
    # LLM Request Loop für Function Calling
    for i in range(5): # Begrenzt die Anzahl der LLM-Runden
        
        if session_state["llm_count"] >= MAX_LLM_REQUESTS:
            final_text = "Error: LLM request limit reached."
            break 
        
        try:
            with lock: # Thread-Sicherheit beim Aufruf der OpenAI API
                print(f"-> LLM Request (Turn {i+1})")
                response = client.chat.completions.create(
                    model="gpt-4o", 
                    messages=current_messages,
                    tools=TOOL_SCHEMAS if TOOL_SCHEMAS else None,
                    tool_choice="auto" if TOOL_SCHEMAS else None,
                )
                session_state["llm_count"] += 1
                
        except Exception as e:
            final_text = f"Error: Failed to call LLM API: {e}"
            break 

        choice = response.choices[0]
        msg = choice.message
        
        # 1. Text-Antwort
        if msg.content:
            final_text = msg.content
            current_messages.append({"role": "assistant", "content": final_text})
            break 

        # 2. Tool-Calls
        elif msg.tool_calls:
            current_messages.append(msg.model_dump()) # Fügt Tool-Request zur History hinzu
            
            image_was_injected = False 
            
            for tc in msg.tool_calls:
                fname = tc.function.name
                fargs_str = tc.function.arguments
                
                if fname in REGISTERED_TOOL_FUNCTIONS:
                    try:
                        # Argumente vorbereiten
                        fargs = json.loads(fargs_str)
                        executed_tool_calls.append(f"{fname}({fargs_str})")
                        
                        # Tool-Funktion ausführen
                        # HIER WIRD DIE FUNKTION AUS DEM TOOL-REGISTER GEHOLT
                        # WICHTIG: Geht davon aus, dass REGISTERED_TOOL_FUNCTIONS[fname]
                        # die Funktion direkt ist (wie in der ersten Version) ODER ein Dict
                        # mit dem Schlüssel 'function'. Wir nehmen an, es ist direkt die Funktion 
                        # oder wir greifen auf 'function' zu, wenn es ein Dict ist.
                        func_entry = REGISTERED_TOOL_FUNCTIONS[fname]
                        func = func_entry['function'] if isinstance(func_entry, dict) and 'function' in func_entry else func_entry
                        
                        result = func(**fargs)
                        
                        # --- MULTIMODAL VERARBEITUNG ---
                        tool_content_for_llm: Union[str, Dict[str, Any]] = str(result)
                        
                        try:
                            # 1. Versuche, das Ergebnis als JSON zu parsen (erwartet von camera_tools.py)
                            tool_data = json.loads(str(result)) 
                            
                            # 2. Prüfe auf multimodalen Payload
                            payload = tool_data.get("multimodal_payload")
                            base64_data = payload.get("base64_data") if payload else None
                            mime_type = payload.get("mime_type") if payload else None
                            
                            if base64_data and mime_type:
                                # Data URL erstellen
                                image_url = f"data:{mime_type};base64,{base64_data}"
                                
                                # Hinzufügen der Tool-Antwort (als Bestätigung des Tool-Aufrufs)
                                current_messages.append({
                                    "tool_call_id": tc.id, 
                                    "role": "tool", 
                                    "name": fname, 
                                    "content": tool_data.get("message", "Tool execution completed.")
                                })
                                
                                # NEU: Füge die multimodale Nachricht hinzu
                                image_message_part = {
                                    "role": "user",
                                    "content": [
                                        # Fügen Sie den ORIGINAL-PROMPT wieder hinzu,
                                        # damit das LLM weiß, was es mit dem Bild tun soll.
                                        {"type": "text", "text": prompt}, 
                                        {"type": "image_url", "image_url": {"url": image_url}}
                                    ]
                                }
                                
                                current_messages.append(image_message_part) 
                                print("DEBUG: Multimodal payload successfully injected into history. Restarting LLM for analysis.")
                                
                                image_was_injected = True 
                                break # BEENDE INNERE SCHLEIFE
                                
                            else:
                                # Normales JSON oder JSON ohne Base64 Payload
                                tool_content_for_llm = str(result)
                                
                        except json.JSONDecodeError:
                            # 3. Wenn es kein JSON ist, behandle es als normale Text-Tool-Antwort
                            tool_content_for_llm = str(result)
                        
                        # --- ENDE MULTIMODAL VERARBEITUNG ---
                        
                        # Füge die Tool-Antwort zur History hinzu (nur wenn kein Bild injiziert wurde)
                        if not image_was_injected: 
                            current_messages.append({
                                "tool_call_id": tc.id, 
                                "role": "tool", 
                                "name": fname, 
                                "content": tool_content_for_llm 
                            })

                    except Exception as e:
                        print(f"❌ ERROR: Failed to execute tool {fname}: {e}")
                        current_messages.append({
                                "tool_call_id": tc.id, 
                                "role": "tool", 
                                "name": fname, 
                                "content": f"Error: Tool execution failed with: {e}"
                            })
                else:
                    current_messages.append({
                        "tool_call_id": tc.id, 
                        "role": "tool", 
                        "name": fname, 
                        "content": "Error: Tool not found on server."
                    })
            
            # --- PRÜFUNG NACH INNERE SCHLEIFE ---
            if image_was_injected:
                # Wenn ein Bild injiziert wurde, fahren wir sofort mit der nächsten LLM-Runde fort.
                continue 
            
        else:
            # Weder Text-Antwort noch Tool-Call vorhanden
            final_text = "Error: LLM response without content or tool call."
            current_messages.append({"role": "assistant", "content": final_text})
            break

    # --- SPEICHERN NACH SCHLEIFE ---
    if final_text:
        with lock:
            # Speichere die komplette, bereinigte History
            conversation_history[:] = current_messages
            session_state["last_llm_prompt"] = prompt
            session_state["last_response"] = final_text
            return final_text, executed_tool_calls
        
    return "Error: Loop limit exceeded.", []

# --- INIT ---
initialize_history()

if __name__ == "__main__":
    # Testlauf
    print("--- Testing LLM Service Initialization ---")
    
    # Test 1: Laden der Tools
    print(f"\nRegistered Tools: {list(REGISTERED_TOOL_FUNCTIONS.keys())}")
    print(f"Loaded Schemas: {len(TOOL_SCHEMAS)}")

    # Test 2: Emotionen (set/get)
    set_allowed_emotions(["happy", "sad"])
    print(f"Allowed Emotions: {get_allowed_emotions()}")
    
    print("\nLLM Service ist initialisiert und bereit.")