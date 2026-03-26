#!/usr/bin/env python3
"""
Verify setup is working
"""

import sys
import os
from pathlib import Path

print("=" * 60)
print("Verifying Weather MCP Server Setup")
print("=" * 60)

# Check virtual environment
print("\n1. Checking virtual environment...")
venv_python = Path("venv/bin/python3")
if venv_python.exists():
    print(f"   ✅ Virtual environment exists: {venv_python}")
else:
    print(f"   ❌ Virtual environment not found")
    sys.exit(1)

# Check requirements
print("\n2. Checking requirements...")
try:
    import httpx
    import mcp
    from dotenv import load_dotenv
    print(f"   ✅ All imports work")
    print(f"   - httpx: {httpx.__version__}")
    print(f"   - mcp: {mcp.__version__ if hasattr(mcp, '__version__') else 'unknown'}")
except ImportError as e:
    print(f"   ❌ Import error: {e}")
    sys.exit(1)

# Check weather_server_fixed.py
print("\n3. Checking weather_server_fixed.py...")
server_file = Path("weather_server_fixed.py")
if server_file.exists():
    print(f"   ✅ Server file exists: {server_file}")
    
    # Try to import it
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from weather_server_fixed import WeatherService
        print(f"   ✅ Can import WeatherService")
        
        # Try to create an instance
        try:
            service = WeatherService()
            print(f"   ✅ WeatherService initialized with {len(service.configs)} providers")
        except Exception as e:
            print(f"   ⚠️  WeatherService init warning (may need API keys): {e}")
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        sys.exit(1)
else:
    print(f"   ❌ Server file not found")
    sys.exit(1)

# Check test_server_updated.py
print("\n4. Checking test_server_updated.py...")
test_file = Path("test_server_updated.py")
if test_file.exists():
    print(f"   ✅ Test file exists: {test_file}")
else:
    print(f"   ❌ Test file not found")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ Setup verification passed!")
print("\nTo use with Claude Desktop, add to ~/.claude/mcp.json:")
print('''{
  "mcpServers": {
    "weather-server": {
      "command": "''' + str(Path(__file__).parent / "venv" / "bin" / "python3") + '''",
      "args": ["''' + str(Path(__file__).parent / "weather_server_fixed.py") + '''"]
    }
  }
}''')
print("\n" + "=" * 60)