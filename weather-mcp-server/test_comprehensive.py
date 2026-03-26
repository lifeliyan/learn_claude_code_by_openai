#!/usr/bin/env python3
"""
Comprehensive test to reproduce the error
"""

import os
import sys
from pathlib import Path

# Set up environment similar to what might be causing issues
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("Comprehensive WeatherService Test")
print("=" * 60)

print("\n1. Testing direct httpx client creation...")
import httpx
try:
    client = httpx.AsyncClient(trust_env=False)
    print(f"   ✅ Direct client creation works")
except Exception as e:
    print(f"   ❌ Direct client creation failed: {e}")

print("\n2. Testing WeatherService import...")
try:
    from weather_server_fixed import WeatherService
    print(f"   ✅ WeatherService import works")
except Exception as e:
    print(f"   ❌ WeatherService import failed: {e}")
    import traceback
    traceback.print_exc()

print("\n3. Testing WeatherService initialization...")
try:
    service = WeatherService()
    print(f"   ✅ WeatherService initialization works")
    print(f"   Configs loaded: {len(service.configs)}")
    print(f"   Client created: {service.client}")
    print(f"   Client trust_env: {service.client.trust_env}")
except Exception as e:
    print(f"   ❌ WeatherService initialization failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)