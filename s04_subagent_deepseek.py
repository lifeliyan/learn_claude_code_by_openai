#!/usr/bin/env python3
"""
s04_subagent_deepseek.py - DeepSeek版本的subagent实现（增强日志版）

架构说明：
┌─────────────────────────────────────────────────────────────────┐
│                      Main Agent (父Agent)                       │
│  职责：协调者 - 负责全局规划和任务委托                              │
│  特点：有完整历史、有task工具、负责任务整合                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 调用 task 工具
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Sub Agent (子Agent)                          │
│  职责：执行者 - 专注于执行独立的子任务                              │
│  特点：全新上下文、只有基础工具、返回摘要即销毁                       │
└─────────────────────────────────────────────────────────────────┘
"""

import os
import sys
import subprocess
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

# ============================================================
# 第一部分：日志辅助函数
# ============================================================

class Logger:
    """统一的日志输出类，便于区分不同Agent的输出"""
    
    @staticmethod
    def main_agent(message: str, level: str = "INFO"):
        """Main Agent 的日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[36m[{timestamp}] [MAIN] {message}\033[0m")
    
    @staticmethod
    def sub_agent(message: str, level: str = "INFO"):
        """Sub Agent 的日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level == "ERROR":
            print(f"\033[31m[{timestamp}] [SUB] {message}\033[0m")
        elif level == "SUCCESS":
            print(f"\033[32m[{timestamp}] [SUB] {message}\033[0m")
        else:
            print(f"\033[33m[{timestamp}] [SUB] {message}\033[0m")
    
    @staticmethod
    def tool_call(agent: str, tool_name: str, args: dict, output: str = None):
        """工具调用的日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n\033[35m[{timestamp}] [{agent}] 🔧 工具调用: {tool_name}\033[0m")
        print(f"   📝 参数: {json.dumps(args, ensure_ascii=False, indent=2)}")
        if output:
            output_preview = output[:200] + "..." if len(output) > 200 else output
            print(f"   📤 输出: {output_preview}")
    
    @staticmethod
    def separator(char: str = "=", length: int = 80):
        """打印分隔线"""
        print(f"\033[90m{char * length}\033[0m")
    
    @staticmethod
    def section(title: str, agent: str = None):
        """打印章节标题"""
        Logger.separator("=")
        if agent:
            print(f"\033[1m[{agent}] {title}\033[0m")
        else:
            print(f"\033[1m{title}\033[0m")
        Logger.separator("-")

# ============================================================
# 第二部分：客户端配置
# ============================================================

def setup_client_with_proxy():
    """配置OpenAI客户端，处理代理问题"""
    proxy_url = None
    for proxy_key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
        if proxy_key in os.environ:
            proxy_url = os.environ[proxy_key]
            if proxy_url:
                Logger.main_agent(f"检测到代理: {proxy_key}={proxy_url}")
            break
    
    # 清除所有代理环境变量，使用直连
    for proxy_key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 
                      'all_proxy', 'ALL_PROXY']:
        if proxy_key in os.environ:
            del os.environ[proxy_key]
    
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )

client = setup_client_with_proxy()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
WORKDIR = Path.cwd()

# ============================================================
# 第三部分：系统提示词
# ============================================================

SYSTEM = f"""You are a Main Agent (coordinator) at {WORKDIR}. Your responsibilities:
1. Understand user requirements and break down complex tasks
2. Plan and coordinate the overall workflow
3. Use the 'task' tool to delegate independent subtasks to subagents
4. Integrate results from subagents and provide final responses

When delegating to a subagent:
- Provide clear, focused prompts
- Include necessary context but avoid overloading
- Trust the subagent to handle the details

Available tools: bash, read_file, write_file, edit_file, task
"""

SUBAGENT_SYSTEM = f"""You are a Sub Agent (executor) at {WORKDIR}. Your role:
1. Execute a single, focused task delegated by the main agent
2. Use available tools to gather information or perform actions
3. Complete the task efficiently
4. Return a concise summary of your findings/actions

Important:
- You have NO 'task' tool (cannot spawn more subagents)
- Each invocation starts with a fresh context
- Your response will be summarized for the main agent
- Focus on completing the assigned task, not long explanations

Available tools: bash, read_file, write_file, edit_file
"""

# ============================================================
# 第四部分：工具实现
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
        start_time = time.time()
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        elapsed = time.time() - start_time
        out = (r.stdout + r.stderr).strip()
        result = out[:50000] if out else "(no output)"
        Logger.tool_call("SUB", "bash", {"command": command}, f"{result} (耗时: {elapsed:.2f}s)")
        return result
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except Exception as e:
        return f"Error: {e}"

def run_read(path: str, limit: Optional[int] = None) -> str:
    """读取文件"""
    try:
        start_time = time.time()
        lines = safe_path(path).read_text().splitlines()
        total_lines = len(lines)
        if limit and limit < total_lines:
            lines = lines[:limit] + [f"... ({total_lines - limit} more lines)"]
        result = "\n".join(lines)[:50000]
        elapsed = time.time() - start_time
        Logger.tool_call("SUB", "read_file", {"path": path, "limit": limit}, 
                        f"读取 {total_lines} 行, 返回 {len(lines)} 行 (耗时: {elapsed:.2f}s)")
        return result
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        start_time = time.time()
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        elapsed = time.time() - start_time
        result = f"Wrote {len(content)} bytes to {path}"
        Logger.tool_call("SUB", "write_file", {"path": path, "content_length": len(content)}, 
                        f"{result} (耗时: {elapsed:.2f}s)")
        return result
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件"""
    try:
        start_time = time.time()
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)
        elapsed = time.time() - start_time
        result = f"Edited {path} (replaced '{old_text[:30]}...')"
        Logger.tool_call("SUB", "edit_file", {"path": path, "old_text": old_text[:50], "new_text": new_text[:50]}, 
                        f"{result} (耗时: {elapsed:.2f}s)")
        return result
    except Exception as e:
        return f"Error: {e}"

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# ============================================================
# 第五部分：工具定义
# ============================================================

BASE_TOOLS = [
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
    }
]

CHILD_TOOLS = BASE_TOOLS
PARENT_TOOLS = BASE_TOOLS + [
    {
        "type": "function",
        "function": {
            "name": "task",
            "description": """Delegate a subtask to a subagent. 
            The subagent starts with a fresh context and will return a summary.
            Use this when you need to:
            - Explore codebase independently
            - Perform isolated research
            - Execute focused tasks that shouldn't pollute your context""",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed instructions for the subagent"},
                    "description": {"type": "string", "description": "Brief description of the task for logging"}
                },
                "required": ["prompt"]
            }
        }
    }
]

# ============================================================
# 第六部分：Sub Agent 实现（带详细日志）
# ============================================================

def run_subagent(prompt: str) -> str:
    """
    运行子Agent - 详细的日志记录每一步
    """
    # 生成唯一ID来标识这次子Agent调用
    subagent_id = f"SUB-{datetime.now().strftime('%H%M%S')}"
    
    Logger.separator("=", 80)
    Logger.sub_agent(f"🚀 启动新的子Agent实例 [{subagent_id}]")
    Logger.sub_agent(f"📋 任务内容: {prompt[:150]}...")
    Logger.sub_agent(f"🧹 上下文状态: 全新 (无历史记录)")
    Logger.sub_agent(f"🔧 可用工具: bash, read_file, write_file, edit_file")
    Logger.separator("-", 80)
    
    # 子Agent的对话历史 - 每次都是全新的！
    sub_messages = [{"role": "user", "content": prompt}]
    
    # 记录执行统计
    tool_calls_count = 0
    start_time = time.time()
    
    # 最多执行30轮迭代
    for round_num in range(30):
        Logger.sub_agent(f"🔄 第 {round_num + 1} 轮推理")
        
        try:
            # 记录API调用开始
            api_start = time.time()
            
            # 调用 DeepSeek API
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SUBAGENT_SYSTEM}] + sub_messages,
                tools=CHILD_TOOLS,
                max_tokens=8000,
                temperature=0.7
            )
            
            api_elapsed = time.time() - api_start
            Logger.sub_agent(f"⏱️  API响应时间: {api_elapsed:.2f}s")
            
            assistant_message = response.choices[0].message
            
            # 记录助手的思考
            if assistant_message.content:
                content_preview = assistant_message.content[:100] + "..." if len(assistant_message.content) > 100 else assistant_message.content
                Logger.sub_agent(f"💭 模型思考: {content_preview}")
            
            # 记录助手响应
            sub_messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            # 如果没有工具调用，任务完成
            if not assistant_message.tool_calls:
                elapsed = time.time() - start_time
                result = assistant_message.content or "(no summary)"
                
                Logger.sub_agent(f"✅ 任务完成! 总耗时: {elapsed:.2f}s")
                Logger.sub_agent(f"📊 统计: 共进行 {round_num + 1} 轮推理, 调用 {tool_calls_count} 次工具")
                Logger.sub_agent(f"📝 返回摘要: {result[:200]}...")
                Logger.separator("=", 80)
                
                return result
            
            # 处理工具调用
            for tool_call in assistant_message.tool_calls:
                tool_calls_count += 1
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                Logger.sub_agent(f"🔧 工具调用 #{tool_calls_count}: {tool_name}")
                Logger.sub_agent(f"   📝 输入参数: {json.dumps(arguments, ensure_ascii=False, indent=2)}")
                
                # 执行工具
                tool_start = time.time()
                handler = TOOL_HANDLERS.get(tool_name)
                if handler:
                    output = handler(**arguments)
                else:
                    output = f"Unknown tool: {tool_name}"
                
                tool_elapsed = time.time() - tool_start
                
                # 记录工具输出
                output_preview = output[:300] + "..." if len(output) > 300 else output
                Logger.sub_agent(f"   ✅ 执行完成 (耗时: {tool_elapsed:.2f}s)")
                Logger.sub_agent(f"   📤 输出预览: {output_preview}")
                
                # 如果输出较长，额外记录长度信息
                if len(output) > 300:
                    Logger.sub_agent(f"   📏 输出总长度: {len(output)} 字符")
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50000]
                })
            
            # 将工具结果添加到历史中
            sub_messages.extend(tool_results)
            Logger.sub_agent(f"📦 本轮完成，进入下一轮迭代")
            Logger.separator("-", 80)
            
        except Exception as e:
            Logger.sub_agent(f"❌ 执行出错: {e}", "ERROR")
            return f"(subagent error: {e})"
    
    elapsed = time.time() - start_time
    Logger.sub_agent(f"⏰ 超时: 达到最大迭代次数30次 (总耗时: {elapsed:.2f}s)", "ERROR")
    return "(subagent timeout)"

# ============================================================
# 第七部分：Main Agent 实现
# ============================================================

def agent_loop(messages: List[Dict]) -> None:
    """Main Agent 的主循环"""
    while True:
        try:
            # 调用 DeepSeek API
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + messages,
                tools=PARENT_TOOLS,
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
                    Logger.main_agent(f"💬 响应: {assistant_message.content[:100]}...")
                return
            
            # 处理工具调用
            tool_results = []
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                Logger.main_agent(f"🔧 调用工具: {tool_name}")
                
                # 关键：task 工具的处理逻辑
                if tool_name == "task":
                    desc = arguments.get("description", "subtask")
                    prompt = arguments["prompt"]
                    
                    Logger.main_agent(f"📤 委托任务给子Agent")
                    Logger.main_agent(f"   📝 任务描述: {desc}")
                    Logger.main_agent(f"   📋 详细指令: {prompt[:100]}...")
                    Logger.separator("-", 80)
                    
                    # 启动子Agent
                    output = run_subagent(prompt)
                    
                    Logger.main_agent(f"📥 收到子Agent响应")
                    Logger.main_agent(f"   📊 摘要: {output[:200]}...")
                    
                else:
                    # 直接执行其他工具
                    handler = TOOL_HANDLERS.get(tool_name)
                    output = handler(**arguments) if handler else f"Unknown tool: {tool_name}"
                    Logger.main_agent(f"✅ 工具执行完成")
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)
                })
            
            # 将工具结果返回给 Main Agent
            messages.extend(tool_results)
            
        except Exception as e:
            Logger.main_agent(f"❌ 错误: {e}", "ERROR")
            messages.append({
                "role": "user",
                "content": f"Error: {e}"
            })
            return

# ============================================================
# 第八部分：主程序
# ============================================================

def main():
    """主函数"""
    Logger.section("🚀 DeepSeek Agent System 启动", "SYSTEM")
    print(f"\n📍 工作目录: {WORKDIR}")
    print(f"🤖 使用模型: {MODEL}")
    print(f"\n📖 架构说明:")
    print(f"   ┌─ Main Agent (协调者)")
    print(f"   │  • 理解用户需求，规划整体任务")
    print(f"   │  • 拥有完整对话历史")
    print(f"   │  • 可以调用 task 工具启动子Agent")
    print(f"   │")
    print(f"   └─ Sub Agent (执行者)")
    print(f"      • 执行独立的子任务")
    print(f"      • 每次都是全新上下文")
    print(f"      • 只返回摘要，不污染主对话")
    print(f"      • 详细日志记录每一步操作")
    print(f"\n💡 使用示例:")
    print(f"   • '列出当前目录所有Python文件' - Main Agent 直接执行")
    print(f"   • '分析项目结构并总结' - Main Agent 会启动 Sub Agent 来分析")
    print(f"\n⌨️  命令:")
    print(f"   • 输入任意问题开始对话")
    print(f"   • 'clear' - 清空对话历史")
    print(f"   • 'exit' 或 'q' - 退出程序")
    Logger.separator("=", 80)
    
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
            Logger.main_agent("✨ 对话历史已清空")
            continue
        
        if not query:
            continue
        
        # 添加用户消息到历史
        history.append({"role": "user", "content": query})
        
        Logger.main_agent(f"📨 收到用户输入: {query}")
        Logger.separator("-", 80)
        
        # 运行 Main Agent 循环
        agent_loop(history)
        
        # 打印 Main Agent 的最终响应
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 助手 >>\033[0m")
            print(f"{last_msg['content']}")
        
        Logger.separator("=", 80)

if __name__ == "__main__":
    main()