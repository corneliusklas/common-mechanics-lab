# camera_tools.py
#
# Dieses Modul stellt Funktionen für den Kamerazugriff auf USB-Kameras (z.B. Stereo-Kameras)
# bereit. Es ist für die Verwendung mit einem multimodalen LLM konzipiert und liefert
# das aufgenommene Bild direkt als Base64-kodierten JSON-Payload zurück.

import time
import os
import datetime
import json
import base64
import mimetypes
from typing import Optional, Tuple, Dict, Any

# Versuche, die OpenCV-Bibliothek zu importieren (notwendig für USB-Kameras)
try:
    import cv2
    CAMERA_IS_AVAILABLE = True
except ImportError:
    # Wenn cv2 nicht installiert ist, verwenden wir nur eine Platzhalter-Logik.
    CAMERA_IS_AVAILABLE = False

class CameraTools:
    """
    Stellt Funktionen für den Kamerazugriff bereit, die vom LLM als Tools aufgerufen werden.
    Nutzt OpenCV für USB-Kameras und liefert Base64-kodierte Bilder zurück.
    """

    # --- KONFIGURATIONSOPTIONEN FÜR DIE KAMERA ---
    # Optimale Auflösung für Side-by-Side-Stereo
    STEREO_WIDTH = 2560
    STEREO_HEIGHT = 720
    
    def __init__(self):
        # Definiert und erstellt den Ordner für die Bilder
        self.output_dir = "captured_usb_images"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
    def _path_to_base64(self, filepath: str) -> Tuple[Optional[str], Optional[str]]:
        """ 
        Konvertiert eine lokale Datei in Base64 und bestimmt den MIME-Typ. 
        Dies wird benötigt, um das Bild an multimodale LLMs zu senden.
        """
        if not os.path.exists(filepath):
            print(f"ERROR: File not found at {filepath}")
            return None, None
            
        try:
            with open(filepath, "rb") as f:
                # Base64-Kodierung der Binärdaten
                encoded_data = base64.b64encode(f.read()).decode("utf-8")
            
            # MIME-Typ anhand der Dateiendung erraten
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                mime_type = "image/jpeg" # Fallback für JPG
                
            print(f"DEBUG: File {filepath} successfully converted to Base64 with MIME type {mime_type}.")
            return encoded_data, mime_type
            
        except Exception as e:
            print(f"ERROR: Failed to read or encode file {filepath}: {e}")
            return None, None

    def capture_camera_image(self, camera_id: Optional[int] = 0) -> str:
        """
        Nimmt ein Bild von einer spezifischen USB-Kamera auf, speichert es und gibt 
        ein JSON-Objekt mit den Base64-kodierten Bilddaten zurück.

        Args:
            camera_id (int, optional): Der Index (ID) der zu verwendenden Kamera. 
                                       0 für links (Monobild), 1 für rechts (Monobild).
                                       Jeder andere Wert liefert das volle Side-by-Side Stereobild.

        Returns:
            str: Eine JSON-stringifizierte Antwort, die Base64-Daten für das LLM enthält.
        """
        if camera_id is None:
            camera_id = 0
            
        if not isinstance(camera_id, int) or camera_id < 0:
            return json.dumps({"status": "error", "message": "Fehler: camera_id muss eine positive Ganzzahl sein."})

        filepath = None
        base64_data = None
        mime_type = "image/jpeg"
        status = "error" # Default status

        # --- KAMERA VORBEREITUNG UND AUFNAHME ---
        if not CAMERA_IS_AVAILABLE:
            # --- PLATZHALTER LOGIK ---
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"placeholder_usb_cam_{camera_id}_{timestamp_str}.txt"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w') as f:
                f.write(f"Dies ist ein simuliertes Bild von USB Kamera {camera_id}.")
                
            message = (f"Bild erfolgreich (Simuliert/Platzhalter) von USB Kamera {camera_id} aufgenommen. "
                       f"Gespeichert unter: {filepath}. Bitte 'opencv-python' installieren.")
            base64_data = "U3VtbGF0ZWQgQ29udGVudA==" # Simulierter Base64-Text
            mime_type = "text/plain" 
            status = "simulated"
            
        else:
            # --- AKTUELLE USB KAMERA LOGIK ---
            device_to_open = 0 
            cap = cv2.VideoCapture(device_to_open) 
            
            if not cap.isOpened():
                return json.dumps({"status": "error", "message": f"Fehler: Konnte USB Kamera mit Index {device_to_open} nicht öffnen."})

            try:
                # Setze explizit den MJPG-Codec und die Stereo-Auflösung
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.STEREO_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.STEREO_HEIGHT)
                
                actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                
                time.sleep(1) 
                
                ret, frame = cap.read()
                
                if not ret:
                    raise IOError("Konnte keinen Frame lesen.")
                
                # CROPPING-LOGIK
                if actual_width >= self.STEREO_WIDTH / 2: 
                    half_width = actual_width // 2
                    
                    if camera_id == 0:
                        frame = frame[:, :half_width] # Linke Kamera
                    elif camera_id == 1:
                        frame = frame[:, half_width:] # Rechte Kamera
                    # Sonst: Volles Side-by-Side Frame
                
                # Definiere Dateiname und speichere Frame
                timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"usb_image_cam{camera_id}_{timestamp_str}.jpg" 
                filepath = os.path.join(self.output_dir, filename)
                
                cv2.imwrite(filepath, frame)

                message = f"Bild erfolgreich von Index {camera_id} aufgenommen und gespeichert."
                status = "success"
                
            except Exception as e:
                return json.dumps({"status": "error", "message": f"Fehler bei der Bildaufnahme: {e}"})

            finally:
                cap.release()

            # --- Base64-Kodierung der gespeicherten Datei ---
            # Wird nur ausgeführt, wenn filepath gesetzt und erfolgreich gespeichert wurde
            if filepath:
                base64_data, mime_type = self._path_to_base64(filepath)
            
                if not base64_data:
                    status = "partial_success"
                    message = f"Bild gespeichert, aber Base64-Kodierung fehlgeschlagen. Fehler: {message}"
        
        # --- ERGEBNIS ALS JSON ZURÜCKGEBEN ---
        response_data: Dict[str, Any] = {
            "status": status,
            "message": message,
            "file_path": filepath,
            # Dies ist der Schlüssel, den der LLM-Service (im Hintergrund) suchen muss, 
            # um die Bilddaten in den API-Call zu injizieren.
            "multimodal_payload": {
                "base64_data": base64_data,
                "mime_type": mime_type
            }
        }
        
        # Gebe das Ergebnis als JSON-String zurück
        return json.dumps(response_data)

    def start_live_stereo_stream(self):
        """
        Startet einen kontinuierlichen Live-Stream, der das unbeschnittene
        2560x720 Side-by-Side-Bild der Stereo-Kamera anzeigt.
        
        WICHTIG: Diese Funktion blockiert und öffnet ein externes cv2.imshow()-Fenster.
        Sie ist nur für lokale Tests gedacht. Zum Beenden 'q' im Fenster drücken.
        """
        if not CAMERA_IS_AVAILABLE:
            print("ERROR: OpenCV ist nicht verfügbar. Live-Stream kann nicht gestartet werden.")
            return "ERROR: OpenCV ist nicht verfügbar. Live-Stream kann nicht gestartet werden."

        device_to_open = 0 
        cap = cv2.VideoCapture(device_to_open)

        if not cap.isOpened():
            print(f"ERROR: Konnte USB Kamera (Index {device_to_open}) nicht öffnen.")
            return f"ERROR: Konnte USB Kamera (Index {device_to_open}) nicht öffnen."

        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.STEREO_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.STEREO_HEIGHT)

            print(f"INFO: Streaming gestartet. Drücken Sie 'q' im Fenster, um zu beenden.")
            time.sleep(1) 

            while True:
                ret, frame = cap.read()
                if not ret:
                    print("Stream Ende oder Fehler beim Lesen des Frames.")
                    break
                
                cv2.imshow('LIVE STEREO FEED - Q zum Beenden', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        except Exception as e:
            print(f"ERROR während des Streamings: {e}")
            return f"ERROR während des Streamings: {e}"

        finally:
            cap.release()
            cv2.destroyAllWindows()
            return "Live-Stream beendet und Fenster geschlossen."


# --- EXPORTS FÜR LLM-TOOLS ---

TOOL_FUNCTIONS = {
    "capture_camera_image": CameraTools().capture_camera_image
}

def get_tool_schemas():
    """
    Gibt das LLM Function calling Schema für das Kamera-Tool zurück.
    """
    return [{
        "type": "function",
        "function": {
            "name": "capture_camera_image",
            "description": "Nimmt ein Foto auf und sendet es an das LLM zur Analyse. Verwenden Sie den Parameter 'camera_id', um zwischen Monobild (0 oder 1) und Stereobild (jeder andere Wert) zu wählen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_id": {
                        "type": "integer",
                        "description": "Der Index (ID) der Ansicht: 0 für linke Monobild-Ansicht, 1 für rechte Monobild-Ansicht. Jeder andere Wert (z.B. 2) liefert das unbeschnittene Side-by-Side-Stereobild."
                    }
                },
                "required": [],
            },
        },
    }]

# --- INTERACTIVE TEST MODE ---
if __name__ == "__main__":
    tools = CameraTools()
    print("--- CAMERA TOOL TEST MODE: DEMO CAPTURE ---")
    
    # Der Rückgabewert sollte ein JSON-String sein
    print("\nAttempting to take photo from Camera Index 0 (Linke Ansicht - Monobild)...")
    result_json_str = tools.capture_camera_image(camera_id=0)
    
    print("\n--- CAPTURE RESULT (JSON String) ---")
    print(result_json_str)
    
    try:
        # Versuche, den JSON-String zu parsen, um den Payload zu überprüfen
        result_data = json.loads(result_json_str)
        print("\n--- PARSED JSON CONTENT ---")
        print(f"Status: {result_data.get('status')}")
        print(f"File Path: {result_data.get('file_path')}")
        payload = result_data.get('multimodal_payload')
        if payload and payload.get('base64_data'):
            print(f"Base64 Data present: YES (MIME: {payload.get('mime_type')})")
        else:
            print("Base64 Data present: NO")
    except json.JSONDecodeError:
        print("\nERROR: Failed to decode JSON result.")

    print("\nDie Logik der Base64-Kodierung befindet sich nun in dieser Datei.")
