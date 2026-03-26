#!/usr/bin/env python3
"""
Demo script showing how to use the Weather MCP Server.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from weather_server_fixed import (
    WeatherService, 
    TemperatureUnit, 
    WeatherProvider,
    handle_get_current_weather,
    handle_get_weather_forecast,
    handle_search_weather_locations,
    handle_get_available_providers
)

async def demo():
    """Demo the weather server functionality"""
    print("🌤️ Weather MCP Server Demo")
    print("=" * 50)
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Initialize service
    print("\n1. Initializing Weather Service...")
    try:
        service = WeatherService()
        print(f"   ✅ Initialized with {len(service.configs)} provider(s)")
        for provider in service.configs.keys():
            print(f"   • {provider.value}")
    except ValueError as e:
        print(f"   ❌ Failed: {e}")
        print("\n   Please add API keys to .env file:")
        print("   - OPENWEATHERMAP_API_KEY")
        print("   - WEATHERAPI_API_KEY")
        print("   - VISUALCROSSING_API_KEY")
        return
    
    # Demo available providers
    print("\n2. Available Providers:")
    providers_result = await handle_get_available_providers()
    print(f"   {providers_result}")
    
    # Demo location search
    print("\n3. Location Search Demo:")
    try:
        locations_result = await handle_search_weather_locations("New York", limit=3)
        print(f"   {locations_result}")
    except Exception as e:
        print(f"   ⚠️  Search failed: {e}")
    
    # Demo current weather
    print("\n4. Current Weather Demo:")
    cities = ["London", "Tokyo", "Paris"]
    for city in cities:
        try:
            weather_result = await handle_get_current_weather(city, "celsius")
            # Extract just the first line for demo
            first_line = weather_result.split('\n')[0]
            print(f"   {first_line}")
        except Exception as e:
            print(f"   ⚠️  {city}: {e}")
    
    # Demo forecast
    print("\n5. Weather Forecast Demo:")
    try:
        forecast_result = await handle_get_weather_forecast("London", days=2, unit="celsius")
        # Extract just the summary for demo
        lines = forecast_result.split('\n')
        print(f"   {lines[0]}")
        print(f"   {lines[1]}")
    except Exception as e:
        print(f"   ⚠️  Forecast failed: {e}")
    
    # Clean up
    await service.close()
    
    print("\n" + "=" * 50)
    print("🎉 Demo Complete!")
    print("\nTo use with Claude Desktop:")
    print("1. Ensure you have API keys in .env file")
    print("2. Add server to ~/.claude/mcp.json")
    print("3. Restart Claude Desktop")
    print("4. Ask Claude weather questions!")
    print("\nExample questions:")
    print("  • 'What's the weather in Tokyo?'")
    print("  • 'Get a 5-day forecast for Paris'")
    print("  • 'Search for cities named Sydney'")

if __name__ == "__main__":
    asyncio.run(demo())