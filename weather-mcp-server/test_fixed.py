#!/usr/bin/env python3
"""
Test the fixed weather MCP server
"""

import sys
import os
from pathlib import Path

# Add mock API keys for testing
os.environ['OPENWEATHERMAP_API_KEY'] = 'test_key'
os.environ['WEATHERAPI_API_KEY'] = 'test_key'
os.environ['VISUALCROSSING_API_KEY'] = 'test_key'

# Import after setting environment variables
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Try to import and create the server
    from weather_server_fixed import WeatherService, server, TOOLS
    
    print("✅ Server imports successfully")
    print(f"✅ Server name: {server.name}")
    
    # Check tools
    print(f"\n🔧 Found {len(TOOLS)} tools:")
    for tool in TOOLS:
        print(f"  - {tool.name}: {tool.description[:50]}...")
    
    # Test WeatherService initialization
    try:
        service = WeatherService()
        print(f"\n✅ WeatherService initialized with {len(service.configs)} providers")
        print(f"   Providers: {list(service.configs.keys())}")
    except ValueError as e:
        print(f"\n⚠️  WeatherService initialization (expected without real API keys): {e}")
    
    # Test tool handlers directly
    print("\n🧪 Testing tool handlers...")
    
    import asyncio
    
    # Test get_available_providers
    from weather_server_fixed import handle_get_available_providers
    result = asyncio.run(handle_get_available_providers())
    print(f"✅ get_available_providers: {result[:50]}...")
    
    # Test clear_weather_cache
    from weather_server_fixed import handle_clear_weather_cache
    result = asyncio.run(handle_clear_weather_cache())
    print(f"✅ clear_weather_cache: {result}")
    
    print("\n🎉 Fixed server test passed!")
    print("\nTo use with Claude Desktop:")
    print("1. Add real API keys to .env file")
    print("2. Update your ~/.claude/mcp.json to use weather_server_fixed.py")
    print("3. Restart Claude Desktop")
    
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)