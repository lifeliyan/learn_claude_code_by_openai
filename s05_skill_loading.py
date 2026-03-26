#!/usr/bin/env python3
# Harness: on-demand knowledge -- domain expertise, loaded when the model asks.
"""
s05_skill_loading.py - Skills (DeepSeek版本)

Two-layer skill injection that avoids bloating the system prompt:

    Layer 1 (cheap): skill names in system prompt (~100 tokens/skill)
    Layer 2 (on demand): full skill body in tool_result

    skills/
      pdf/
        SKILL.md          <-- frontmatter (name, description) + body
      code-review/
        SKILL.md

    System prompt:
    +--------------------------------------+
    | You are a coding agent.              |
    | Skills available:                    |
    |   - pdf: Process PDF files...        |  <-- Layer 1: metadata only
    |   - code-review: Review code...      |
    +--------------------------------------+

    When model calls load_skill("pdf"):
    +--------------------------------------+
    | tool_result:                         |
    | <skill>                              |
    |   Full PDF processing instructions   |  <-- Layer 2: full body
    |   Step 1: ...                        |
    |   Step 2: ...                        |
    | </skill>                             |
    +--------------------------------------+

Key insight: "Don't put everything in the system prompt. Load on demand."
"""

import os
import re
import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

# ============================================================
# 客户端配置（DeepSeek兼容OpenAI接口）
# ============================================================

def setup_client():
    """配置OpenAI客户端（使用DeepSeek的base_url）"""
    # 处理代理问题
    proxy_url = None
    for proxy_key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
        if proxy_key in os.environ:
            proxy_url = os.environ[proxy_key]
            if proxy_url:
                print(f"检测到代理: {proxy_key}={proxy_url}")
            break
    
    # 清除代理环境变量，使用直连（根据需要调整）
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
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"

# ============================================================
# SkillLoader - 扫描 skills/<name>/SKILL.md
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

    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between --- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"


SKILL_LOADER = SkillLoader(SKILLS_DIR)

# Layer 1: skill metadata injected into system prompt
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""

# ============================================================
# 工具实现
# ============================================================

def safe_path(p: str) -> Path:
    """路径安全检查"""
    path = (WORKDIR / p).resolve()
    try:
        if not path.is_relative_to(WORKDIR):
            raise ValueError(f"Path escapes workspace: {p}")
    except AttributeError:
        if WORKDIR not in path.parents and WORKDIR != path:
            raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    """执行bash命令"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "mkfs", "dd if="]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except Exception as e:
        return f"Error: {e}"

def run_read(path: str, limit: Optional[int] = None) -> str:
    """读取文件"""
    try:
        lines = safe_path(path).read_text().splitlines()
        total_lines = len(lines)
        if limit and limit < total_lines:
            lines = lines[:limit] + [f"... ({total_lines - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件"""
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_load_skill(name: str) -> str:
    """加载技能"""
    return SKILL_LOADER.get_content(name)

# ============================================================
# 工具定义（OpenAI格式）
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file. Optionally limit to first N lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (overwrites if exists).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path where to write the file"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace first occurrence of old_text with new_text in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "old_text": {"type": "string", "description": "Text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load specialized knowledge by skill name. Use this before tackling unfamiliar domains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to load (e.g., 'pdf', 'code-review')"}
                },
                "required": ["name"]
            }
        }
    }
]

TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "load_skill": run_load_skill,
}

# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: List[Dict]) -> None:
    """
    Main Agent 的主循环，使用 OpenAI 格式的 tool calls
    """
    while True:
        try:
            # 调用 DeepSeek API
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + messages,
                tools=TOOLS,
                max_tokens=8000,
                temperature=0.7
            )
            
            assistant_message = response.choices[0].message
            
            # 记录助手响应
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            # 如果没有工具调用，本轮对话结束
            if not assistant_message.tool_calls:
                if assistant_message.content:
                    print(f"💬 {assistant_message.content[:200]}...")
                return
            
            # 处理工具调用
            tool_results = []
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                print(f"🔧 调用工具: {tool_name}")
                print(f"   📝 参数: {arguments}")
                
                # 执行工具
                handler = TOOL_HANDLERS.get(tool_name)
                if handler:
                    try:
                        output = handler(**arguments)
                    except Exception as e:
                        output = f"Error executing {tool_name}: {e}"
                else:
                    output = f"Unknown tool: {tool_name}"
                
                # 打印输出预览
                output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                print(f"   📤 输出: {output_preview}")
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50000]  # 限制输出长度
                })
            
            # 将工具结果添加到历史中
            messages.extend(tool_results)
            
        except Exception as e:
            print(f"❌ Agent 循环错误: {e}")
            messages.append({
                "role": "user",
                "content": f"Error: {e}"
            })
            return

# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*80)
    print("🚀 DeepSeek Skills System 启动")
    print("="*80)
    print(f"📍 工作目录: {WORKDIR}")
    print(f"🤖 使用模型: {MODEL}")
    print(f"📚 技能目录: {SKILLS_DIR}")
    print(f"\n📖 技能列表:")
    print(SKILL_LOADER.get_descriptions())
    print("\n💡 使用示例:")
    print("   • '列出当前目录所有Python文件' - 直接执行")
    print("   • '使用 pdf 技能处理 document.pdf' - 自动加载 pdf 技能")
    print("\n⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • 'clear' - 清空对话历史")
    print("   • 'exit' 或 'q' - 退出程序")
    print("="*80)
    
    history = []
    
    while True:
        try:
            query = input("\n\033[36m👤 你 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 再见！")
            break
        
        if query.lower() in ('q', 'exit', 'quit'):
            print("👋 再见！")
            break
        
        if query.lower() == 'clear':
            history = []
            print("✨ 对话历史已清空")
            continue
        
        if not query:
            continue
        
        # 添加用户消息到历史
        history.append({"role": "user", "content": query})
        
        print("\n🤖 助手思考中...")
        print("-"*80)
        
        # 运行 Agent 循环
        agent_loop(history)
        
        # 打印最终响应
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 助手 >>\033[0m")
            print(f"{last_msg['content']}")
        
        print("\n" + "="*80)