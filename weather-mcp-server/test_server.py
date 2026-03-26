#!/usr/bin/env python3
"""
Test script for the Weather MCP Server.
Run this to verify the server works before integrating with Claude.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from weather_server_fixed import WeatherService, TemperatureUnit, WeatherProvider

async def test_weather_service():
    """Test the weather service directly"""
    print("🧪 Testing Weather Service...")
    
    # Check for API keys
    required_keys = ['OPENWEATHERMAP_API_KEY', 'WEATHERAPI_API_KEY', 'VISUALCROSSING_API_KEY']
    available_keys = [key for key in required_keys if os.getenv(key)]
    
    if not available_keys:
        print("❌ No API keys found in environment variables")
        print("Please set at least one of:")
        for key in required_keys:
            print(f"  - {key}")
        return False
    
    print(f"✅ Found API keys: {', '.join(available_keys)}")
    
    try:
        # Initialize service
        service = WeatherService()
        print(f"✅ Service initialized with providers: {list(service.configs.keys())}")
        
        # Test location search
        print("\n🔍 Testing location search...")
        locations = await service.search_locations("London", limit=2)
        print(f"✅ Found {len(locations)} locations")
        for loc in locations:
            print(f"  - {loc['name']}")
        
        # Test current weather (using first available provider)
        print("\n🌤️ Testing current weather...")
        provider = list(service.configs.keys())[0]
        print(f"Using provider: {provider.value}")
        
        weather = await service.get_current_weather(
            "London",
            TemperatureUnit.CELSIUS,
            provider
        )
        
        print(f"✅ Weather data retrieved:")
        print(f"  Location: {weather['location']}")
        print(f"  Temperature: {weather['temperature']}°C")
        print(f"  Conditions: {weather['weather']}")
        print(f"  Provider: {weather['provider']}")
        
        # Test forecast
        print("\n📅 Testing forecast...")
        forecast = await service.get_forecast("London", days=2, unit=TemperatureUnit.CELSIUS)
        print(f"✅ Forecast retrieved:")
        print(f"  Location: {forecast['location']}")
        print(f"  Days: {len(forecast['forecast_days'])}")
        print(f"  Provider: {forecast['provider']}")
        
        # Test cache
        print("\n💾 Testing cache...")
        cache_key = service._generate_cache_key(
            provider,
            "weather",
            {"location": "London", "unit": "celsius"}
        )
        
        cached = service.cache.get(cache_key)
        print(f"✅ Cache test: {'Hit' if cached else 'Miss'}")
        
        # Clear cache
        service.cache.clear()
        print("✅ Cache cleared")
        
        # Clean up
        await service.close()
        
        print("\n🎉 All tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_mcp_tools():
    """Test the MCP tools interface"""
    print("\n🛠️ Testing MCP Tools Interface...")
    
    from weather_server import get_current_weather, get_weather_forecast, search_weather_locations
    
    try:
        # Test current weather tool
        print("\nTesting get_current_weather tool...")
        result = await get_current_weather("Paris", "celsius")
        print(f"✅ Tool response (first 200 chars):")
        print(result[:200] + "...")
        
        # Test forecast tool
        print("\nTesting get_weather_forecast tool...")
        result = await get_weather_forecast("Tokyo", 2, "celsius")
        print(f"✅ Tool response (first 200 chars):")
        print(result[:200] + "...")
        
        # Test location search tool
        print("\nTesting search_weather_locations tool...")
        result = await search_weather_locations("New York", 2)
        print(f"✅ Tool response:")
        print(result)
        
        print("\n🎉 MCP tools test passed!")
        return True
        
    except Exception as e:
        print(f"❌ MCP tools test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Weather MCP Server Test Suite")
    print("=" * 60)
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Run tests
    success = True
    
    # Test 1: Weather Service
    try:
        service_success = asyncio.run(test_weather_service())
        success = success and service_success
    except Exception as e:
        print(f"❌ Weather service test crashed: {e}")
        success = False
    
    # Test 2: MCP Tools (only if service test passed)
    if success:
        try:
            tools_success = asyncio.run(test_mcp_tools())
            success = success and tools_success
        except Exception as e:
            print(f"❌ MCP tools test crashed: {e}")
            success = False
    
    # Summary
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests passed! The server is ready to use.")
        print("\nTo use with Claude Desktop:")
        print("1. Add to ~/.claude/mcp.json:")
        print('''{
  "mcpServers": {
    "weather-server": {
      "command": "python3",
      "args": ["''' + str(Path(__file__).parent / "weather_server.py") + '''"]
    }
  }
}''')
        print("\n2. Restart Claude Desktop")
        print("\n3. Ask Claude: 'What's the weather in London?'")
    else:
        print("❌ Some tests failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()