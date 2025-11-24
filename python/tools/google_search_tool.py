# tools/google_search_tool.py
import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv() 
# Reads the key from the environment (e.g., from /etc/environment or .env)
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

def perform_google_search(query: str):
    """
    Performs a Google search using the Serper API via a direct HTTP request.
    It returns structured data (local, weather) or general snippets.
    """
    if not SERPER_API_KEY:
        return "Error: SERPER_API_KEY is not configured."
    
    output = []
    
    try:
        # Direct HTTP call to the Serper API
        url = "https://google.serper.dev/search"
        
        # Configured parameters for German, localized results
        payload = json.dumps({
            "q": query,
            "location": "Germany", 
            "hl": "de",
            "gl": "de"
        })
        
        headers = {
            'X-API-KEY': SERPER_API_KEY, # Authentication via Header
            'Content-Type': 'application/json'
        }
        
        # Send the POST request
        response = requests.request("POST", url, headers=headers, data=payload)
        response.raise_for_status() # Raises an exception for 4xx/5xx status codes
        
        results = response.json()
        
        # --- CORRECTED DEBUG CHECK ---
        # Correct check for all relevant fields, including 'organic'
        has_relevant_data = any(k in results for k in ["local_results", "weather", "organic", "answer_box"])

        if "error" in results or not has_relevant_data:
            # Debugging print statement if no data is returned
            print(f"❌ SERPER ERROR OR EMPTY RESULTS FOR: {query}")
            
            if "error" in results:
                return f"Error from Serper API: {results['error']}"
            
            return "Google Search could not provide relevant results."
        # --- END DEBUG CHECK ---

        # 1. Prioritize Specific Results (Answer Box, Local/Maps, Weather)
        
        if "answer_box" in results and "answer" in results["answer_box"]:
             output.append(f"--- Direct Answer ---\n{results['answer_box']['answer']}")

        if "local_results" in results:
            output.append("\n--- Local Results (Address/Contact) ---")
            for i, item in enumerate(results["local_results"][:2]):
                title = item.get("title", "Unknown")
                address = item.get("address", "No Address")
                phone = item.get("phone", "No Phone Number")
                output.append(f"{i+1}. {title}\n  Address: {address}\n  Phone: {phone}")

        if "weather" in results:
            weather = results["weather"]
            output.append("\n--- Weather Data ---")
            output.append(f"Location: {weather.get('location')}, {weather.get('temperature')}°C, {weather.get('forecast')}")

        # 2. General Snippets (using 'organic' field correctly)
        if "organic" in results:
            if not output: 
                 output.append("--- General Search Results ---")
            else:
                 output.append("\n--- Additional Search Results ---")

            for item in results["organic"][:3]:
                title = item.get("title", "No Title")
                snippet = item.get("snippet", "No Snippet available")
                source = item.get("source", "")
                
                # We clean up Unicode sequences provided by Serper (like \u00b7)
                snippet = snippet.replace('\\u00b7', '·')
                
                output.append(f"Title: {title}\nContent: {snippet}\nSource: {source}")


        if not output:
            return "Google Search could not provide relevant results."

        return "\n".join(output)

    except requests.exceptions.HTTPError as e:
        # Catches errors like 429 (Quota Exceeded)
        return f"HTTP Error from Serper (Possibly Quota Exceeded): {e}"
    except Exception as e:
        return f"Severe error during Google Search: {str(e)}"

# --- EXPORTS FOR THE AUTO-LOADER ---

TOOL_FUNCTIONS = {
    "perform_google_search": perform_google_search
}

def get_tool_schemas():
    return [{
        "type": "function",
        "function": {
            "name": "perform_google_search",
            "description": "Performs a Google search for all requests needing current facts, news, local information (address, phone number), or weather.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "The complete search term for Google, e.g., 'Current DAX Index' or 'Dr. Friedrich Karlsruhe phone number'."
                    }
                },
                "required": ["query"],
            },
        },
    }]

# --- INTERACTIVE TEST MODE (for direct file execution) ---
if __name__ == "__main__":
    print("\n--- GOOGLE SEARCH TEST MODE (Final) ---")
    if not SERPER_API_KEY:
        print("❌ Please set SERPER_API_KEY in the environment.")
    else:
        # Test 1: Local Search
        print("\nTesting local search:")
        ergebnis_lokal = perform_google_search("Dr. Friedrich Karlsruhe Telefonnummer")
        print("\n--- LOCAL RESULT ---\n" + ergebnis_lokal)
        
        # Test 2: General Search
        print("\nTesting general search:")
        ergebnis_allgemein = perform_google_search("Aktueller DAX Stand")
        print("\n--- GENERAL RESULT ---\n" + ergebnis_allgemein)