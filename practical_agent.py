#!/usr/bin/env python3
"""
Practical Agent - Implementing agent-builder skill principles

This demonstrates:
1. The universal agent loop
2. 3-5 core capabilities
3. On-demand skill loading
4. Trusting the model to figure out workflows
"""

import os
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

# ============================================================
# Configuration
# ============================================================

WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"

# Setup client (using existing pattern from s05_skill_loading.py)
def setup_client():
    """Configure OpenAI client"""
    # Clear proxy for direct connection
    for proxy_key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 
                      'all_proxy', 'ALL_PROXY']:
        if proxy_key in os.environ:
            del os.environ[proxy_key]
    
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )

client = setup_client()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ============================================================
# Core Capabilities (3-5 as recommended)
# ============================================================

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
        "name": "load_skill",
        "description": "Load specialized knowledge by skill name",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        }
    },
]

# ============================================================
# Skill Loader (from s05_skill_loading.py)
# ============================================================

class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str):
        """Parse frontmatter from SKILL.md"""
        lines = text.strip().split('\n')
        meta = {}
        body_lines = []
        
        in_frontmatter = False
        for line in lines:
            if line.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                if ':' in line:
                    key, value = line.split(':', 1)
                    meta[key.strip()] = value.strip()
            else:
                body_lines.append(line)
        
        body = '\n'.join(body_lines).strip()
        return meta, body

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """Get skill by name"""
        return self.skills.get(name)

skill_loader = SkillLoader(SKILLS_DIR)

# ============================================================
# Tool Execution
# ============================================================

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

    elif name == "load_skill":
        skill_name = args.get("name", "")
        skill = skill_loader.get_skill(skill_name)
        if skill:
            return f"<skill name=\"{skill_name}\">\n{skill['body']}\n</skill>"
        else:
            available = ", ".join(skill_loader.skills.keys())
            return f"Skill '{skill_name}' not found. Available skills: {available}"

    return f"Unknown tool: {name}"

# ============================================================
# System Prompt (Following agent-builder principles)
# ============================================================

SYSTEM = f"""You are a practical agent at {WORKDIR}.

## Core Philosophy (from agent-builder skill):
1. **You are the agent** - The code just gives you capabilities
2. **Trust yourself** - You know how to reason and plan
3. **Start simple** - Use 3-5 capabilities effectively
4. **Load knowledge on-demand** - Use load_skill when you need expertise

## Available Capabilities:
1. **bash** - Execute shell commands (read, write, list, search, etc.)
2. **read_file** - Read file contents
3. **write_file** - Write content to files
4. **load_skill** - Load specialized knowledge (agent-builder, code-review, pdf, mcp-builder)

## Available Skills (load on-demand):
- agent-builder: Build AI agents for any domain
- code-review: Review code for security, performance, maintainability
- pdf: Process PDF files (extract text, create, merge)
- mcp-builder: Build MCP servers to give Claude new capabilities

## Your Approach:
1. **Analyze** the user's request
2. **Plan** which tools to use in what sequence
3. **Execute** tools to accomplish the task
4. **Summarize** what you did

## Remember:
- You decide the workflow, not the code
- Use load_skill when you need domain expertise
- Prefer action over explanation
- Trust your reasoning capabilities
"""

# ============================================================
# The Universal Agent Loop
# ============================================================

def agent_loop(prompt: str, history: List[Dict] = None) -> str:
    """The universal agent loop - model decides when to act or respond."""
    if history is None:
        history = []

    # Add user message to history
    history.append({"role": "user", "content": prompt})

    print(f"\n{'='*60}")
    print(f"AGENT STARTING: {prompt[:50]}...")
    print(f"{'='*60}")

    iteration = 0
    while True:
        iteration += 1
        print(f"\n[Iteration {iteration}] Agent thinking...")

        try:
            # Call the model
            response = client.chat.completions.create(
                model=MODEL,
                messages=history,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=4000,
            )

            message = response.choices[0].message
            history.append(message)

            # If no tool calls, return the response
            if not message.tool_calls:
                print(f"[Iteration {iteration}] Agent responding...")
                return message.content

            # Execute tool calls
            tool_results = []
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                print(f"[Iteration {iteration}] Using {tool_name}: {tool_args}")
                
                result = execute_tool(tool_name, tool_args)
                print(f"[Iteration {iteration}] Result: {result[:100]}...")
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": result
                })

            # Add tool results to history
            history.extend(tool_results)

        except Exception as e:
            return f"Error in agent loop: {e}"

# ============================================================
# Interactive Session
# ============================================================

def interactive_session():
    """Run an interactive agent session."""
    print("\n" + "="*60)
    print("PRACTICAL AGENT - Following agent-builder principles")
    print("="*60)
    print("\nKey principles demonstrated:")
    print("1. The model IS the agent (you decide the workflow)")
    print("2. Code provides 3-5 core capabilities")
    print("3. Skills loaded on-demand when needed")
    print("4. Universal agent loop: model decides act/respond")
    print("\nType 'quit' to exit.")
    print("-"*60)

    history = []
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break
            
        if user_input.lower() in ('quit', 'exit', 'q'):
            print("Goodbye!")
            break
            
        if not user_input:
            continue
        
        # Run the agent
        result = agent_loop(user_input, history)
        
        print(f"\n{'='*60}")
        print("AGENT RESPONSE:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}")

if __name__ == "__main__":
    interactive_session()