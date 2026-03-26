#!/usr/bin/env python3
# Harness: background execution -- the model thinks while the harness waits.
"""
s08_background_tasks.py - Background Tasks (DeepSeek版本)

Run commands in background threads. A notification queue is drained
before each LLM call to deliver results.

    Main thread                Background thread
    +-----------------+        +-----------------+
    | agent loop      |        | task executes   |
    | ...             |        | ...             |
    | [LLM call] <---+------- | enqueue(result) |
    |  ^drain queue   |        +-----------------+
    +-----------------+

    Timeline:
    Agent ----[spawn A]----[spawn B]----[other work]----
                 |              |
                 v              v
              [A runs]      [B runs]        (parallel)
                 |              |
                 +-- notification queue --> [results injected]

Key insight: "Fire and forget -- the agent doesn't block while the command runs."
"""

import os
import subprocess
import threading
import time
import uuid
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
    def background(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 🔄 {message}\033[0m")
    
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
            Logger.info(f"清除代理环境变量: {proxy_key}")
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

SYSTEM = f"""You are a coding agent at {WORKDIR}. Use background_run for long-running commands.

Background Task Guidelines:
1. Use background_run for commands that take >10 seconds
2. Continue working while tasks run in background
3. Check status with check_background or wait for automatic notifications
4. Background results are automatically injected before each LLM call
5. Tasks have 5-minute timeout by default
"""


# ============================================================
# BackgroundManager: threaded execution + notification queue
# ============================================================

class BackgroundManager:
    """
    后台任务管理器
    - 在独立线程中执行命令
    - 使用通知队列传递结果
    - 线程安全的操作
    """
    
    def __init__(self):
        self.tasks = {}  # task_id -> {status, result, command, start_time}
        self._notification_queue = []  # completed task results
        self._lock = threading.Lock()
        self._task_counter = 0
        Logger.background("后台任务管理器初始化")

    def run(self, command: str) -> str:
        """
        启动后台任务，立即返回任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        self._task_counter += 1
        
        Logger.background(f"启动后台任务 #{self._task_counter}")
        Logger.info(f"  任务ID: {task_id}")
        Logger.info(f"  命令: {command[:100]}...")
        
        self.tasks[task_id] = {
            "status": "running",
            "result": None,
            "command": command,
            "start_time": datetime.now().isoformat(),
            "task_number": self._task_counter
        }
        
        thread = threading.Thread(
            target=self._execute,
            args=(task_id, command),
            daemon=True,
            name=f"BG-{task_id}"
        )
        thread.start()
        
        Logger.success(f"后台任务已启动，线程: {thread.name}")
        return f"Background task {task_id} started: {command[:80]}"

    def _execute(self, task_id: str, command: str):
        """
        线程执行函数：运行子进程，捕获输出，推送到队列
        """
        thread_name = threading.current_thread().name
        Logger.background(f"线程 {thread_name} 开始执行命令")
        
        try:
            start_time = time.time()
            Logger.info(f"执行后台命令: {command[:100]}")
            
            r = subprocess.run(
                command, shell=True, cwd=WORKDIR,
                capture_output=True, text=True, timeout=300  # 5分钟超时
            )
            
            elapsed = time.time() - start_time
            output = (r.stdout + r.stderr).strip()[:50000]
            status = "completed"
            
            Logger.success(f"后台任务完成，耗时: {elapsed:.2f}s")
            Logger.info(f"输出长度: {len(output)} 字符")
            
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            output = f"Error: Timeout after 300s"
            status = "timeout"
            Logger.error(f"后台任务超时 (300s)")
            
        except Exception as e:
            elapsed = time.time() - start_time
            output = f"Error: {e}"
            status = "error"
            Logger.error(f"后台任务错误: {e}")
        
        # 更新任务状态
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output or "(no output)"
        self.tasks[task_id]["end_time"] = datetime.now().isoformat()
        self.tasks[task_id]["elapsed"] = elapsed
        
        # 添加到通知队列
        with self._lock:
            self._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": command[:80],
                "result": (output or "(no output)")[:500],
                "elapsed": elapsed
            })
            Logger.background(f"任务 {task_id} 结果已入队，队列长度: {len(self._notification_queue)}")

    def check(self, task_id: str = None) -> str:
        """
        检查任务状态
        - 指定 task_id: 返回该任务的详细信息
        - 不指定: 列出所有任务
        """
        if task_id:
            Logger.background(f"查询任务状态: {task_id}")
            t = self.tasks.get(task_id)
            if not t:
                Logger.warning(f"任务不存在: {task_id}")
                return f"Error: Unknown task {task_id}"
            
            status_text = f"[{t['status']}] {t['command'][:60]}"
            if t.get('result'):
                status_text += f"\n结果: {t['result'][:200]}"
            if t.get('elapsed'):
                status_text += f"\n耗时: {t['elapsed']:.2f}s"
            
            return status_text
        
        # 列出所有任务
        Logger.background("列出所有后台任务")
        if not self.tasks:
            return "No background tasks."
        
        lines = []
        running = 0
        completed = 0
        
        for tid, t in self.tasks.items():
            status_icon = {
                "running": "🔄",
                "completed": "✅",
                "timeout": "⏰",
                "error": "❌"
            }.get(t["status"], "❓")
            
            lines.append(f"{status_icon} {tid}: [{t['status']}] {t['command'][:60]}")
            
            if t["status"] == "running":
                running += 1
            elif t["status"] == "completed":
                completed += 1
        
        lines.insert(0, f"📊 任务统计: 运行中 {running} | 已完成 {completed} | 总计 {len(self.tasks)}")
        lines.insert(1, "-" * 50)
        
        return "\n".join(lines)

    def drain_notifications(self) -> list:
        """
        获取并清空所有待处理的通知
        在主循环的每次 LLM 调用前调用
        """
        with self._lock:
            notifs = list(self._notification_queue)
            if notifs:
                Logger.background(f"从队列中取出 {len(notifs)} 个通知")
                for n in notifs:
                    Logger.info(f"  - 任务 {n['task_id']}: {n['status']} (耗时 {n.get('elapsed', 0):.2f}s)")
            else:
                Logger.info("通知队列为空")
            self._notification_queue.clear()
        return notifs
    
    def get_stats(self) -> dict:
        """获取任务统计信息"""
        with self._lock:
            return {
                "total": len(self.tasks),
                "running": sum(1 for t in self.tasks.values() if t["status"] == "running"),
                "completed": sum(1 for t in self.tasks.values() if t["status"] == "completed"),
                "timeout": sum(1 for t in self.tasks.values() if t["status"] == "timeout"),
                "error": sum(1 for t in self.tasks.values() if t["status"] == "error"),
                "queue_size": len(self._notification_queue)
            }


# 全局后台任务管理器
BG = BackgroundManager()


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
    """执行bash命令（阻塞）"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "mkfs", "dd if="]
    if any(d in command for d in dangerous):
        Logger.warning(f"阻止危险命令: {command}")
        return "Error: Dangerous command blocked"
    
    try:
        Logger.info(f"执行阻塞命令: {command[:100]}")
        start_time = time.time()
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        elapsed = time.time() - start_time
        out = (r.stdout + r.stderr).strip()
        Logger.success(f"命令完成，耗时: {elapsed:.2f}s")
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        Logger.error("命令超时 (120s)")
        return "Error: Timeout (120s)"
    except Exception as e:
        Logger.error(f"命令执行错误: {e}")
        return f"Error: {e}"

def run_read(path: str, limit: Optional[int] = None) -> str:
    """读取文件"""
    try:
        Logger.info(f"读取文件: {path}")
        lines = safe_path(path).read_text().splitlines()
        total_lines = len(lines)
        if limit and limit < total_lines:
            lines = lines[:limit] + [f"... ({total_lines - limit} more lines)"]
        Logger.info(f"读取完成，共 {total_lines} 行")
        return "\n".join(lines)[:50000]
    except Exception as e:
        Logger.error(f"读取文件错误: {e}")
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        Logger.info(f"写入文件: {path}, 内容长度: {len(content)}")
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        Logger.success(f"写入完成")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        Logger.error(f"写入文件错误: {e}")
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件"""
    try:
        Logger.info(f"编辑文件: {path}")
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            Logger.warning(f"文本未找到: {old_text[:50]}...")
            return f"Error: Text not found in {path}"
        
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)
        Logger.success(f"编辑完成")
        return f"Edited {path}"
    except Exception as e:
        Logger.error(f"编辑文件错误: {e}")
        return f"Error: {e}"

def run_background_run(command: str) -> str:
    """启动后台任务"""
    return BG.run(command)

def run_check_background(task_id: Optional[str] = None) -> str:
    """检查后台任务状态"""
    return BG.check(task_id)


TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "background_run": run_background_run,
    "check_background": run_check_background,
}


# ============================================================
# 工具定义（OpenAI格式）
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command (blocking). Use for quick commands that complete within seconds.",
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
            "name": "background_run",
            "description": "Run command in background thread. Returns task_id immediately. Use for long-running commands (>10 seconds).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run in background"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_background",
            "description": "Check background task status. Omit task_id to list all tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to check (optional)"}
                }
            }
        }
    }
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """Main Agent 的主循环，包含后台任务通知注入"""
    round_num = 0
    
    while True:
        round_num += 1
        Logger.separator("-", 80)
        Logger.info(f"🔄 第 {round_num} 轮对话")
        
        # 关键：在每次 LLM 调用前，先获取后台任务通知并注入
        Logger.info("检查后台任务通知...")
        notifs = BG.drain_notifications()
        
        if notifs:
            Logger.success(f"发现 {len(notifs)} 个后台任务完成")
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['command']}\n结果: {n['result'][:200]}"
                for n in notifs
            )
            
            # 将通知作为系统消息注入
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{notif_text}\n</background-results>"
            })
            messages.append({
                "role": "assistant",
                "content": "Noted background results. I'll consider them for next steps."
            })
            Logger.background("后台任务结果已注入对话")
        else:
            Logger.info("没有待处理的后台任务通知")
        
        # 调用 DeepSeek API
        try:
            Logger.info("调用 DeepSeek API...")
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
                Logger.info(f"💬 助手响应: {assistant_message.content[:150]}...")
            
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
            
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                Logger.tool_call(tool_name, arguments)
                
                # 执行工具
                handler = TOOL_HANDLERS.get(tool_name)
                if handler:
                    try:
                        start_time = time.time()
                        output = handler(**arguments)
                        elapsed = time.time() - start_time
                        Logger.info(f"工具执行完成，耗时: {elapsed:.2f}s")
                    except Exception as e:
                        output = f"Error executing {tool_name}: {e}"
                        Logger.error(f"工具执行失败: {e}")
                else:
                    output = f"Unknown tool: {tool_name}"
                    Logger.warning(f"未知工具: {tool_name}")
                
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
    Logger.section("📊 后台任务系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    
    stats = BG.get_stats()
    print(f"\n   后台任务统计:")
    print(f"     总任务数: {stats['total']}")
    print(f"     运行中: {stats['running']}")
    print(f"     已完成: {stats['completed']}")
    print(f"     超时: {stats['timeout']}")
    print(f"     错误: {stats['error']}")
    print(f"     待通知: {stats['queue_size']}")
    
    Logger.separator("-")


if __name__ == "__main__":
    import json
    
    Logger.section("🚀 DeepSeek Background Tasks System 启动")
    print_status()
    
    print("\n📖 后台任务系统说明:")
    print("   🔄 非阻塞执行: 命令在后台线程中运行，Agent 可以继续工作")
    print("   📨 自动通知: 任务完成时结果自动注入对话")
    print("   🔍 状态查询: 随时可以查询任务状态")
    print("   ⏱️  超时控制: 任务默认超时时间 5 分钟")
    print()
    print("📚 可用工具:")
    print("   • background_run    - 启动后台任务，立即返回任务ID")
    print("   • check_background  - 查询任务状态（可选指定任务ID）")
    print("   • bash              - 阻塞式命令（用于快速命令）")
    print("   • read/write/edit   - 标准文件操作")
    print()
    print("💡 使用示例:")
    print("   • '后台运行: sleep 10 && echo done'")
    print("   • '检查所有后台任务'")
    print("   • '查看任务 abcd1234 的状态'")
    print("   • '同时运行多个后台任务'")
    print()
    print("🔄 执行流程说明:")
    print("   1. Agent 调用 background_run 启动后台任务")
    print("   2. 后台任务在独立线程中运行，Agent 继续工作")
    print("   3. 在每次 LLM 调用前，系统自动检查已完成的任务")
    print("   4. 任务结果作为 <background-results> 注入对话")
    print("   5. Agent 收到通知后可以继续处理结果")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • 'status' - 查看系统状态")
    print("   • 'tasks' - 列出所有后台任务")
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
        
        if query.lower() == 'tasks':
            print(BG.check())
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
        
        # 显示后台任务状态
        stats = BG.get_stats()
        if stats['total'] > 0:
            Logger.info(f"后台任务: 运行中 {stats['running']} | 已完成 {stats['completed']}")
        
        Logger.separator("=")