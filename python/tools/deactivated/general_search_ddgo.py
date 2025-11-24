# tools/general_search.py
from ddgs import DDGS 
import logging

# Unterdrücke Warnungen der Such-Bibliothek, falls vorhanden
logging.getLogger("ddgs").setLevel(logging.ERROR)

def perform_general_search(query: str):
    """
    Sucht mit DuckDuckGo nach allgemeinen aktuellen Informationen im Internet (Nachrichten, Fakten).
    """
    print(f"DEBUG: Allgemeine Suche nach: {query}")
    try:
        results = []
        with DDGS() as ddgs:
            # WICHTIG: Region auf Deutsch festlegen, um irrelevante Sprachen zu vermeiden
            ddgs_gen = ddgs.text(query, region='de-de', max_results=3) 
            if ddgs_gen:
                results = list(ddgs_gen)

        if not results:
            return "Keine relevanten Suchergebnisse gefunden."

        formatted_results = []
        for r in results:
            title = r.get('title', 'Ohne Titel')
            body = r.get('body', '')
            href = r.get('href', '')
            
            if body:
                formatted_results.append(f"Titel: {title}\nInhalt: {body}\nLink: {href}")
        
        return "\n---\n".join(formatted_results)

    except Exception as e:
        return f"Fehler bei der allgemeinen Suche: {str(e)}"

# --- EXPORTS (bleiben gleich) ---

TOOL_FUNCTIONS = {
    "perform_general_search": perform_general_search
}

def get_tool_schemas():
    return [{
        "type": "function",
        "function": {
            "name": "perform_general_search",
            "description": "Führt eine allgemeine Internetsuche für Fakten, Nachrichten oder Ereignisse durch. NICHT für lokale Informationen (Adresse, Telefon) oder Wetter nutzen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Der Suchbegriff."}
                },
                "required": ["query"],
            },
        },
    }]

if __name__ == "__main__":
    print("\n--- TEST: ALLGEMEINE SUCHE ---")
    print(perform_general_search("Aktueller Bitcoin-Kurs"))
    print("----------------------------")