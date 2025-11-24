# llm_service.py
import json
import os
import threading
import importlib.util
import sys
from dotenv import load_dotenv
from openai import OpenAI
from typing import List, Dict, Any, Tuple, Optional

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) 
lock = threading.Lock() 

# --- CONFIG & STATE ---
MAX_LLM_REQUESTS = 500
# System message updated to signal multimodal capabilities
DEFAULT_SYSTEM_MESSAGE = "You are a friendly, helpful robot, PiBot. You are equipped with various tools to perform tasks in the physical world and capture multimodal data."
current_system_message = DEFAULT_SYSTEM_MESSAGE
conversation_history: List[Dict[str, Any]] = [{"role": "system", "content": current_system_message}]

session_state: Dict[str, Any] = {"llm_count": 0, "last_llm_prompt": None, "last_response": None}

# --- TOOL REGISTRY (Dynamic) ---
REGISTERED_TOOL_FUNCTIONS: Dict[str, Any] = {} # Map: "name" -> func
LOADED_TOOL_MODULES: List[Any] = []       # List of loaded modules (for state access)
TOOL_SCHEMAS: List[Dict[str, Any]] = []    # List of LLM Function Schemas

def _load_tools_from_folder(folder: str = "tools"):
    """
    Scans the folder, imports all .py files, and registers 
    their TOOL_FUNCTIONS and schemas.
    """
    global REGISTERED_TOOL_FUNCTIONS, LOADED_TOOL_MODULES, TOOL_SCHEMAS
    
    REGISTERED_TOOL_FUNCTIONS = {}
    LOADED_TOOL_MODULES = []
    TOOL_SCHEMAS = []
    
    if not os.path.exists(folder):
        print(f"⚠️ Tool folder '{folder}' not found. No tools registered.")
        return

    # Add the folder to the Python path to allow relative imports
    if folder not in sys.path:
        sys.path.append(folder)

    # Search the folder
    for filename in os.listdir(folder):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                # Dynamically load the module
                spec = importlib.util.spec_from_file_location(module_name, os.path.join(folder, filename))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    # Delete module from sys.modules if it already exists, to allow reloading
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                    spec.loader.exec_module(module)
                    sys.modules[module_name] = module # Add it again
                    
                    # Register functions and schemas, if available
                    if hasattr(module, "TOOL_FUNCTIONS"):
                        REGISTERED_TOOL_FUNCTIONS.update(module.TOOL_FUNCTIONS)
                        LOADED_TOOL_MODULES.append(module)
                        print(f"✅ Loaded tool module: {module_name} with {len(module.TOOL_FUNCTIONS)} functions.")
                        
                        if hasattr(module, "get_tool_schemas"):
                            TOOL_SCHEMAS.extend(module.get_tool_schemas())
                            
            except Exception as e:
                print(f"❌ Error loading tool module {module_name}: {e}")
                
    # Remove the path again to keep the namespace clean
    if folder in sys.path:
        sys.path.remove(folder)

def initialize_history():
    """Resets the conversation history and loads tools."""
    global conversation_history, current_system_message, session_state
    
    # Reload tools
    _load_tools_from_folder()

    current_system_message = DEFAULT_SYSTEM_MESSAGE
    conversation_history.clear()
    conversation_history.append({"role": "system", "content": current_system_message})
    
    session_state["llm_count"] = 0
    session_state["last_llm_prompt"] = None
    session_state["last_response"] = None

def generate_response(prompt: str) -> Tuple[str, List[str]]:
    """
    Generates a response from the LLM, including tool usage and 
    processing of multimodal payloads.
    """
    global conversation_history, current_system_message, session_state
    
    # Add the new user prompt to the history
    new_user_message = {"role": "user", "content": prompt}
    
    # Temporary message list used for the current request
    current_messages = list(conversation_history)
    current_messages.append(new_user_message)
    
    executed_tool_calls: List[str] = []
    final_text: Optional[str] = None # Set final_text initially to None
    
    # LLM Request Loop for Function Calling
    for i in range(5): # Limit the number of LLM rounds
        
        if session_state["llm_count"] >= MAX_LLM_REQUESTS:
            final_text = "Error: LLM request limit reached."
            break # Break the loop
        
        try:
            with lock: # Thread safety when calling the OpenAI API
                response = client.chat.completions.create(
                    model="gpt-4o", # A multimodal model is required
                    messages=current_messages,
                    tools=TOOL_SCHEMAS if TOOL_SCHEMAS else None,
                    tool_choice="auto" if TOOL_SCHEMAS else None,
                )
                session_state["llm_count"] += 1
                
        except Exception as e:
            final_text = f"Error: Failed to call LLM API: {e}"
            break # Break the loop

        choice = response.choices[0]
        
        if choice.message.content:
            # LLM generated a text response
            final_text = choice.message.content
            current_messages.append({"role": "assistant", "content": final_text})
            break # End the loop, as we have a text response

        elif choice.message.tool_calls:
            # LLM requested one or more tool calls
            current_messages.append(choice.message.model_dump()) # Adds tool request
            
            image_was_injected = False # NEW: Flag for immediate LLM restart after image injection
            
            for tc in choice.message.tool_calls:
                fname = tc.function.name
                fargs_str = tc.function.arguments
                
                if fname in REGISTERED_TOOL_FUNCTIONS:
                    try:
                        # Prepare arguments
                        fargs = json.loads(fargs_str)
                        executed_tool_calls.append(f"{fname}({fargs_str})")
                        
                        # Execute the function
                        func = REGISTERED_TOOL_FUNCTIONS[fname]
                        result = func(**fargs)
                        
                        # --- START MINIMAL MULTIMODAL ADJUSTMENT ---
                        try:
                            # 1. Try to parse the result as JSON (expected from camera_tools.py)
                            tool_data = json.loads(result)
                            
                            # 2. Check for multimodal payload
                            payload = tool_data.get("multimodal_payload")
                            base64_data = payload.get("base64_data") if payload else None
                            mime_type = payload.get("mime_type") if payload else None
                            
                            if base64_data and mime_type:
                                # Create Data URL (e.g., data:image/jpeg;base64,...)
                                image_url = f"data:{mime_type};base64,{base64_data}"
                                
                                # Add the tool response (result) to the history (as confirmation of the tool call)
                                # IMPORTANT: Use a neutral message HERE, as the image analysis follows in the next step
                                current_messages.append({
                                    "tool_call_id": tc.id, 
                                    "role": "tool", 
                                    "name": fname, 
                                    "content": tool_data.get("message", "Tool execution completed.")
                                })
                                
                                # NEW: Add the multimodal message with almost empty text as the next 'user' entry
                                image_message_part = {
                                    "role": "user",
                                    "content": [
                                        # Just a dot to start the next LLM call without provoking a text response from the LLM
                                        {"type": "text", "text": "."}, 
                                        {"type": "image_url", "image_url": {"url": image_url}}
                                    ]
                                }
                                
                                current_messages.append(image_message_part) 
                                print("DEBUG: Multimodal payload successfully injected into history.")
                                
                                image_was_injected = True # SET FLAG
                                break # IMMEDIATELY END INNER LOOP (since image injection occurred)
                                
                            else:
                                # Normal JSON or JSON without Base64 payload
                                tool_content_for_llm = result
                                
                        except json.JSONDecodeError:
                            # 3. If it is not JSON, treat it as a normal text tool response
                            tool_content_for_llm = result
                        
                        # --- END MINIMAL MULTIMODAL ADJUSTMENT ---
                        
                        # Add the tool response (result) to the history (only if no image was injected)
                        if not image_was_injected: 
                            current_messages.append({
                                "tool_call_id": tc.id, 
                                "role": "tool", 
                                "name": fname, 
                                "content": tool_content_for_llm 
                            })

                    except Exception as e:
                        print(f"ERROR: Failed to execute tool {fname}: {e}")
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
            
            # --- CHECK AFTER INNER LOOP ---
            if image_was_injected:
                # If an image was injected, we must immediately proceed to the next LLM round 
                # (outer loop) to have the image analyzed.
                continue # IMMEDIATELY CONTINUE OUTER LOOP
            
        else:
            # If no text response and no tool call is present
            final_text = "Error: LLM response without content or tool call."
            current_messages.append({"role": "assistant", "content": final_text})
            break

    # --- CHECK AFTER LOOP ---
    if final_text:
        # Save the complete, cleaned history
        conversation_history[:] = current_messages
        session_state["last_llm_prompt"] = prompt
        session_state["last_response"] = final_text
        return final_text, executed_tool_calls
        
    return "Error: Loop limit exceeded.", []

# --- INIT ---
initialize_history()

if __name__ == "__main__":
    # Test run
    print("--- Testing LLM Service Initialization ---")
    
    # Simulate tool initialization (assumes camera_tools.py exists)
    _load_tools_from_folder()

    print(f"\nRegistered Tools: {list(REGISTERED_TOOL_FUNCTIONS.keys())}")
    
    # Example for a text request that does not use tools:
    if not TOOL_SCHEMAS:
        resp, tools = generate_response("Hello, how are you today?")
        print(f"\nResponse (Text-Only): {resp}")
        print(f"Tools executed: {tools}")
        
    print("\nLLM Service is initialized and ready.")