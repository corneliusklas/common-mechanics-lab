# tts_service.py
# -------------------------------------------------------------------------------------------------
# Text-to-Speech (TTS) Service for PiBot
#
# PURPOSE: Provides a unified API endpoint for converting text to speech using various engines.
#
# ENGINES:
# - OpenAI TTS: High-quality, cloud-based speech synthesis.
# - gTTS (Google TTS): Cloud-based synthesis (requires internet).
# - Espeak: Local, lightweight TTS engine (for offline capability).
#
# FUNCTIONALITY:
# - Caching mechanism: Stores generated audio files locally to save API calls and bandwidth.
# - Modulated playback: Includes logic to modulate audio output (e.g., lower frequency) if required.
# - Status tracking: Manages the 'is_talking' state for real-time reporting to the frontend.
# -------------------------------------------------------------------------------------------------

import subprocess
import os
import time
import hashlib
import json
import numpy as np
import scipy.io.wavfile as wav
from gtts import gTTS 
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- CONFIGURATION ---
CACHE_DIR = os.path.expanduser("~/.local/share/tts_cache")
MAX_OPENAI_REQUESTS = 100
MAX_CACHE_FILES = 200 # LRU: löscht älteste Dateien
MODULATED_OUTPUT_WAV = os.path.join(CACHE_DIR, "modulated_output.wav") # Zentraler Pfad für die modulierte Datei

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# --- GLOBAL STATE ---
openai_request_count = 0
tts_cache_index_path = os.path.join(CACHE_DIR, "index.json")
tts_cache_index = {}
is_talking_state = False 

# Load index if exists
if os.path.exists(tts_cache_index_path):
    with open(tts_cache_index_path, "r", encoding="utf-8") as f:
        tts_cache_index = json.load(f)

# --- STATUS MANAGEMENT ---

def get_talking_status():
    """Gibt den aktuellen Sprechstatus (True/False) zurück."""
    global is_talking_state
    return is_talking_state

# --- UTILITY FUNCTIONS ---
def save_index():
    with open(tts_cache_index_path, "w", encoding="utf-8") as f:
        json.dump(tts_cache_index, f)

def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def prune_cache():
    """LRU: löscht alte Dateien, wenn MAX_CACHE_FILES überschritten"""
    if len(tts_cache_index) <= MAX_CACHE_FILES:
        return
    sorted_items = sorted(tts_cache_index.items(), key=lambda x: x[1]["timestamp"])
    for key, info in sorted_items[: len(tts_cache_index) - MAX_CACHE_FILES]:
        try:
            os.remove(info["path"])
        except FileNotFoundError:
            pass
        del tts_cache_index[key]
    save_index()

def play_audio_ffplay(file_path):
    """Spielt eine Audio-Datei mit ffplay ab und aktualisiert den globalen Sprechstatus."""
    global is_talking_state
    
    if not os.path.exists(file_path):
        print(f"❌ Fehler: Audio-Datei nicht gefunden unter {file_path}")
        return False

    is_talking_state = True
    
    try:
        subprocess.run(
            ['ffplay', '-nodisp', '-autoexit', '-hide_banner', '-loglevel', 'error', file_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return True
    except Exception as e:
        print(f"❌ Audio playback error: {e}")
        return False
    finally:
        is_talking_state = False

def convert_mp3_to_wav_ffmpeg(input_mp3, output_wav):
    """Konvertiert MP3 zu 44100Hz WAV (notwendig für die Ringmodulation)."""
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', input_mp3, '-acodec', 'pcm_s16le', '-ar', '44100', output_wav],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return True
    except Exception as e:
        print(f"❌ MP3→WAV conversion error: {e}")
        return False

def apply_ring_modulation(input_file, output_file, frequency=80, depth=0.5):
    """Wendet Ringmodulation auf die Audio-Daten an und speichert das Ergebnis."""
    rate, data = wav.read(input_file)
    data = np.array(data)
    if len(data.shape) > 1:
        data = data[:, 0]
    t = np.arange(len(data)) / rate
    modulator = np.sin(2 * np.pi * frequency * t)
    modulated_data = (1 - depth) * data + depth * (data * modulator)
    abs_max = np.max(np.abs(modulated_data)) or 1
    scaling_factor = 32767.0 / abs_max
    modulated_data = np.int16(modulated_data * scaling_factor)
    wav.write(output_file, rate, modulated_data)

# -------------------------
# --- TTS IMPLEMENTATIONS ---
# -------------------------

def say_with_gtts(text, lang="de"):
    """Generiert Audio mit gTTS, moduliert es und spielt es ab."""
    if not text.strip():
        print("Empty text, skipping TTS.")
        return False
        
    hash_val = hashlib.sha256(text.encode('utf-8')).hexdigest()
    temp_mp3_path = os.path.join(CACHE_DIR, f"gtts_{hash_val}.mp3")
    temp_wav_path = os.path.join(CACHE_DIR, f"gtts_{hash_val}.wav")
    
    try:
        print("⚙️ Generating TTS with gTTS...")
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(temp_mp3_path)
        
        if not convert_mp3_to_wav_ffmpeg(temp_mp3_path, temp_wav_path):
             return False
             
        # NEU: Modulation auf gTTS-Audio anwenden
        apply_ring_modulation(temp_wav_path, MODULATED_OUTPUT_WAV)
        
        print("▶️ Playing modulated gTTS audio...")
        return play_audio_ffplay(MODULATED_OUTPUT_WAV)

    except Exception as e:
        print(f"❌ gTTS error: {e}.")
        return False
    finally:
        # Aufräumen der temporären Dateien
        if os.path.exists(temp_mp3_path): os.remove(temp_mp3_path)
        if os.path.exists(temp_wav_path): os.remove(temp_wav_path)


def say_with_openai(text, voice="fable", model="tts-1"):
    """Generiert Audio mit OpenAI TTS, cacht, moduliert und spielt ab."""
    global openai_request_count
    if not text.strip():
        return False

    text_hash = hash_text(text)
    
    # 1. Check cache
    if text_hash in tts_cache_index:
        wav_path = tts_cache_index[text_hash]["path"]
        tts_cache_index[text_hash]["timestamp"] = time.time()
        save_index()
        print("✅ Playing cached audio.")
        return play_audio_ffplay(wav_path)

    # 2. Check if OpenAI limit reached
    if openai_request_count >= MAX_OPENAI_REQUESTS:
        print("⚠️ OpenAI request limit reached, falling back to espeak.")
        return speak_with_espeak(text)[0] 

    # 3. Generate TTS via OpenAI
    mp3_path = os.path.join(CACHE_DIR, f"{text_hash}.mp3")
    wav_path = os.path.join(CACHE_DIR, f"{text_hash}.wav")
    try:
        print("⚙️ Generating TTS with OpenAI...")
        response = client.audio.speech.create(model=model, voice=voice, input=text)
        
        with open(mp3_path, "wb") as f:
            f.write(response.content)
        if not convert_mp3_to_wav_ffmpeg(mp3_path, wav_path):
            return False

        # Apply modulation to the temporary WAV file
        apply_ring_modulation(wav_path, MODULATED_OUTPUT_WAV)
        openai_request_count += 1

        # Update cache (speichert Pfad zur modulierten Datei)
        tts_cache_index[text_hash] = {"path": MODULATED_OUTPUT_WAV, "timestamp": time.time()}
        prune_cache()
        save_index()
        
        print("▶️ Playing modulated audio...")
        return play_audio_ffplay(MODULATED_OUTPUT_WAV)
    except Exception as e:
        print(f"❌ OpenAI TTS error: {e}. Falling back to gTTS.")
        # Fallback auf gTTS
        return say_with_gtts(text, lang='de')
    finally:
        # Clean temp MP3/WAV
        if os.path.exists(mp3_path): os.remove(mp3_path)
        if os.path.exists(wav_path): os.remove(wav_path)


# --- Local Espeak (SPIELT DIREKT AB) ---
def speak_with_espeak(text, lang="de"):
    """Uses the local espeak command for playback with specified language and updates status."""
    global is_talking_state
    
    if not text.strip():
        return False, None

    is_talking_state = True
    
    try:
        print("⚙️ Generating TTS with espeak...")
        subprocess.run(['espeak', f'-v{lang}', '-s', '130', text],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True, None
    except FileNotFoundError:
        print("❌ Fehler: 'espeak' Programm nicht gefunden. Bitte installieren Sie es.")
        return False, "espeak not found"
    except Exception as e:
        print(f"❌ espeak error: {e}")
        return False, str(e)
    finally:
        is_talking_state = False


def speak(text, mode="openai", lang="de", voice="fable"):
    """
    Main entry point for TTS.
    """
    if mode == "espeak":
        return speak_with_espeak(text, lang=lang)[0]
    elif mode == "openai":
        return say_with_openai(text, voice=voice)
    elif mode == "gtts":
        return say_with_gtts(text, lang=lang)
    else:
        print(f"❌ Unbekannter Modus {mode}")
        return False

# -------------------------
# --- INIT ON IMPORT / TEST ---
# -------------------------

if __name__ == "__main__":
    print("\n--- TTS Service Self-Test ---")
    
    import threading

    if OPENAI_API_KEY:
        # Test 1: OpenAI TTS (caching, modulation)
        test_text_openai = "Hallo, ich bin PiBot. Ich verwende die Fable-Stimme und teste Caching."
        print("\n[TEST 1] OpenAI TTS (mit Caching/Modulation)")
        
        # NEUE LÖSUNG: Cache-Eintrag für diesen Test-String löschen, um Konsistenz zu gewährleisten
        test_hash = hash_text(test_text_openai)
        if test_hash in tts_cache_index:
            del tts_cache_index[test_hash]
            save_index()
            print("   -> Vorhandener Cache-Eintrag für Test-String wurde entfernt.")
        
        # Jetzt sollte der erste Aufruf GENERIEREN (was die Datei anlegt)
        print("   -> Erster Aufruf (generiert):")
        say_with_openai(test_text_openai, voice='fable')
        
        # Nun sollte der zweite Aufruf den Cache finden und verwenden
        print("   -> Zweiter Aufruf (aus Cache):")
        say_with_openai(test_text_openai, voice='fable')

        # Test 2: gTTS und is_talking Statusprüfung (Polling-Methode)
        test_text_gtts = "Dies ist ein Test mit gTTS und Ringmodulation."
        print(f"\n[TEST 2] gTTS TTS und is_talking Statusprüfung")

        # Starte die Wiedergabe in einem separaten Thread
        t = threading.Thread(target=say_with_gtts, args=(test_text_gtts, 'de'))
        t.start()

        # Warten (Polling), bis der Status True ist, maximal 5 Sekunden
        timeout = time.time() + 5  
        while not get_talking_status() and time.time() < timeout:
            time.sleep(0.1)  

        # Prüfung 1: Status während Wiedergabe
        status_during_playback = get_talking_status()
        print(f"   Status während Wiedergabe: {status_during_playback}")
        assert status_during_playback == True, "❌ is_talking wurde nicht auf True gesetzt."

        t.join() 

        # Prüfung 2: Status nach Wiedergabe
        status_after_playback = get_talking_status()
        print(f"   Status nach Wiedergabe: {status_after_playback}")
        assert status_after_playback == False, "❌ is_talking wurde nicht auf False zurückgesetzt."

        print(f"✅ TTS/gTTS und is_talking Test abgeschlossen.")

    else:
        print("❌ OPENAI_API_KEY nicht gesetzt. OpenAI/gTTS-Tests übersprungen.")
    
    
    # Test 3: Espeak (unabhängig von OpenAI Key)
    test_text_espeak = "Hallo, dies ist ein Test mit espeak."
    print(f"\n[TEST 3] Espeak TTS und is_talking Statusprüfung")

    # Starte die Wiedergabe in einem separaten Thread
    t_espeak = threading.Thread(target=speak_with_espeak, args=(test_text_espeak, 'de'))
    t_espeak.start()

    # Warten (Polling), bis der Status True ist, maximal 5 Sekunden
    timeout = time.time() + 5  
    while not get_talking_status() and time.time() < timeout:
        time.sleep(0.1)  

    # Prüfung 1: Status während Wiedergabe
    status_during_espeak = get_talking_status()
    print(f"   Status während Wiedergabe: {status_during_espeak}")
    assert status_during_espeak == True, "❌ Espeak is_talking wurde nicht auf True gesetzt."

    t_espeak.join() 

    # Prüfung 2: Status nach Wiedergabe
    status_after_espeak = get_talking_status()
    print(f"   Status nach Wiedergabe: {status_after_espeak}")
    assert status_after_espeak == False, "❌ Espeak is_talking wurde nicht auf False zurückgesetzt."
    print(f"✅ Espeak Test abgeschlossen.")


    # Aufräumen der temporären modulierten Datei (falls vorhanden)
    if os.path.exists(MODULATED_OUTPUT_WAV):
        os.remove(MODULATED_OUTPUT_WAV)