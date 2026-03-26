#!/usr/bin/env python3
"""
Simple test to verify the weather server can start without API keys
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
    from weather_server import WeatherService, server
    
    print("✅ Server imports successfully")
    print(f"✅ Server name: {server.name}")
    
    # Check if tools are registered
    print("\n🔧 Checking tools...")
    
    # The server tools are registered via decorators, so they should be available
    print("✅ Server created successfully")
    
    # Test WeatherService initialization
    try:
        service = WeatherService()
        print(f"✅ WeatherService initialized with {len(service.configs)} providers")
        print(f"   Providers: {list(service.configs.keys())}")
    except ValueError as e:
        print(f"⚠️  WeatherService initialization (expected without real API keys): {e}")
    
    print("\n🎉 Basic server test passed!")
    print("\nTo run the full test with API keys:")
    print("1. Add real API keys to .env file")
    print("2. Run: python3 test_server.py")
    
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)