#!/usr/bin/env python3
# Harness: persistent tasks -- goals that outlive any single conversation.
"""
s07_task_system.py - Tasks (DeepSeek版本)

Tasks persist as JSON files in .tasks/ so they survive context compression.
Each task has a dependency graph (blockedBy/blocks).

    .tasks/
      task_1.json  {"id":1, "subject":"...", "status":"completed", ...}
      task_2.json  {"id":2, "blockedBy":[1], "status":"pending", ...}
      task_3.json  {"id":3, "blockedBy":[2], "blocks":[], ...}

    Dependency resolution:
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- completing task 1 removes it from task 2's blockedBy

Key insight: "State that survives compression -- because it's outside the conversation."
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
    def task(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 📋 {message}\033[0m")
    
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
TASKS_DIR = WORKDIR / ".tasks"

SYSTEM = f"""You are a coding agent at {WORKDIR}. Use task tools to plan and track work.

Task Management Guidelines:
1. Create tasks for non-trivial work that requires multiple steps
2. Use dependencies (blockedBy) to express ordering requirements
3. Update task status as work progresses (pending -> in_progress -> completed)
4. When a task is completed, it automatically unblocks dependent tasks
5. Tasks persist across conversations - they survive context compression
"""


# ============================================================
# TaskManager: CRUD with dependency graph, persisted as JSON files
# ============================================================

class TaskManager:
    """任务管理器 - 持久化存储任务及其依赖关系"""
    
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1
        Logger.task(f"任务管理器初始化，目录: {self.dir}")
        Logger.task(f"下一个任务ID: {self._next_id}")

    def _max_id(self) -> int:
        """获取当前最大任务ID"""
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        max_id = max(ids) if ids else 0
        if ids:
            Logger.info(f"现有任务ID: {ids}, 最大值: {max_id}")
        return max_id

    def _load(self, task_id: int) -> dict:
        """加载任务JSON文件"""
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        task = json.loads(path.read_text())
        Logger.info(f"加载任务 #{task_id}: {task.get('subject', 'No subject')}")
        return task

    def _save(self, task: dict):
        """保存任务到JSON文件"""
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
        Logger.info(f"保存任务 #{task['id']}: {task['subject']}")

    def create(self, subject: str, description: str = "") -> str:
        """
        创建新任务
        返回: JSON格式的任务详情
        """
        Logger.task(f"创建新任务: {subject}")
        
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": [],
            "blocks": [],
            "owner": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        self._save(task)
        task_id = self._next_id
        self._next_id += 1
        
        Logger.success(f"任务创建成功: #{task_id} - {subject}")
        return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        """获取任务详情"""
        Logger.task(f"获取任务详情: #{task_id}")
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    def update(self, task_id: int, status: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        """
        更新任务状态或依赖关系
        - status: pending, in_progress, completed
        - add_blocked_by: 添加阻止当前任务的其他任务ID列表
        - add_blocks: 添加当前任务阻止的任务ID列表
        """
        Logger.task(f"更新任务 #{task_id}")
        
        task = self._load(task_id)
        old_status = task.get("status")
        
        # 更新状态
        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            Logger.info(f"  状态变更: {old_status} -> {status}")
            
            # 当任务完成时，从所有其他任务的 blockedBy 中移除
            if status == "completed":
                Logger.info(f"  任务完成，清理依赖关系...")
                self._clear_dependency(task_id)
        
        # 添加被阻止关系 (当前任务被哪些任务阻止)
        if add_blocked_by:
            old_blocked = task["blockedBy"].copy()
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
            Logger.info(f"  被阻止于: {old_blocked} -> {task['blockedBy']}")
        
        # 添加阻止关系 (当前任务阻止哪些任务)
        if add_blocks:
            old_blocks = task["blocks"].copy()
            task["blocks"] = list(set(task["blocks"] + add_blocks))
            Logger.info(f"  阻止: {old_blocks} -> {task['blocks']}")
            
            # 双向更新：同时更新被阻止任务的 blockedBy 列表
            for blocked_id in add_blocks:
                try:
                    blocked_task = self._load(blocked_id)
                    if task_id not in blocked_task["blockedBy"]:
                        blocked_task["blockedBy"].append(task_id)
                        self._save(blocked_task)
                        Logger.info(f"    更新任务 #{blocked_id}: 被 #{task_id} 阻止")
                except ValueError:
                    Logger.warning(f"    任务 #{blocked_id} 不存在，跳过")
        
        task["updated_at"] = datetime.now().isoformat()
        self._save(task)
        
        return json.dumps(task, indent=2, ensure_ascii=False)

    def _clear_dependency(self, completed_id: int):
        """
        完成的任务从所有其他任务的 blockedBy 中移除
        这允许被阻塞的任务自动变为可执行状态
        """
        Logger.info(f"清理任务 #{completed_id} 的依赖关系...")
        removed_count = 0
        
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
                removed_count += 1
                Logger.info(f"  从任务 #{task['id']} 的 blockedBy 中移除 #{completed_id}")
        
        if removed_count > 0:
            Logger.success(f"已从 {removed_count} 个任务中清理依赖")
        else:
            Logger.info("没有需要清理的依赖关系")

    def list_all(self) -> str:
        """列出所有任务（简要视图）"""
        Logger.task("列出所有任务")
        
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        
        if not tasks:
            Logger.info("没有任务")
            return "No tasks."
        
        lines = []
        stats = {"pending": 0, "in_progress": 0, "completed": 0}
        
        for t in tasks:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]"
            }.get(t["status"], "[?]")
            
            stats[t["status"]] = stats.get(t["status"], 0) + 1
            
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
        
        # 添加统计信息
        lines.insert(0, f"📊 任务统计: 待处理 {stats['pending']} | 进行中 {stats['in_progress']} | 已完成 {stats['completed']}")
        lines.insert(1, "-" * 50)
        
        Logger.info(f"任务统计: {stats}")
        return "\n".join(lines)

    def get_dependency_graph(self) -> str:
        """获取依赖关系图的文本表示"""
        Logger.task("生成依赖关系图")
        
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        
        if not tasks:
            return "No tasks."
        
        lines = ["依赖关系图:", "=" * 50]
        
        for task in tasks:
            if task.get("blocks"):
                for blocked_id in task["blocks"]:
                    lines.append(f"  #{task['id']} -> #{blocked_id}")
            if task.get("blockedBy"):
                for blocker_id in task["blockedBy"]:
                    lines.append(f"  #{task['id']} <-- #{blocker_id}")
        
        return "\n".join(lines)


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
        Logger.warning(f"阻止危险命令: {command}")
        return "Error: Dangerous command blocked"
    
    try:
        Logger.info(f"执行命令: {command}")
        start_time = time.time()
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        elapsed = time.time() - start_time
        out = (r.stdout + r.stderr).strip()
        Logger.info(f"命令完成，耗时: {elapsed:.2f}s")
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


# 全局任务管理器实例
TASKS = TaskManager(TASKS_DIR)

# 工具处理函数
def run_task_create(subject: str, description: str = "") -> str:
    """创建任务"""
    return TASKS.create(subject, description)

def run_task_update(task_id: int, status: str = None, 
                    add_blocked_by: list = None, add_blocks: list = None) -> str:
    """更新任务"""
    return TASKS.update(task_id, status, add_blocked_by, add_blocks)

def run_task_list() -> str:
    """列出所有任务"""
    return TASKS.list_all()

def run_task_get(task_id: int) -> str:
    """获取任务详情"""
    return TASKS.get(task_id)

def run_task_graph() -> str:
    """获取依赖关系图"""
    return TASKS.get_dependency_graph()


TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "task_create": run_task_create,
    "task_update": run_task_update,
    "task_list": run_task_list,
    "task_get": run_task_get,
    "task_graph": run_task_graph,
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
            "name": "task_create",
            "description": "Create a new task for tracking work that spans multiple steps or conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Brief task title"},
                    "description": {"type": "string", "description": "Detailed task description (optional)"}
                },
                "required": ["subject"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_update",
            "description": "Update a task's status or dependencies. When status='completed', automatically unblocks dependent tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID to update"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "New status"},
                    "add_blocked_by": {"type": "array", "items": {"type": "integer"}, "description": "Tasks that block this task"},
                    "add_blocks": {"type": "array", "items": {"type": "integer"}, "description": "Tasks blocked by this task"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "List all tasks with their status and blockers.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_get",
            "description": "Get full details of a specific task by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID to retrieve"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_graph",
            "description": "Show the dependency graph of all tasks.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """Main Agent 的主循环"""
    round_num = 0
    
    while True:
        round_num += 1
        Logger.separator("-", 80)
        Logger.info(f"🔄 第 {round_num} 轮对话")
        
        try:
            # 调用 DeepSeek API
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
    Logger.section("📊 任务系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    print(f"   任务目录: {TASKS_DIR}")
    
    # 统计任务数量
    if TASKS_DIR.exists():
        task_files = list(TASKS_DIR.glob("task_*.json"))
        print(f"   任务文件数: {len(task_files)}")
        
        if task_files:
            # 统计各状态任务数量
            status_counts = {"pending": 0, "in_progress": 0, "completed": 0}
            for f in task_files:
                try:
                    task = json.loads(f.read_text())
                    status = task.get("status", "unknown")
                    if status in status_counts:
                        status_counts[status] += 1
                except:
                    pass
            
            print(f"   任务状态: 待处理 {status_counts['pending']} | "
                  f"进行中 {status_counts['in_progress']} | "
                  f"已完成 {status_counts['completed']}")
    
    Logger.separator("-")


if __name__ == "__main__":
    Logger.section("🚀 DeepSeek Task System 启动")
    print_status()
    
    print("\n📖 任务系统说明:")
    print("   📋 任务持久化: 任务保存在 .tasks/ 目录，跨对话持久存在")
    print("   🔗 依赖管理: 支持任务间的阻塞关系 (blockedBy/blocks)")
    print("   ✅ 自动解阻: 任务完成时自动从依赖列表中移除")
    print("   💾 状态保存: 每个任务独立JSON文件，便于版本控制")
    print()
    print("📚 可用工具:")
    print("   • task_create    - 创建新任务")
    print("   • task_update    - 更新任务状态或依赖")
    print("   • task_list      - 列出所有任务")
    print("   • task_get       - 获取任务详情")
    print("   • task_graph     - 显示依赖关系图")
    print("   • bash/read/write/edit - 标准文件操作")
    print()
    print("💡 使用示例:")
    print("   • '创建一个任务: 实现用户登录功能'")
    print("   • '列出所有任务'")
    print("   • '任务 #1 已完成'")
    print("   • '任务 #2 被 #1 阻塞'")
    print("   • '显示依赖关系图'")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • 'status' - 查看系统状态")
    print("   • 'graph' - 显示任务依赖图")
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
        
        if query.lower() == 'graph':
            print(TASKS.get_dependency_graph())
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
        
        # 显示当前任务列表摘要
        if TASKS_DIR.exists() and list(TASKS_DIR.glob("task_*.json")):
            Logger.info("当前任务摘要:")
            print(TASKS.list_all())
        
        Logger.separator("=")