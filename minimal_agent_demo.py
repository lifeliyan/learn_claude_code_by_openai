#!/usr/bin/env python3
"""
Minimal Agent Demo - Following agent-builder skill principles

This demonstrates the core philosophy:
1. The model IS the agent
2. Code just provides capabilities
3. Start with 3-5 capabilities
4. Trust the model to figure out the rest
"""

import os
import subprocess
from pathlib import Path

# Configuration
WORKDIR = Path.cwd()

# System prompt - simple and focused
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Rules:
1. Use tools to complete tasks
2. Prefer action over explanation
3. Summarize what you did when done
4. Trust yourself to figure out the workflow

Available capabilities:
- bash: Run shell commands
- read_file: Read file contents
- write_file: Write content to files
- list_files: List directory contents

Remember: You are the agent. The code just gives you capabilities."""

# Minimal tool set - 4 capabilities as recommended
TOOLS = [
    {
        "name": "bash",
        "description": "Execute shell command",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_files",
        "description": "List directory contents",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "detailed": {"type": "boolean", "default": False}
            }
        }
    },
]

def execute_tool(name: str, args: dict) -> str:
    """Execute a tool and return result."""
    if name == "bash":
        try:
            result = subprocess.run(
                args["command"], shell=True, cwd=WORKDIR,
                capture_output=True, text=True, timeout=60
            )
            output = result.stdout + result.stderr
            return output.strip() or "(empty output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 60 seconds"
        except Exception as e:
            return f"Error: {e}"

    elif name == "read_file":
        try:
            file_path = WORKDIR / args["path"]
            if not file_path.exists():
                return f"Error: File not found: {args['path']}"
            content = file_path.read_text()
            return f"File: {args['path']}\n\n{content}"
        except Exception as e:
            return f"Error reading file: {e}"

    elif name == "write_file":
        try:
            file_path = WORKDIR / args["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(args["content"])
            return f"Successfully wrote {len(args['content'])} bytes to {args['path']}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif name == "list_files":
        try:
            dir_path = WORKDIR / args.get("path", ".")
            if not dir_path.exists():
                return f"Error: Directory not found: {args.get('path', '.')}"
            
            if args.get("detailed", False):
                result = subprocess.run(
                    f"ls -la {dir_path}", shell=True, cwd=WORKDIR,
                    capture_output=True, text=True
                )
                return result.stdout.strip()
            else:
                files = list(dir_path.iterdir())
                return "\n".join([f.name for f in files])
        except Exception as e:
            return f"Error listing files: {e}"

    return f"Unknown tool: {name}"

def agent_loop():
    """Simple agent loop demonstration."""
    print("=" * 60)
    print("MINIMAL AGENT DEMO")
    print("=" * 60)
    print("\nThis demonstrates the agent-builder skill principles:")
    print("1. The model IS the agent")
    print("2. Code just provides capabilities")
    print("3. Start with 3-5 capabilities")
    print("4. Trust the model to figure out the rest")
    print("\nType 'quit' to exit.")
    print("-" * 60)
    
    # Simulated conversation history
    history = []
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
            
        if user_input.lower() in ('quit', 'exit', 'q'):
            print("Goodbye!")
            break
            
        if not user_input:
            continue
            
        print("\nAgent thinking...")
        
        # Simulate agent decision-making
        # In a real implementation, this would call an LLM API
        # For this demo, we'll simulate the agent's reasoning
        
        print(f"\nAgent received: {user_input}")
        print("\nAgent would now:")
        print("1. Analyze the request")
        print("2. Decide which tools to use")
        print("3. Execute tools in appropriate sequence")
        print("4. Return results")
        
        # Example: If user asks to list files
        if "list" in user_input.lower() or "files" in user_input.lower() or "ls" in user_input.lower():
            print("\nExample tool execution:")
            result = execute_tool("list_files", {"detailed": True})
            print(f"\nTool result:\n{result}")
        
        # Example: If user asks to read a file
        elif "read" in user_input.lower() and "file" in user_input.lower():
            print("\nExample: To read a file, agent would use read_file tool")
            print("Available files:")
            files_result = execute_tool("list_files", {})
            print(files_result)
        
        # Example: If user asks to create a file
        elif "create" in user_input.lower() or "write" in user_input.lower():
            print("\nExample: To create a file, agent would use write_file tool")
            print("Example: write_file({'path': 'test.txt', 'content': 'Hello World'})")
        
        else:
            print("\nAgent would analyze the request and choose appropriate tools.")
            print("\nAvailable tools:")
            for tool in TOOLS:
                print(f"  - {tool['name']}: {tool['description']}")

if __name__ == "__main__":
    agent_loop()