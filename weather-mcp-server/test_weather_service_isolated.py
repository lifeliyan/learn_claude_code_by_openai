#!/usr/bin/env python3
"""
Test WeatherService in isolation
"""

import os
import sys
from pathlib import Path

# Set up environment
os.environ['VISUALCROSSING_API_KEY'] = 'test_key'

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

print("Testing WeatherService in isolation...")

try:
    # Import just the WeatherService class
    from weather_server_fixed import WeatherService
    
    print("✅ WeatherService imported")
    
    # Try to create an instance
    print("Creating WeatherService instance...")
    service = WeatherService()
    
    print(f"✅ WeatherService created successfully")
    print(f"   Configs loaded: {len(service.configs)}")
    print(f"   Client created: {service.client}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()