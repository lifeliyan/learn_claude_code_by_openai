#!/usr/bin/env python3
"""
Simple test to isolate the httpx issue
"""

import sys
import httpx

print("Testing httpx client creation...")

try:
    # Simplest possible client creation
    client = httpx.AsyncClient()
    print(f"✅ Success! Created client: {client}")
    print(f"   Client timeout: {client.timeout}")
except Exception as e:
    print(f"❌ Failed to create client: {e}")
    print(f"   Error type: {type(e)}")
    import traceback
    traceback.print_exc()
    
    # Try sync client
    print("\nTrying sync client...")
    try:
        sync_client = httpx.Client()
        print(f"✅ Sync client created: {sync_client}")
    except Exception as e2:
        print(f"❌ Sync client also failed: {e2}")