#!/usr/bin/env python3
"""
Debug script to test the weather server
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Try to import the server components
    print("1. Testing imports...")
    from weather_server_fixed import WeatherService, server
    print("   ✅ Imports successful")
    
    # Test WeatherService initialization
    print("\n2. Testing WeatherService...")
    try:
        service = WeatherService()
        print(f"   ✅ WeatherService initialized with {len(service.configs)} providers")
        for provider in service.configs.keys():
            print(f"   • {provider.value}")
    except Exception as e:
        print(f"   ❌ WeatherService failed: {e}")
    
    # Test server initialization
    print("\n3. Testing server...")
    print(f"   Server name: {server.name}")
    
    # Try to run the server
    print("\n4. Testing server run...")
    async def test_run():
        from mcp.server.stdio import stdio_server
        import asyncio
        
        print("   Starting server...")
        try:
            async with stdio_server() as (read, write):
                print("   ✅ stdio_server context entered")
                await server.run(read, write)
                print("   ✅ Server run completed")
        except Exception as e:
            print(f"   ❌ Server run failed: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(test_run())
    
except Exception as e:
    print(f"\n❌ Overall error: {e}")
    import traceback
    traceback.print_exc()