# vision_tools.py
#
# This module provides functions for accessing USB cameras (e.g., stereo cameras).
# It is designed to interface with a multimodal LLM by delivering the captured
# image directly as a Base64-encoded JSON payload for immediate analysis, representing
# the robot's visual perception.

import time
import os
import datetime
import json
import base64
import mimetypes
from typing import Optional, Tuple, Dict, Any

# Attempt to import the OpenCV library (necessary for USB cameras)
try:
    import cv2
    CAMERA_IS_AVAILABLE = True
except ImportError:
    # If cv2 is not installed, use placeholder logic only.
    CAMERA_IS_AVAILABLE = False

class VisionTools:
    """
    Provides camera access functions invoked by the LLM as tools.
    Uses OpenCV for USB cameras and returns Base64-encoded images.
    """

    # --- CAMERA CONFIGURATION OPTIONS ---
    # Optimal resolution for Side-by-Side stereo
    STEREO_WIDTH = 2560
    STEREO_HEIGHT = 720
    
    def __init__(self):
        # Define and create the folder for captured images
        self.output_dir = "captured_usb_images"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
    def _path_to_base64(self, filepath: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Converts a local file to Base64 and determines the MIME type.
        This is required to send the image to multimodal LLMs.
        """
        if not os.path.exists(filepath):
            print(f"ERROR: File not found at {filepath}")
            return None, None
            
        try:
            with open(filepath, "rb") as f:
                # Base64 encoding of binary data
                encoded_data = base64.b64encode(f.read()).decode("utf-8")
            
            # Guess MIME type based on file extension
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                mime_type = "image/jpeg" # Fallback for JPG
                
            print(f"DEBUG: File {filepath} successfully converted to Base64 with MIME type {mime_type}.")
            return encoded_data, mime_type
            
        except Exception as e:
            print(f"ERROR: Failed to read or encode file {filepath}: {e}")
            return None, None

    def capture_robot_vision_frame(self, camera_id: Optional[int] = 0) -> str:
        """
        Captures an image from a specific USB camera, saves it, and returns
        a JSON object with the Base64-encoded image data for LLM analysis.
        
        This function represents the robot's primary visual input.

        Args:
            camera_id (int, optional): The index (ID) of the view to use.
                                       0 for left (mono image), 1 for right (mono image).
                                       Any other value provides the full side-by-side stereo image.

        Returns:
            str: A JSON-stringified response containing Base64 data for the LLM.
        """
        if camera_id is None:
            camera_id = 0
            
        if not isinstance(camera_id, int) or camera_id < 0:
            return json.dumps({"status": "error", "message": "Error: camera_id must be a positive integer."})

        filepath = None
        base64_data = None
        mime_type = "image/jpeg"
        status = "error" # Default status

        # --- CAMERA PREPARATION AND CAPTURE ---
        if not CAMERA_IS_AVAILABLE:
            # --- PLACEHOLDER LOGIC ---
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"placeholder_robot_cam_{camera_id}_{timestamp_str}.txt"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w') as f:
                f.write(f"This is a simulated image from the robot's camera view {camera_id}.")
                
            message = (f"Image successfully captured (Simulated/Placeholder) from camera view {camera_id}. "
                       f"Saved to: {filepath}. Please install 'opencv-python' to enable live capture.")
            base64_data = "U3VtbGF0ZWQgQ29udGVudA==" # Simulated Base64 text
            mime_type = "text/plain" 
            status = "simulated"
            
        else:
            # --- ACTUAL USB CAMERA LOGIC ---
            device_to_open = 0 
            cap = cv2.VideoCapture(device_to_open) 
            
            if not cap.isOpened():
                return json.dumps({"status": "error", "message": f"Error: Could not open USB camera with index {device_to_open}."})

            try:
                # Explicitly set MJPG codec and stereo resolution
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.STEREO_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.STEREO_HEIGHT)
                
                actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                
                time.sleep(1) 
                
                ret, frame = cap.read()
                
                if not ret:
                    raise IOError("Could not read a frame.")
                
                # CROPPING LOGIC
                if actual_width >= self.STEREO_WIDTH / 2: 
                    half_width = actual_width // 2
                    
                    if camera_id == 0:
                        frame = frame[:, :half_width] # Left Camera View
                    elif camera_id == 1:
                        frame = frame[:, half_width:] # Right Camera View
                    # Else: Full Side-by-Side Frame
                
                # Define filename and save frame
                timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"robot_vision_cam{camera_id}_{timestamp_str}.jpg" 
                filepath = os.path.join(self.output_dir, filename)
                
                cv2.imwrite(filepath, frame)

                message = f"Image successfully captured from view index {camera_id} and saved."
                status = "success"
                
            except Exception as e:
                return json.dumps({"status": "error", "message": f"Error during image capture: {e}"})

            finally:
                cap.release()

            # --- Base64 Encoding of the saved file ---
            # Only executes if filepath is set and saving was successful
            if filepath:
                base64_data, mime_type = self._path_to_base64(filepath)
                
                if not base64_data:
                    status = "partial_success"
                    message = f"Image saved, but Base64 encoding failed. Error: {message}"
        
        # --- RETURN RESULT AS JSON ---
        response_data: Dict[str, Any] = {
            "status": status,
            "message": message,
            "file_path": filepath,
            # This is the key the LLM service (in the background) must look for
            # to inject the image data into the API call.
            "multimodal_payload": {
                "base64_data": base64_data,
                "mime_type": mime_type
            }
        }
        
        # Return the result as a JSON string
        return json.dumps(response_data)

    def start_live_stereo_stream(self):
        """
        Starts a continuous live stream displaying the uncropped
        2560x720 side-by-side stereo camera image.
        
        IMPORTANT: This function blocks and opens an external cv2.imshow() window.
        It is intended for local testing only. Press 'q' in the window to quit.
        """
        if not CAMERA_IS_AVAILABLE:
            print("ERROR: OpenCV is not available. Live stream cannot be started.")
            return "ERROR: OpenCV is not available. Live stream cannot be started."

        device_to_open = 0 
        cap = cv2.VideoCapture(device_to_open)

        if not cap.isOpened():
            print(f"ERROR: Could not open USB camera (Index {device_to_open}).")
            return f"ERROR: Could not open USB camera (Index {device_to_open}) not opened."

        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.STEREO_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.STEREO_HEIGHT)

            print(f"INFO: Streaming started. Press 'q' in the window to quit.")
            time.sleep(1) 

            while True:
                ret, frame = cap.read()
                if not ret:
                    print("Stream end or error reading frame.")
                    break
                
                cv2.imshow('LIVE STEREO FEED - Q to Quit', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        except Exception as e:
            print(f"ERROR during streaming: {e}")
            return f"ERROR during streaming: {e}"

        finally:
            cap.release()
            cv2.destroyAllWindows()
            return "Live stream ended and window closed."


# --- EXPORTS FOR LLM TOOLS ---

# Initialize the VisionTools class
_vision_tools_instance = VisionTools()

TOOL_FUNCTIONS = {
    # Renamed the function to reflect 'vision' capability
    "capture_robot_vision_frame": _vision_tools_instance.capture_robot_vision_frame
}

def get_tool_schemas():
    """
    Returns the LLM Function calling Schema for the Vision Tool.
    """
    return [{
        "type": "function",
        "function": {
            "name": "capture_robot_vision_frame",
            "description": "Captures a still image from the robot's perspective and sends it to the LLM for analysis (visual perception). The LLM should automatically use this when the user asks 'What do you see?' or similar questions requiring visual input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_id": {
                        "type": "integer",
                        "description": "The index (ID) of the view: 0 for left monocular view, 1 for right monocular view. Any other value (e.g., 2) provides the uncropped side-by-side stereo image."
                    }
                },
                "required": [],
            },
        },
    }]

# --- INTERACTIVE TEST MODE ---
if __name__ == "__main__":
    print("--- VISION TOOL TEST MODE: DEMO CAPTURE ---")
    
    # The return value should be a JSON string
    print("\nAttempting to take photo from Camera Index 0 (Left Monocular View)...")
    result_json_str = _vision_tools_instance.capture_robot_vision_frame(camera_id=0)
    
    print("\n--- CAPTURE RESULT (JSON String) ---")
    print(result_json_str)
    
    try:
        # Attempt to parse the JSON string to verify the payload
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
    
    print("\nBase64 encoding logic is contained within this file.")