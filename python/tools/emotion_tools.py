# Globaler State für dieses Modul
DEFAULT_EMOTIONS = ["happy", "sad", "neutral"]
current_allowed_emotions = DEFAULT_EMOTIONS.copy()
last_recognized_emotion = "neutral"

def set_face_emotion(emotion: str):
    """
    Speichert die vom LLM gewählte Emotion.
    """
    global last_recognized_emotion
    if emotion in current_allowed_emotions:
        last_recognized_emotion = emotion
        return f"Emotion '{emotion}' erfolgreich gesetzt."
    return f"Fehler: Emotion '{emotion}' ist nicht erlaubt."

# Hilfsfunktionen für den Service (damit llm_service darauf zugreifen kann)
def get_last_emotion():
    return last_recognized_emotion

def set_allowed_emotions(emotion_list):
    global current_allowed_emotions
    current_allowed_emotions = [str(e).lower() for e in emotion_list]
    return True

def get_allowed_emotions():
    return current_allowed_emotions

# --- EXPORTS FÜR DEN AUTO-LOADER ---

TOOL_FUNCTIONS = {
    "set_face_emotion": set_face_emotion
}

def get_tool_schemas():
    """Generiert das Schema dynamisch basierend auf current_allowed_emotions."""
    return [{
        "type": "function",
        "function": {
            "name": "set_face_emotion",
            "description": "Steuert den Gesichtsausdruck des Roboters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emotion": {
                        "type": "string",
                        "enum": current_allowed_emotions, # Hier wird die dynamische Liste genutzt
                        "description": "Der gewünschte Gesichtsausdruck.",
                    }
                },
                "required": ["emotion"],
            },
        },
    }]