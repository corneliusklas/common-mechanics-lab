# server.py (or main_app.py)
# -------------------------------------------------------------------------------------------------
# Flask REST API Router for PiBot Scratch Extension
#
# PURPOSE: Serves as the central interface, routing HTTP requests from the PiBot Scratch extension 
# to the appropriate backend services (LLM, TTS, Hearing).
#
# FUNCTIONALITY:
# - Configures CORS (Cross-Origin Resource Sharing) to allow communication from the Scratch editor.
# - Provides API endpoints (e.g., /api/ask_llm, /api/tts_speak) for the JavaScript extension.
# - Integrates and manages the state of llm_service, tts_service, and hearing_service.
# -------------------------------------------------------------------------------------------------

import os
import json
import threading
import subprocess
import re
import ipaddress
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Lokale Module importieren
import llm_service
import tts_service
import hearing_service 

load_dotenv()

# --- FLASK SETUP ---
# Setzt den statischen Ordner relativ zum Script (z.B. '../web')
app = Flask(__name__, static_folder='../web') 
CORS(app) 
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- GLOBAL LOCK ---
AUDIO_LOCK = threading.Lock() 

# --- CORS & Error Handling ---
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Max 16MB.'}), 413

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# =========================================================================
# --- WEB SERVER ROUTEN (STATISCH, TURBOWARP & DEVICES) ---
# =========================================================================

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/turbowrap/build-tw/<path:path>')
def turbowrap_editor(path):
    return send_from_directory(os.path.join(app.static_folder, 'turbowrap/build-tw'), path)

@app.route('/turbowrap/extensions/<path:path>')
def turbowrap_extensions(path):
    return send_from_directory(os.path.join(app.static_folder, 'turbowrap/extensions'), path)

# ---------- Hilfsfunktionen (für /devices Route) ----------

def get_mdns_devices(timeout="1s"):
    """Findet Geräte im Netz per mDNS (über avahi-browse). (Unverändert)"""
    devices_map = {}
    try:
        # Führt avahi-browse aus
        result = subprocess.run(
            ["timeout", str(timeout), "avahi-browse", "-alrt"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore' 
        )
        lines = result.stdout.splitlines()
        current_ip, current_host = None, None

        for line in lines:
            if "hostname = [" in line:
                match = re.search(r"hostname = \[([^\]]+)\]", line)
                if match:
                    current_host = match.group(1).replace(".local", "")
            if "address = [" in line:
                match = re.search(r"address = \[([0-9\.]+)\]", line)
                if match:
                    current_ip = match.group(1)
            
            if current_ip and current_host:
                if current_ip not in devices_map:
                    devices_map[current_ip] = current_host
                current_ip, current_host = None, None

    except Exception as e:
        print("Fehler bei mDNS-Scan:", e)

    return [{'ip': ip, 'hostname': host} for ip, host in devices_map.items()]

@app.route('/devices')
def devices():
    """Zeigt eine HTML-Liste der im Netzwerk gefundenen mDNS-Geräte. (Unverändert)"""
    devices_list = get_mdns_devices(timeout="1s")
    # ... (Rest der Devices-HTML-Logik unverändert)
    PI_SUBNET = ipaddress.IPv4Network("192.168.50.0/24")

    def sort_key(d):
        try:
            ip_obj = ipaddress.IPv4Address(d['ip'])
            if ip_obj in PI_SUBNET:
                return (0, ip_obj)
            else:
                return (1, ip_obj)
        except:
            return (2, ipaddress.IPv4Address("0.0.0.0"))

    devices_list.sort(key=sort_key)

    html = """
    <!DOCTYPE html><html><head><meta charset='UTF-8'><title>Netzwerkgeräte</title>
    <style>
    body{font-family:Arial,sans-serif;padding:20px;}
    table{border-collapse:collapse;width:100%;}
    th,td{border:1px solid #ddd;padding:8px;text-align:left;}
    th{background-color:#007acc;color:white;}
    tr:nth-child(even){background-color:#f2f2f2;}
    </style></head><body>
    <h1>Geräte im lokalen Netzwerk (mDNS)</h1>
    <table><tr><th>IP-Adresse</th><th>Hostname</th></tr>
    """

    for d in devices_list:
        try:
            ip_obj = ipaddress.IPv4Address(d['ip'])
            style = "" if ip_obj in PI_SUBNET else "color:gray;"
        except:
            style = "color:gray;"

        ip_link = f"<a href='http://{d['ip']}/' target='_blank' style='{style}'>{d['ip']}</a>"
        hostname_link = f"<a href='http://{d['hostname']}.local/' target='_blank' style='{style}'>{d['hostname']}</a>"

        html += f"<tr style='{style}'><td>{ip_link}</td><td>{hostname_link}</td></tr>"

    html += "</table></body></html>"
    return html

# =========================================================================
# --- AI SERVER ROUTEN (KORRIGIERTE LLM-LOGIK) ---
# =========================================================================

# --- Audio / STT Routen (Nutzen hearing_service) ---

@app.route('/api/start_record', methods=['POST'])
def start_record():
    """Startet die Aufnahme über den hearing_service."""
    with AUDIO_LOCK:
        success = hearing_service.start_pi_recording()
        if success:
            return jsonify({'status': 'Recording started'}), 200
        else:
            return jsonify({'error': 'Failed to start recording or already active.'}), 500

@app.route('/api/stop_transcribe', methods=['POST'])
def stop_transcribe():
    """Stoppt die Aufnahme, speichert die WAV und transkribiert (erwartet JSON)."""
    try:
        data = request.get_json()
        lang = data.get('lang', 'en') 
        
        with AUDIO_LOCK:
            transcript, error = hearing_service.stop_pi_recording_and_transcribe(lang)

        if error:
             return jsonify({'error': error}), 400
        
        return jsonify({'text': transcript}), 200

    except Exception as e:
        print(f"Transcription error: {e}")
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500

# --- TTS Routen (Nutzen tts_service) ---

@app.route('/api/tts_speak', methods=['POST'])
def tts_speak():
    data = request.get_json()
    text = data.get('text')
    mode = data.get('mode', 'openai')
    lang = data.get('lang', 'de')
    voice = data.get('voice', 'fable')

    if not text:
        return jsonify({'error': 'No text provided for TTS.'}), 400

    try:
        success = tts_service.speak(text, mode, lang, voice)
        
        if success:
            return jsonify({'status': 'Audio playback started'}), 200
        else:
            return jsonify({'error': 'TTS generation or playback failed.'}), 500
            
    except Exception as e:
        print(f"TTS error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/is_talking', methods=['GET'])
def is_talking_route():
    """Gibt zurück, ob der Roboter gerade spricht (TTS-Status)."""
    status = tts_service.get_talking_status()
    return jsonify({'is_talking': status}), 200

# --- LLM / History / Emotion Routen (KORRIGIERT FÜR llm_service.generate_response) ---

@app.route('/api/ask_llm', methods=['POST'])
def ask_llm_route():
    data = request.get_json()
    prompt = data.get('prompt')
    if not prompt:
        return jsonify({'error': 'No prompt provided.'}), 400
    
    # ⚠️ KORRIGIERT: Nutzt llm_service.generate_response
    # Gibt (response_text, executed_tool_calls) zurück
    response_text, executed_tools = llm_service.generate_response(prompt)
    
    if response_text and response_text.startswith("Error:"):
        # Fehlerbehandlung, falls generate_response einen Fehler-String zurückgibt
        return jsonify({'error': response_text}), 500
        
    # Rückgabe im neuen Format (kombiniert mit explizit ausgeführten Tools)
    # Beachte: Die finale Emotion wird implizit über get_emotion abgerufen (siehe Test-Skript)
    response_data = {
        "response": response_text,
        "executed_tools": executed_tools
    }
    
    return jsonify(response_data), 200

@app.route('/api/llm_system_message', methods=['POST'])
def set_system_message():
    data = request.get_json()
    message = data.get('system_message')
    llm_service.set_system_message(message)
    return jsonify({'status': 'System message updated'}), 200

@app.route('/api/llm_history_clear', methods=['POST'])
def clear_history():
    llm_service.clear_history()
    return jsonify({'status': 'Conversation history cleared'}), 200

@app.route('/api/llm_history', methods=['GET', 'POST'])
def llm_history():
    if request.method == 'GET':
        return jsonify({'history': llm_service.get_history()}), 200
    
    elif request.method == 'POST':
        data = request.get_json()
        new_history = data.get('history', [])
        turns_set = llm_service.set_history(new_history)
        return jsonify({'status': 'History replaced', 'turns_set': turns_set}), 200

@app.route('/api/get_emotion', methods=['GET'])
def get_emotion_route():
    """Gibt die zuletzt vom LLM vorgeschlagene Emotion zurück."""
    emotion = llm_service.get_last_emotion()
    return jsonify({'emotion': emotion}), 200

@app.route('/api/set_allowed_emotions', methods=['POST'])
def set_allowed_emotions_route():
    """Setzt die Liste der erlaubten Emotionen für das LLM."""
    data = request.get_json()
    emotions = data.get('emotions', [])
    llm_service.set_allowed_emotions(emotions)
    return jsonify({'status': 'success', 'emotions_updated': emotions}), 200

@app.route('/api/get_allowed_emotions', methods=['GET'])
def get_allowed_emotions_route():
    """Gibt die Liste der aktuell erlaubten Emotionen zurück."""
    emotions = llm_service.get_allowed_emotions()
    return jsonify({'emotions': emotions}), 200


if __name__ == '__main__':
    print("--- Initializing AI Services ---")
    # Initialisierung der Services (Sampling Rate)
    try:
        hearing_service.initialize_samplerate()
    except Exception as e:
        print(f"Warning: Could not initialize hearing_service samplerate: {e}")
        
    print("--- Starting PiBot AI Server on 0.0.0.0:5000 (Static Web + API) ---")
    # use_reloader=False ist wichtig für threading/Hintergrunddienste
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)