#!/usr/bin/env python3
"""
Verify the httpx proxy fix
"""

import os
import sys

print("=" * 60)
print("Verifying httpx proxy fix")
print("=" * 60)

# Set problematic environment variables
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'

print("\n1. Checking current file content...")
try:
    with open('weather_server_fixed.py', 'r') as f:
        lines = f.readlines()
        # Look for the client creation line
        for i, line in enumerate(lines[90:100], 91):
            if 'self.client = httpx.AsyncClient' in line:
                print(f"   Line {i}: {line.strip()}")
                break
except Exception as e:
    print(f"   Error reading file: {e}")

print("\n2. Testing WeatherService...")
try:
    from weather_server_fixed import WeatherService
    print("   ✅ Module imported")
    
    service = WeatherService()
    print(f"   ✅ WeatherService created")
    print(f"   Configs: {len(service.configs)}")
    print(f"   Client: {service.client}")
    
except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)