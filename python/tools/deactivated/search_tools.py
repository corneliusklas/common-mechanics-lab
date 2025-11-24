# tools/web_tools.py
import logging

# Unterdrücke Warnungen der Such-Bibliothek, falls vorhanden
logging.getLogger("duckduckgo_search").setLevel(logging.ERROR)

from duckduckgo_search import DDGS

def perform_web_search(query: str):
    """
    Sucht mit DuckDuckGo nach Informationen.
    """
    # Debug-Ausgabe nur, wenn nicht direkt aufgerufen (optional)
    # print(f"DEBUG: Suche im Web nach: {query}")
    
    try:
        results = []
        # Context Manager verwenden für stabilere Verbindung
        with DDGS() as ddgs:
            # Suche nach Text
            ddgs_gen = ddgs.text(query, max_results=4)
            if ddgs_gen:
                results = list(ddgs_gen)

        if not results:
            return "Die Internetsuche hat leider keine Ergebnisse geliefert."

        formatted_results = []
        for r in results:
            title = r.get('title', 'Ohne Titel')
            body = r.get('body', '')
            href = r.get('href', '')
            
            # Nur Ergebnisse mit Inhalt nehmen
            if body:
                formatted_results.append(f"Titel: {title}\nInhalt: {body}\nLink: {href}")
        
        return "\n\n---\n\n".join(formatted_results)

    except Exception as e:
        return f"Fehler bei der Internetsuche: {str(e)}"

# --- EXPORTS FÜR DEN AUTO-LOADER ---

TOOL_FUNCTIONS = {
    "perform_web_search": perform_web_search
}

def get_tool_schemas():
    return [{
        "type": "function",
        "function": {
            "name": "perform_web_search",
            "description": "Nutze dieses Tool für aktuelle Informationen (Nachrichten, Fakten), die du nicht weißt. Nicht für Wetter nutzen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "Der Suchbegriff."
                    }
                },
                "required": ["query"],
            },
        },
    }]

# --- INTERAKTIVER TEST-MODUS ---
if __name__ == "__main__":
    print("\n--- WEB TOOL TEST MODUS ---")
    print("Gib einen Suchbegriff ein (oder 'exit' zum Beenden).")
    print("-" * 40)

    while True:
        user_input = input("\nDeine Suche: ").strip()
        
        if user_input.lower() in ["exit", "quit", "ende"]:
            print("Beende Test.")
            break
        
        if not user_input:
            continue

        print(f"Suche läuft für: '{user_input}'...")
        result = perform_web_search(user_input)
        
        print("\n--- ERGEBNIS ---")
        print(result)
        print("----------------")