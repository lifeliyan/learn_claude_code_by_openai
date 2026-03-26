# Agent Builder Skill - Key Takeaways

## The Fundamental Insight

**"The model already knows how to be an agent. Your job is to get out of the way."**

## What This Means

1. **The agent is the model** (Claude, GPT, etc.), not your code
2. **Your code is the harness** - it provides capabilities and context
3. **The model decides** what to do, when to act, and how to sequence actions

## The Three Elements of an Agent Harness

### 1. Capabilities (Tools)
- **What can the agent DO?**
- Atomic actions: bash, read_file, write_file, API calls, etc.
- **Start with 3-5 capabilities** - add more only when consistently needed

### 2. Knowledge (Skills)
- **What does the agent KNOW?**
- Domain expertise: code-review, PDF processing, agent-building, etc.
- **Load on-demand** - not upfront (avoids context bloat)

### 3. Context (Memory)
- **What has happened?**
- Conversation history, tool results, decisions
- **Protect clarity** - isolate noisy subtasks, truncate verbose outputs

## The Universal Agent Loop

```
LOOP:
  Model sees: context + available tools
  Model decides: act or respond
  If act: tool executed, result added to context, loop continues
  If respond: answer returned, loop ends
```

**This is the entire architecture.** Everything else is optimization.

## Progressive Complexity

| Level | What to add | When to add it |
|-------|-------------|----------------|
| Basic | 3-5 capabilities | Always start here |
| Planning | Progress tracking | Multi-step tasks lose coherence |
| Subagents | Isolated child agents | Exploration pollutes context |
| Skills | On-demand knowledge | Domain expertise needed |

**Most agents never need to go beyond Level 2.**

## Key Principles

1. **Trust the model** - It's better at reasoning than your rule systems
2. **Constraints enable** - Limits create focus, not limitation
3. **Start minimal** - Add complexity only when usage reveals the need
4. **Knowledge on-demand** - Load skills when needed, not upfront
5. **Context is precious** - Protect it from noise and bloat

## Anti-Patterns to Avoid

| Pattern | Problem | Solution |
|---------|---------|----------|
| Over-engineering | Complexity before need | Start simple |
| Too many capabilities | Model confusion | 3-5 to start |
| Rigid workflows | Can't adapt | Let model decide |
| Front-loaded knowledge | Context bloat | Load on-demand |
| Micromanagement | Undercuts intelligence | Trust the model |

## The Mindset Shift

**From**: "How do I make the system do X?"
**To**: "How do I enable the model to do X?"

**From**: "What's the workflow for this task?"
**To**: "What capabilities would help accomplish this?"

## Practical Implementation

### Minimal Agent (~80 lines)
```python
# 1. Define 3-5 tools
TOOLS = [bash, read_file, write_file]

# 2. Simple system prompt
SYSTEM = "You are an agent. Use tools to complete tasks."

# 3. Universal loop
while True:
    response = model(history, tools)
    if no_tool_calls: return response
    execute_tools()
    add_results_to_history()
```

### Skill Loading Pattern
```python
# Layer 1: Brief mention in system prompt
"Skills available: code-review, pdf, agent-builder"

# Layer 2: Load on-demand
load_skill("code-review") → <skill>full content</skill>
```

## Resources Created

1. **`minimal_agent_demo.py`** - Simple demonstration of principles
2. **`practical_agent.py`** - Full implementation with skill loading
3. **`test_agent_concepts.py`** - Interactive demonstration
4. **`agent_demo.md`** - Documentation of what was built
5. **`agent_builder_summary.md`** - This summary

## The Bottom Line

**The best agent code is almost boring.** Simple loops, clear capabilities, clean context. The magic isn't in the code - it's in the model's ability to reason and act when given the right capabilities.

Give the model capabilities and knowledge. Trust it to figure out the rest.