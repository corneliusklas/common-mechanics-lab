import requests

def get_weather_forecast(city: str):
    """
    Holt das Wetter für eine Stadt via Open-Meteo (Kostenlos, kein Key).
    """
    try:
        # 1. Geocoding: Stadt in Koordinaten umwandeln
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=de&format=json"
        geo_res = requests.get(geo_url).json()
        
        if not geo_res.get("results"):
            return f"Konnte den Ort '{city}' nicht finden."
            
        location = geo_res["results"][0]
        lat = location["latitude"]
        lon = location["longitude"]
        name = location["name"]
        
        # 2. Wetterdaten abrufen
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current_weather=true&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&timezone=auto"
        )
        w_res = requests.get(weather_url).json()
        
        # 3. Daten formatieren
        current = w_res.get("current_weather", {})
        daily = w_res.get("daily", {})
        
        temp_now = current.get("temperature")
        wind = current.get("windspeed")
        
        # Vorhersage für heute (Index 0)
        max_temp = daily["temperature_2m_max"][0]
        min_temp = daily["temperature_2m_min"][0]
        rain_prob = daily["precipitation_probability_max"][0]
        
        return (
            f"Wetterbericht für {name}:\n"
            f"- Aktuell: {temp_now}°C, Windgeschwindigkeit {wind} km/h\n"
            f"- Heute: Max {max_temp}°C / Min {min_temp}°C\n"
            f"- Regenwahrscheinlichkeit: {rain_prob}%"
        )

    except Exception as e:
        return f"Fehler beim Wetterabruf: {e}"

# --- EXPORTS ---

TOOL_FUNCTIONS = {
    "get_weather_forecast": get_weather_forecast
}

def get_tool_schemas():
    return [{
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Ruft den aktuellen Wetterbericht und die Vorhersage für einen Ort ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Der Name der Stadt, z.B. 'Berlin'."}
                },
                "required": ["city"],
            },
        },
    }]

if __name__ == "__main__":
    print(get_weather_forecast("Berlin"))