#!/usr/bin/env python3
# Harness: compression -- clean memory for infinite sessions.
"""
s06_context_compact.py - Compact (DeepSeek版本)

Three-layer compression pipeline so the agent can work forever:

    Every turn:
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        (silent, every turn)
      Replace tool_result content older than last 3
      with "[Previous: used {tool_name}]"
            |
            v
    [Check: tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  Save full transcript to .transcripts/
                  Ask LLM to summarize conversation.
                  Replace all messages with [summary].
                        |
                        v
                [Layer 3: compact tool]
                  Model calls compact -> immediate summarization.
                  Same as auto, triggered manually.

Key insight: "The agent can forget strategically and keep working forever."
"""

import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

# ============================================================
# 日志辅助类
# ============================================================

class Logger:
    """统一的日志输出类"""
    
    @staticmethod
    def info(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[36m[{timestamp}] ℹ️  {message}\033[0m")
    
    @staticmethod
    def success(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[32m[{timestamp}] ✅ {message}\033[0m")
    
    @staticmethod
    def warning(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[33m[{timestamp}] ⚠️  {message}\033[0m")
    
    @staticmethod
    def error(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[31m[{timestamp}] ❌ {message}\033[0m")
    
    @staticmethod
    def compact(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 🗜️  {message}\033[0m")
    
    @staticmethod
    def tool_call(tool_name: str, args: dict, output_preview: str = None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n\033[35m[{timestamp}] 🔧 工具调用: {tool_name}\033[0m")
        print(f"   📝 参数: {json.dumps(args, ensure_ascii=False, indent=2)}")
        if output_preview:
            print(f"   📤 输出: {output_preview}")
    
    @staticmethod
    def separator(char: str = "=", length: int = 80):
        print(f"\033[90m{char * length}\033[0m")
    
    @staticmethod
    def section(title: str):
        Logger.separator("=")
        print(f"\033[1m{title}\033[0m")
        Logger.separator("-")


# ============================================================
# 客户端配置（DeepSeek兼容OpenAI接口）
# ============================================================

def setup_client():
    """配置OpenAI客户端（使用DeepSeek的base_url）"""
    # 处理代理问题
    for proxy_key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 
                      'all_proxy', 'ALL_PROXY']:
        if proxy_key in os.environ:
            Logger.info(f"清除代理环境变量: {proxy_key}={os.environ[proxy_key]}")
            del os.environ[proxy_key]
    
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        Logger.error("未找到 DEEPSEEK_API_KEY 环境变量")
        raise ValueError("DEEPSEEK_API_KEY not set")
    
    Logger.success(f"API Key 已加载: {api_key[:10]}...")
    
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )

client = setup_client()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
WORKDIR = Path.cwd()
SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."

# 压缩配置
THRESHOLD = 50000  # token阈值，超过则触发自动压缩
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3    # 保留最近N个工具结果


def estimate_tokens(messages: list) -> int:
    """粗略估算token数: 约4个字符 = 1 token"""
    total_chars = len(json.dumps(messages, default=str))
    estimated = total_chars // 4
    Logger.info(f"📊 Token估算: {estimated} tokens (基于 {total_chars} 字符)")
    return estimated


# ============================================================
# Layer 1: micro_compact - 替换旧的工具结果为占位符
# ============================================================

def micro_compact(messages: list) -> list:
    """
    微压缩：将旧的工具调用结果替换为简短的占位符
    只保留最近的 KEEP_RECENT 个工具结果
    """
    Logger.compact("Layer 1: 开始微压缩 (micro_compact)")
    
    # 收集所有工具结果的位置
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        # OpenAI格式：工具结果在 message 的 role 为 "tool"
        if msg["role"] == "tool":
            tool_results.append((msg_idx, msg))
        # 也兼容旧的格式
        elif msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part))
    
    total_results = len(tool_results)
    Logger.info(f"   找到 {total_results} 个工具结果，保留最近 {KEEP_RECENT} 个")
    
    if total_results <= KEEP_RECENT:
        Logger.info("   工具结果数量未超过阈值，跳过压缩")
        return messages
    
    # 构建 tool_use_id 到 tool_name 的映射
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tool_call in msg["tool_calls"]:
                tool_name_map[tool_call.id] = tool_call.function.name
    
    # 压缩旧的结果（保留最近 KEEP_RECENT 个）
    to_clear = tool_results[:-KEEP_RECENT]
    Logger.info(f"   压缩 {len(to_clear)} 个旧工具结果")
    
    for msg_idx, result in to_clear:
        # 处理不同的结果格式
        content = result.get("content", "")
        if isinstance(content, str) and len(content) > 100:
            tool_id = result.get("tool_call_id", result.get("tool_use_id", ""))
            tool_name = tool_name_map.get(tool_id, "unknown")
            result["content"] = f"[Previous: used {tool_name}]"
            Logger.info(f"      压缩结果: {tool_name} -> 占位符")
    
    Logger.success("微压缩完成")
    return messages


# ============================================================
# Layer 2: auto_compact - 保存转录本，总结，替换消息
# ============================================================

def auto_compact(messages: list) -> list:
    """
    自动压缩：保存完整对话，让LLM总结，用总结替换所有消息
    """
    Logger.compact("Layer 2: 开始自动压缩 (auto_compact)")
    
    # 保存完整对话到磁盘
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    
    Logger.info(f"   保存完整对话到: {transcript_path}")
    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")
    
    Logger.success(f"   对话已保存，共 {len(messages)} 条消息")
    
    # 准备总结用的对话文本
    conversation_text = json.dumps(messages, default=str, ensure_ascii=False)[:80000]
    Logger.info(f"   准备总结文本，长度: {len(conversation_text)} 字符")
    
    # 调用 LLM 生成总结
    Logger.info("   请求 LLM 生成对话总结...")
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer. Create concise but comprehensive summaries."},
                {"role": "user", "content": 
                    "Summarize this conversation for continuity. Include:\n"
                    "1) What was accomplished,\n"
                    "2) Current state,\n"
                    "3) Key decisions made.\n"
                    "Be concise but preserve critical details.\n\n"
                    f"{conversation_text}"}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        summary = response.choices[0].message.content
        Logger.success(f"   总结生成完成，长度: {len(summary)} 字符")
        Logger.info(f"   总结预览: {summary[:200]}...")
        
    except Exception as e:
        Logger.error(f"   总结生成失败: {e}")
        summary = f"[压缩失败: {e}]"
    
    # 用压缩后的消息替换原消息
    compressed_messages = [
        {"role": "user", "content": f"[对话已压缩。完整记录: {transcript_path}]\n\n{summary}"},
        {"role": "assistant", "content": "收到。我已从总结中获取上下文，继续工作。"}
    ]
    
    Logger.success(f"对话压缩完成: {len(messages)} 条消息 -> {len(compressed_messages)} 条消息")
    Logger.compact("自动压缩完成")
    
    return compressed_messages


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

def run_compact(focus: str = None) -> str:
    """手动触发压缩"""
    Logger.info(f"手动压缩触发，聚焦点: {focus or '全部'}")
    return f"Manual compression requested. Focus: {focus or 'general'}"


TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "compact":    lambda **kw: run_compact(kw.get("focus")),
}


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
            "name": "compact",
            "description": "Trigger manual conversation compression to free up context space.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "What to preserve in the summary (optional)"}
                }
            }
        }
    }
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """
    Main Agent 的主循环，包含三层压缩机制
    """
    round_num = 0
    
    while True:
        round_num += 1
        Logger.separator("-", 80)
        Logger.info(f"🔄 第 {round_num} 轮对话")
        
        # Layer 1: micro_compact - 每次调用前进行微压缩
        Logger.info("执行 Layer 1: 微压缩...")
        micro_compact(messages)
        
        # Layer 2: auto_compact - 检查token阈值
        estimated_tokens = estimate_tokens(messages)
        if estimated_tokens > THRESHOLD:
            Logger.warning(f"Token数 ({estimated_tokens}) 超过阈值 ({THRESHOLD})，触发自动压缩")
            Logger.compact("执行 Layer 2: 自动压缩")
            messages[:] = auto_compact(messages)
            Logger.success(f"压缩后Token估算: {estimate_tokens(messages)}")
        else:
            Logger.info(f"Token数正常: {estimated_tokens}/{THRESHOLD}")
        
        # 调用 DeepSeek API
        Logger.info("调用 DeepSeek API...")
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + messages,
                tools=TOOLS,
                max_tokens=8000,
                temperature=0.7
            )
            
            assistant_message = response.choices[0].message
            
            # 记录助手的响应
            if assistant_message.content:
                Logger.info(f"💬 助手响应: {assistant_message.content[:100]}...")
            
            # 添加到历史
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            # 如果没有工具调用，本轮结束
            if not assistant_message.tool_calls:
                Logger.success("对话轮次结束（无工具调用）")
                return
            
            # 处理工具调用
            tool_results = []
            manual_compact_triggered = False
            
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                Logger.tool_call(tool_name, arguments)
                
                # 检查是否是手动压缩
                if tool_name == "compact":
                    manual_compact_triggered = True
                    output = TOOL_HANDLERS[tool_name](**arguments)
                    Logger.compact(f"手动压缩工具被调用: {output}")
                else:
                    handler = TOOL_HANDLERS.get(tool_name)
                    try:
                        output = handler(**arguments) if handler else f"Unknown tool: {tool_name}"
                    except Exception as e:
                        output = f"Error executing {tool_name}: {e}"
                        Logger.error(f"工具执行失败: {e}")
                
                # 输出预览
                output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                Logger.info(f"工具输出: {output_preview}")
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50000]
                })
            
            # 添加工具结果到历史
            messages.extend(tool_results)
            Logger.info(f"添加了 {len(tool_results)} 个工具结果")
            
            # Layer 3: manual compact - 如果模型调用了compact工具
            if manual_compact_triggered:
                Logger.compact("执行 Layer 3: 手动压缩 (由 compact 工具触发)")
                messages[:] = auto_compact(messages)
                Logger.success("手动压缩完成")
            
        except Exception as e:
            Logger.error(f"Agent循环错误: {e}")
            messages.append({
                "role": "user",
                "content": f"Error: {e}"
            })
            return


# ============================================================
# 主程序
# ============================================================

def print_status():
    """打印系统状态"""
    Logger.section("📊 系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    print(f"   Token阈值: {THRESHOLD}")
    print(f"   保留最近工具数: {KEEP_RECENT}")
    print(f"   转录本目录: {TRANSCRIPT_DIR}")
    
    # 统计已有的转录本
    if TRANSCRIPT_DIR.exists():
        transcripts = list(TRANSCRIPT_DIR.glob("*.jsonl"))
        print(f"   已有转录本: {len(transcripts)} 个")
        if transcripts:
            latest = max(transcripts, key=lambda p: p.stat().st_mtime)
            print(f"   最新: {latest.name}")
    
    Logger.separator("-")


if __name__ == "__main__":
    Logger.section("🚀 DeepSeek Context Compression System 启动")
    print_status()
    
    print("\n📖 压缩机制说明:")
    print("   Layer 1 (微压缩): 每次对话前自动执行")
    print("     - 将旧的工具调用结果替换为简短占位符")
    print(f"     - 只保留最近 {KEEP_RECENT} 个完整结果")
    print()
    print("   Layer 2 (自动压缩): 当 token 超过阈值时触发")
    print(f"     - 阈值: {THRESHOLD} tokens")
    print("     - 保存完整对话到 .transcripts/")
    print("     - 让 LLM 总结对话内容")
    print("     - 用总结替换所有历史消息")
    print()
    print("   Layer 3 (手动压缩): 模型主动调用 compact 工具")
    print("     - 模型可以主动请求压缩")
    print("     - 可以指定总结的聚焦点")
    print()
    print("💡 使用示例:")
    print("   • 正常对话 - 观察微压缩效果")
    print("   • 长时间对话 - 观察自动压缩触发")
    print("   • 输入 'compact' 或让模型调用 compact 工具 - 手动压缩")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • 'status' - 查看当前状态")
    print("   • 'clear' - 清空对话历史")
    print("   • 'exit' 或 'q' - 退出程序")
    Logger.separator("=")
    
    history = []
    
    while True:
        try:
            query = input("\n\033[36m📝 你 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 再见！")
            break
        
        if query.lower() in ('q', 'exit', 'quit'):
            print("👋 再见！")
            break
        
        if query.lower() == 'clear':
            history = []
            Logger.success("对话历史已清空")
            continue
        
        if query.lower() == 'status':
            print_status()
            continue
        
        if not query:
            continue
        
        # 添加用户消息到历史
        history.append({"role": "user", "content": query})
        Logger.info(f"📨 用户输入: {query}")
        
        # 运行 Agent 循环
        agent_loop(history)
        
        # 打印最终响应
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 助手 >>\033[0m")
            print(f"{last_msg['content']}")
        
        # 显示当前消息数量
        Logger.info(f"当前历史消息数: {len(history)}")
        
        Logger.separator("=")