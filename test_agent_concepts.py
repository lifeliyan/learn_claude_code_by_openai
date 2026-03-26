#!/usr/bin/env python3
"""
Test Agent Concepts - Demonstrating agent-builder principles without API calls
"""

import subprocess
from pathlib import Path

WORKDIR = Path.cwd()

def demonstrate_capabilities():
    """Show how 3-5 capabilities enable complex tasks."""
    
    print("="*70)
    print("DEMONSTRATING AGENT-BUILDER PRINCIPLES")
    print("="*70)
    
    print("\n1. THE MODEL IS THE AGENT")
    print("   The code doesn't dictate workflows. The model reasons.")
    print("   Example: User asks 'Find all Python files and count lines'")
    print("   Model decides workflow: bash(find) → bash(wc) → respond")
    
    print("\n2. 3-5 CORE CAPABILITIES")
    print("   With just bash, read_file, write_file, we can:")
    
    # Demonstrate bash capability
    print("\n   a) bash - List files:")
    result = subprocess.run("ls -la | head -5", shell=True, capture_output=True, text=True, cwd=WORKDIR)
    print(f"      {result.stdout.strip()}")
    
    # Demonstrate read_file capability  
    print("\n   b) read_file - Read a file:")
    try:
        with open("s05_skill_loading.py", "r") as f:
            content = f.read(200)
        print(f"      First 200 chars of s05_skill_loading.py: {content[:100]}...")
    except:
        print("      (File not found for demo)")
    
    print("\n   c) write_file - Create a file:")
    test_content = "# Test file created by agent\nprint('Hello from agent demo')"
    with open("test_agent_output.py", "w") as f:
        f.write(test_content)
    print(f"      Created test_agent_output.py with {len(test_content)} bytes")
    
    print("\n3. ON-DEMAND KNOWLEDGE LOADING")
    print("   Skills loaded when needed, not upfront")
    print("   Example: load_skill('code-review') → review code → unload")
    
    print("\n4. UNIVERSAL AGENT LOOP")
    print("   while True:")
    print("     model.sees(context + tools)")
    print("     model.decides(act_or_respond)")
    print("     if act: execute_tool(), add_result(), continue")
    print("     if respond: return_to_user()")
    
    print("\n" + "="*70)
    print("EXAMPLE TASK: Analyze project structure")
    print("="*70)
    
    print("\nIf user asks: 'Show me the project structure and find large files'")
    print("\nModel might execute:")
    
    steps = [
        "bash: find . -type f -name '*.py' | head -10",
        "bash: du -sh * | sort -hr | head -5",
        "bash: wc -l *.py | tail -1",
        "read_file: s05_skill_loading.py (first 50 lines)",
        "Respond: Summary of findings"
    ]
    
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    
    print("\nThe model decides this sequence based on the request.")
    print("No code specifies 'when to use which tool' - the model reasons.")
    
    print("\n" + "="*70)
    print("KEY INSIGHT FROM AGENT-BUILDER SKILL")
    print("="*70)
    print("\n'Don't put everything in the system prompt. Load on demand.'")
    print("\n'Start with 3-5 capabilities. Add more only when the agent")
    print("consistently fails because a capability is missing.'")
    
    print("\n'Trust the model. Don't over-engineer. Don't pre-specify")
    print("workflows. Give it capabilities and let it reason.'")

def demonstrate_skill_loading():
    """Show how skills work."""
    
    print("\n" + "="*70)
    print("SKILL LOADING DEMONSTRATION")
    print("="*70)
    
    print("\nAvailable skills in skills/ directory:")
    skills_dir = WORKDIR / "skills"
    if skills_dir.exists():
        for item in skills_dir.iterdir():
            if item.is_dir():
                skill_file = item / "SKILL.md"
                if skill_file.exists():
                    with open(skill_file, "r") as f:
                        first_line = f.readline().strip()
                    print(f"  - {item.name}: {first_line}")
    
    print("\nHow it works:")
    print("  1. System prompt mentions: 'Skills available: agent-builder, code-review...'")
    print("  2. When agent needs expertise: load_skill('code-review')")
    print("  3. Full skill content injected via tool_result")
    print("  4. Agent uses that knowledge for current task")
    print("  5. Knowledge not carried forward (avoids context bloat)")

if __name__ == "__main__":
    demonstrate_capabilities()
    demonstrate_skill_loading()
    
    # Clean up test file
    test_file = WORKDIR / "test_agent_output.py"
    if test_file.exists():
        test_file.unlink()
        print(f"\nCleaned up: {test_file.name}")