#!/usr/bin/env python3
"""weather_server_simple.py - A simple weather MCP server using FastMCP"""

from mcp.server import FastMCP
from mcp.server.models import InitializationOptions
from datetime import datetime

# Create server instance
mcp = FastMCP("weather-server")

# Weather data for major cities
WEATHER_DATA = {
    "tokyo": {
        "current": {
            "temperature": 18,
            "condition": "Partly Cloudy",
            "humidity": 65,
            "wind_speed": 12,
            "feels_like": 17
        },
        "forecast": [
            {"day": "Today", "high": 20, "low": 15, "condition": "Partly Cloudy"},
            {"day": "Tomorrow", "high": 22, "low": 16, "condition": "Sunny"},
            {"day": "Day after", "high": 19, "low": 14, "condition": "Rainy"}
        ]
    },
    "osaka": {
        "current": {
            "temperature": 19,
            "condition": "Sunny",
            "humidity": 60,
            "wind_speed": 10,
            "feels_like": 18
        }
    },
    "kyoto": {
        "current": {
            "temperature": 17,
            "condition": "Cloudy",
            "humidity": 70,
            "wind_speed": 8,
            "feels_like": 16
        }
    }
}

@mcp.tool()
def get_current_weather(city: str) -> str:
    """Get current weather for a city.

    Args:
        city: City name (e.g., tokyo, osaka, kyoto)
    """
    city_lower = city.lower().strip()
    
    if city_lower not in WEATHER_DATA:
        available = ", ".join(WEATHER_DATA.keys())
        return f"City '{city}' not found. Available cities: {available}"
    
    data = WEATHER_DATA[city_lower]["current"]
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    return f"""🌤️ Current Weather in {city.title()} ({current_time}):

• Temperature: {data['temperature']}°C
• Feels like: {data['feels_like']}°C  
• Condition: {data['condition']}
• Humidity: {data['humidity']}%
• Wind Speed: {data['wind_speed']} km/h

Enjoy your day! ☀️"""

@mcp.tool()
def get_weather_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city.

    Args:
        city: City name (e.g., tokyo, osaka, kyoto)
        days: Number of days to forecast (1-3)
    """
    city_lower = city.lower().strip()
    
    if city_lower not in WEATHER_DATA:
        available = ", ".join(WEATHER_DATA.keys())
        return f"City '{city}' not found. Available cities: {available}"
    
    if "forecast" not in WEATHER_DATA[city_lower]:
        return f"No forecast available for {city.title()}"
    
    forecast_days = min(days, 3)
    forecast = WEATHER_DATA[city_lower]["forecast"][:forecast_days]
    
    result = f"📅 {forecast_days}-Day Forecast for {city.title()}:\n\n"
    for day in forecast:
        result += f"• {day['day']}: {day['condition']}, High: {day['high']}°C, Low: {day['low']}°C\n"
    
    return result

@mcp.tool()
def list_available_cities() -> str:
    """List all cities with available weather data."""
    cities = list(WEATHER_DATA.keys())
    return f"Available cities: {', '.join(city.title() for city in cities)}"

if __name__ == "__main__":
    # Run the server
    mcp.run()