#!/usr/bin/env python3
"""
Test MCP protocol communication with the weather server
"""

import json
import subprocess
import time
import sys
from pathlib import Path

def test_mcp_protocol():
    """Test basic MCP protocol communication"""
    print("🧪 Testing MCP Protocol Communication...")
    
    # Start the server as a subprocess
    server_path = Path(__file__).parent / "weather_server_fixed.py"
    venv_python = Path(__file__).parent / "venv" / "bin" / "python3"
    
    print(f"Starting server: {venv_python} {server_path}")
    
    # Start the server process
    proc = subprocess.Popen(
        [str(venv_python), str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    try:
        # Give server time to start
        time.sleep(0.5)
        
        # Send initialization request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print("\n1. Sending initialization request...")
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        
        # Read response (with timeout)
        time.sleep(0.5)
        if proc.stdout.readable():
            response = proc.stdout.readline()
            if response:
                print(f"   ✅ Got response: {response[:100]}...")
            else:
                print("   ⚠️  No response received")
        
        # Send tools/list request
        tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        
        print("\n2. Sending tools/list request...")
        proc.stdin.write(json.dumps(tools_request) + "\n")
        proc.stdin.flush()
        
        # Read response
        time.sleep(0.5)
        if proc.stdout.readable():
            response = proc.stdout.readline()
            if response:
                print(f"   ✅ Got response: {response[:100]}...")
                # Parse and show tools
                try:
                    data = json.loads(response)
                    if 'result' in data and 'tools' in data['result']:
                        tools = data['result']['tools']
                        print(f"   Found {len(tools)} tools:")
                        for tool in tools:
                            print(f"   • {tool['name']}")
                except:
                    pass
            else:
                print("   ⚠️  No response received")
        
        print("\n✅ MCP protocol test completed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    
    finally:
        # Clean up
        print("\nCleaning up...")
        proc.terminate()
        proc.wait(timeout=2)

if __name__ == "__main__":
    test_mcp_protocol()