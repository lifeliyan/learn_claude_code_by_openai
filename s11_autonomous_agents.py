#!/usr/bin/env python3
# Harness: autonomy -- models that find work without being told.
"""
s11_autonomous_agents.py - Autonomous Agents (DeepSeek版本)

Idle cycle with task board polling, auto-claiming unclaimed tasks, and
identity re-injection after context compression. Builds on s10's protocols.

    Teammate lifecycle:
    +-------+
    | spawn |
    +---+---+
        |
        v
    +-------+  tool_use    +-------+
    | WORK  | <----------- |  LLM  |
    +---+---+              +-------+
        |
        | stop_reason != tool_use
        v
    +--------+
    | IDLE   | poll every 5s for up to 60s
    +---+----+
        |
        +---> check inbox -> message? -> resume WORK
        |
        +---> scan .tasks/ -> unclaimed? -> claim -> resume WORK
        |
        +---> timeout (60s) -> shutdown

    Identity re-injection after compression:
    messages = [identity_block, ...remaining...]
    "You are 'coder', role: backend, team: my-team"

Key insight: "The agent finds work itself."
"""

import json
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
    def autonomous(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 🤖 {message}\033[0m")
    
    @staticmethod
    def team(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[36m[{timestamp}] 👥 {message}\033[0m")
    
    @staticmethod
    def task_board(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[33m[{timestamp}] 📋 {message}\033[0m")
    
    @staticmethod
    def tool_call(agent: str, tool_name: str, args: dict, output_preview: str = None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n\033[35m[{timestamp}] [{agent}] 🔧 工具调用: {tool_name}\033[0m")
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
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"

POLL_INTERVAL = 5  # 空闲轮询间隔（秒）
IDLE_TIMEOUT = 60   # 空闲超时时间（秒）

SYSTEM = f"""You are a team lead at {WORKDIR}. Teammates are autonomous -- they find work themselves.

Autonomous Agent Guidelines:
1. Spawn autonomous teammates that self-manage their work
2. Teammates will automatically claim tasks from the task board
3. Use idle tool when no work remains
4. Monitor team progress through inbox and task board
"""

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}

# ============================================================
# Request trackers
# ============================================================

shutdown_requests = {}
plan_requests = {}
_tracker_lock = threading.Lock()
_claim_lock = threading.Lock()


# ============================================================
# MessageBus: JSONL inbox per teammate
# ============================================================

class MessageBus:
    """消息总线：基于文件的邮箱系统"""
    
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        Logger.team(f"消息总线初始化，目录: {self.dir}")

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        """发送消息"""
        if msg_type not in VALID_MSG_TYPES:
            Logger.error(f"无效消息类型: {msg_type}")
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat()
        }
        if extra:
            msg.update(extra)
        
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        Logger.info(f"📨 [{sender} -> {to}] {content[:80]}")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        """读取并清空收件箱"""
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []
        
        messages = []
        content = inbox_path.read_text(encoding='utf-8').strip()
        if content:
            for line in content.splitlines():
                if line:
                    try:
                        msg = json.loads(line)
                        messages.append(msg)
                    except json.JSONDecodeError as e:
                        Logger.error(f"解析消息失败: {e}")
        
        # 清空收件箱
        if messages:
            Logger.info(f"{name} 读取 {len(messages)} 条消息")
            inbox_path.write_text("", encoding='utf-8')
        
        return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        """广播消息"""
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        Logger.team(f"广播到 {count} 个队友")
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


# ============================================================
# Task board scanning and claiming
# ============================================================

def scan_unclaimed_tasks() -> list:
    """
    扫描未认领的任务
    条件: pending 状态, 无 owner, 无阻塞依赖
    """
    TASKS_DIR.mkdir(exist_ok=True)
    unclaimed = []
    
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if (task.get("status") == "pending"
                and not task.get("owner")
                and not task.get("blockedBy")):
            unclaimed.append(task)
    
    if unclaimed:
        Logger.task_board(f"发现 {len(unclaimed)} 个未认领任务")
        for task in unclaimed[:3]:  # 只显示前3个
            Logger.task_board(f"  - #{task['id']}: {task['subject']}")
    
    return unclaimed

def claim_task(task_id: int, owner: str) -> str:
    """
    认领任务
    """
    with _claim_lock:
        path = TASKS_DIR / f"task_{task_id}.json"
        if not path.exists():
            Logger.error(f"任务 #{task_id} 不存在")
            return f"Error: Task {task_id} not found"
        
        task = json.loads(path.read_text())
        old_status = task.get("status")
        task["owner"] = owner
        task["status"] = "in_progress"
        task["claimed_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
        
        Logger.task_board(f"{owner} 认领任务 #{task_id}: {task['subject']}")
        Logger.info(f"  状态: {old_status} -> in_progress")
        
    return f"Claimed task #{task_id} for {owner}"

def create_task(subject: str, description: str = "") -> int:
    """创建新任务（用于测试）"""
    TASKS_DIR.mkdir(exist_ok=True)
    
    # 获取下一个ID
    existing = list(TASKS_DIR.glob("task_*.json"))
    next_id = max([int(f.stem.split("_")[1]) for f in existing], default=0) + 1
    
    task = {
        "id": next_id,
        "subject": subject,
        "description": description,
        "status": "pending",
        "owner": None,
        "blockedBy": [],
        "blocks": [],
        "created_at": datetime.now().isoformat()
    }
    
    path = TASKS_DIR / f"task_{next_id}.json"
    path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
    
    Logger.task_board(f"创建任务 #{next_id}: {subject}")
    return next_id


# ============================================================
# Identity re-injection after compression
# ============================================================

def make_identity_block(name: str, role: str, team_name: str) -> dict:
    """
    创建身份信息块，用于压缩后重新注入上下文
    """
    identity = {
        "role": "user",
        "content": f"<identity>You are '{name}', role: {role}, team: {team_name}. Continue your work.</identity>"
    }
    Logger.autonomous(f"为 {name} 创建身份块")
    return identity


# ============================================================
# Autonomous TeammateManager
# ============================================================

class TeammateManager:
    """自治队友管理器"""
    
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}
        self.stop_events = {}
        
        Logger.team(f"自治队友管理器初始化，配置: {self.config_path}")

    def _load_config(self) -> dict:
        """加载团队配置"""
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text())
            Logger.info(f"加载配置: {len(config.get('members', []))} 个队友")
            return config
        return {"team_name": "default", "members": []}

    def _save_config(self):
        """保存团队配置"""
        self.config_path.write_text(json.dumps(self.config, indent=2, ensure_ascii=False))

    def _find_member(self, name: str) -> dict:
        """查找队友"""
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _set_status(self, name: str, status: str):
        """设置队友状态"""
        member = self._find_member(name)
        if member:
            old_status = member.get("status")
            member["status"] = status
            self._save_config()
            Logger.autonomous(f"{name} 状态: {old_status} -> {status}")

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """
        生成自治队友
        """
        Logger.autonomous(f"生成自治队友: {name} (角色: {role})")
        Logger.info(f"初始提示: {prompt[:100]}...")
        
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
            Logger.info(f"唤醒已有队友: {name}")
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
            Logger.success(f"创建新队友: {name}")
        
        self._save_config()
        
        # 创建停止事件
        self.stop_events[name] = threading.Event()
        
        thread = threading.Thread(
            target=self._autonomous_loop,
            args=(name, role, prompt),
            daemon=True,
            name=f"Auto-{name}"
        )
        self.threads[name] = thread
        thread.start()
        
        Logger.success(f"自治队友 {name} 已启动 (线程: {thread.name})")
        return f"Spawned autonomous '{name}' (role: {role})"

    def _autonomous_loop(self, name: str, role: str, prompt: str):
        """
        自治队友的主循环
        工作阶段 -> 空闲阶段 -> 工作阶段 -> ...
        """
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            f"Use idle tool when you have no more work. You will auto-claim new tasks."
        )
        
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()
        
        iteration = 0
        
        while True:
            # 检查停止信号
            if self.stop_events.get(name, threading.Event()).is_set():
                Logger.warning(f"{name} 收到停止信号")
                self._set_status(name, "shutdown")
                return
            
            # ============================================================
            # WORK PHASE: 工作阶段
            # ============================================================
            Logger.autonomous(f"{name} 进入工作阶段")
            self._set_status(name, "working")
            
            work_iterations = 0
            idle_requested = False
            
            while work_iterations < 50:
                work_iterations += 1
                iteration += 1
                Logger.info(f"[{name}] 工作轮次 {work_iterations}")
                
                # 读取收件箱
                inbox = BUS.read_inbox(name)
                if inbox:
                    Logger.info(f"{name} 收到 {len(inbox)} 条消息")
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            Logger.protocol(f"{name} 收到 shutdown 请求，准备退出")
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})
                
                try:
                    response = client.chat.completions.create(
                        model=MODEL,
                        messages=[{"role": "system", "content": sys_prompt}] + messages,
                        tools=tools,
                        max_tokens=8000,
                        temperature=0.7
                    )
                    
                    assistant_message = response.choices[0].message
                    
                    if assistant_message.content:
                        Logger.info(f"[{name}] 思考: {assistant_message.content[:100]}...")
                    
                    messages.append({
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": assistant_message.tool_calls
                    })
                    
                    # 没有工具调用，说明工作完成
                    if not assistant_message.tool_calls:
                        Logger.info(f"{name} 无工具调用，工作完成")
                        break
                    
                    # 处理工具调用
                    results = []
                    for tool_call in assistant_message.tool_calls:
                        tool_name = tool_call.function.name
                        arguments = json.loads(tool_call.function.arguments)
                        
                        Logger.tool_call(name, tool_name, arguments)
                        
                        if tool_name == "idle":
                            idle_requested = True
                            output = "Entering idle phase. Will poll for new tasks."
                            Logger.autonomous(f"{name} 请求进入空闲状态")
                        else:
                            output = self._exec(name, tool_name, arguments)
                        
                        output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                        Logger.info(f"[{name}] 输出: {output_preview}")
                        
                        results.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(output)[:50000]
                        })
                    
                    messages.extend(results)
                    
                    if idle_requested:
                        Logger.autonomous(f"{name} 进入空闲阶段")
                        break
                    
                except Exception as e:
                    Logger.error(f"{name} 工作阶段错误: {e}")
                    self._set_status(name, "idle")
                    return
            
            # ============================================================
            # IDLE PHASE: 空闲阶段 - 轮询新任务
            # ============================================================
            if not idle_requested:
                Logger.autonomous(f"{name} 自动进入空闲阶段")
            
            self._set_status(name, "idle")
            resume = False
            
            # 空闲轮询
            polls = IDLE_TIMEOUT // POLL_INTERVAL
            Logger.info(f"{name} 空闲轮询: 每 {POLL_INTERVAL}s，最多 {polls} 次")
            
            for poll_count in range(polls):
                if self.stop_events.get(name, threading.Event()).is_set():
                    Logger.warning(f"{name} 在空闲时收到停止信号")
                    self._set_status(name, "shutdown")
                    return
                
                time.sleep(POLL_INTERVAL)
                Logger.info(f"{name} 空闲轮询 #{poll_count + 1}")
                
                # 1. 检查收件箱
                inbox = BUS.read_inbox(name)
                if inbox:
                    Logger.success(f"{name} 在空闲时收到 {len(inbox)} 条消息")
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            Logger.protocol(f"{name} 收到 shutdown 请求")
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})
                    resume = True
                    Logger.autonomous(f"{name} 因收到消息而恢复工作")
                    break
                
                # 2. 检查任务板
                unclaimed = scan_unclaimed_tasks()
                if unclaimed:
                    task = unclaimed[0]
                    claim_task(task["id"], name)
                    Logger.success(f"{name} 发现并认领任务 #{task['id']}")
                    
                    task_prompt = (
                        f"<auto-claimed>Task #{task['id']}: {task['subject']}\n"
                        f"{task.get('description', '')}</auto-claimed>"
                    )
                    
                    # 如果上下文太长，注入身份信息
                    if len(messages) <= 3:
                        Logger.info(f"{name} 注入身份信息")
                        messages.insert(0, make_identity_block(name, role, team_name))
                        messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
                    
                    messages.append({"role": "user", "content": task_prompt})
                    messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})
                    resume = True
                    Logger.autonomous(f"{name} 因认领任务而恢复工作")
                    break
            
            if not resume:
                Logger.warning(f"{name} 空闲超时 ({IDLE_TIMEOUT}s)，自动关闭")
                self._set_status(name, "shutdown")
                return
            
            Logger.autonomous(f"{name} 恢复工作")
            # 继续工作阶段循环

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        """执行队友的工具调用"""
        if tool_name == "bash":
            return _run_bash(args["command"])
        if tool_name == "read_file":
            return _run_read(args["path"], args.get("limit"))
        if tool_name == "write_file":
            return _run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return _run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        if tool_name == "read_inbox":
            msgs = BUS.read_inbox(sender)
            return json.dumps(msgs, indent=2, ensure_ascii=False)
        if tool_name == "shutdown_response":
            req_id = args["request_id"]
            approve = args["approve"]
            with _tracker_lock:
                if req_id in shutdown_requests:
                    shutdown_requests[req_id]["status"] = "approved" if approve else "rejected"
            BUS.send(
                sender, "lead", args.get("reason", ""),
                "shutdown_response", {"request_id": req_id, "approve": approve},
            )
            return f"Shutdown {'approved' if approve else 'rejected'}"
        if tool_name == "plan_approval":
            plan_text = args.get("plan", "")
            req_id = str(uuid.uuid4())[:8]
            with _tracker_lock:
                plan_requests[req_id] = {"from": sender, "plan": plan_text, "status": "pending"}
            BUS.send(
                sender, "lead", plan_text, "plan_approval_response",
                {"request_id": req_id, "plan": plan_text},
            )
            return f"Plan submitted (request_id={req_id}). Waiting for approval."
        if tool_name == "claim_task":
            return claim_task(args["task_id"], sender)
        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        """队友工具定义（OpenAI格式）"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute a shell command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"}
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read file contents.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "limit": {"type": "integer"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Replace text in file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"}
                        },
                        "required": ["path", "old_text", "new_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "send_message",
                    "description": "Send message to a teammate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string"},
                            "content": {"type": "string"},
                            "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}
                        },
                        "required": ["to", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_inbox",
                    "description": "Read and drain your inbox.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shutdown_response",
                    "description": "Respond to a shutdown request.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "string"},
                            "approve": {"type": "boolean"},
                            "reason": {"type": "string"}
                        },
                        "required": ["request_id", "approve"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "plan_approval",
                    "description": "Submit a plan for lead approval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "plan": {"type": "string"}
                        },
                        "required": ["plan"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "idle",
                    "description": "Signal that you have no more work. Enters idle polling phase.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "claim_task",
                    "description": "Claim a task from the task board by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "integer"}
                        },
                        "required": ["task_id"]
                    }
                }
            }
        ]

    def list_all(self) -> str:
        """列出所有队友"""
        if not self.config["members"]:
            return "No teammates."
        
        lines = [f"🏢 Team: {self.config['team_name']}"]
        lines.append("-" * 40)
        
        for m in self.config["members"]:
            status_icon = {
                "working": "🔄",
                "idle": "💤",
                "shutdown": "⏹️"
            }.get(m.get("status", "unknown"), "❓")
            lines.append(f"{status_icon} {m['name']} ({m['role']}): {m.get('status', 'unknown')}")
        
        return "\n".join(lines)

    def member_names(self) -> list:
        """获取所有队友名称"""
        return [m["name"] for m in self.config["members"]]

    def shutdown_teammate(self, name: str) -> str:
        """关闭队友"""
        if name in self.stop_events:
            Logger.autonomous(f"发送停止信号给 {name}")
            self.stop_events[name].set()
            return f"Shutdown signal sent to {name}"
        return f"Teammate {name} not found"


TEAM = TeammateManager(TEAM_DIR)


# ============================================================
# 基础工具实现
# ============================================================

def _safe_path(p: str) -> Path:
    """路径安全检查"""
    path = (WORKDIR / p).resolve()
    try:
        if not path.is_relative_to(WORKDIR):
            raise ValueError(f"Path escapes workspace: {p}")
    except AttributeError:
        if WORKDIR not in path.parents and WORKDIR != path:
            raise ValueError(f"Path escapes workspace: {p}")
    return path

def _run_bash(command: str) -> str:
    """执行bash命令"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "mkfs"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def _run_read(path: str, limit: int = None) -> str:
    """读取文件"""
    try:
        lines = _safe_path(path).read_text().splitlines()
        total_lines = len(lines)
        if limit and limit < total_lines:
            lines = lines[:limit] + [f"... ({total_lines - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def _run_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        fp = _safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def _run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件"""
    try:
        fp = _safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# 领导专用协议处理器
# ============================================================

def handle_shutdown_request(teammate: str) -> str:
    """处理 shutdown 请求"""
    req_id = str(uuid.uuid4())[:8]
    with _tracker_lock:
        shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send(
        "lead", teammate, "Please shut down gracefully.",
        "shutdown_request", {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}'"

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    """处理计划审批"""
    with _tracker_lock:
        req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    with _tracker_lock:
        req["status"] = "approved" if approve else "rejected"
    BUS.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {req['status']} for '{req['from']}'"

def check_shutdown_status(request_id: str) -> str:
    """检查 shutdown 状态"""
    with _tracker_lock:
        return json.dumps(shutdown_requests.get(request_id, {"error": "not found"}))

def create_test_task(subject: str) -> str:
    """创建测试任务"""
    task_id = create_task(subject, "")
    return f"Created test task #{task_id}: {subject}"


# ============================================================
# 领导工具定义（OpenAI格式）
# ============================================================

TOOL_HANDLERS = {
    "bash":              lambda **kw: _run_bash(kw["command"]),
    "read_file":         lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file":        lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file":         lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate":    lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":    lambda **kw: TEAM.list_all(),
    "send_message":      lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":        lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2, ensure_ascii=False),
    "broadcast":         lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "shutdown_request":  lambda **kw: handle_shutdown_request(kw["teammate"]),
    "shutdown_response": lambda **kw: check_shutdown_status(kw.get("request_id", "")),
    "plan_approval":     lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "create_test_task":  lambda **kw: create_test_task(kw["subject"]),
    "shutdown_teammate": lambda **kw: TEAM.shutdown_teammate(kw["name"]),
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace text in file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_teammate",
            "description": "Spawn an autonomous teammate that finds work itself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "prompt": {"type": "string"}
                },
                "required": ["name", "role", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_teammates",
            "description": "List all teammates with status.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message to a teammate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "content": {"type": "string"},
                    "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}
                },
                "required": ["to", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_inbox",
            "description": "Read and drain the lead's inbox.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast",
            "description": "Send a message to all teammates.",
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_request",
            "description": "Request a teammate to shut down.",
            "parameters": {
                "type": "object",
                "properties": {"teammate": {"type": "string"}},
                "required": ["teammate"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_response",
            "description": "Check shutdown request status.",
            "parameters": {
                "type": "object",
                "properties": {"request_id": {"type": "string"}},
                "required": ["request_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plan_approval",
            "description": "Approve or reject a teammate's plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "approve": {"type": "boolean"},
                    "feedback": {"type": "string"}
                },
                "required": ["request_id", "approve"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_test_task",
            "description": "Create a test task for autonomous agents to claim.",
            "parameters": {
                "type": "object",
                "properties": {"subject": {"type": "string"}},
                "required": ["subject"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_teammate",
            "description": "Force shutdown a teammate.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        }
    }
]


# ============================================================
# 领导主循环
# ============================================================

def agent_loop(messages: list):
    """领导主循环"""
    round_num = 0
    
    while True:
        round_num += 1
        Logger.separator("-", 80)
        Logger.info(f"🔄 领导第 {round_num} 轮")
        
        # 检查收件箱
        inbox = BUS.read_inbox("lead")
        if inbox:
            Logger.info(f"领导收到 {len(inbox)} 条消息")
            messages.append({
                "role": "user",
                "content": f"<inbox>\n{json.dumps(inbox, indent=2, ensure_ascii=False)}\n</inbox>"
            })
            messages.append({
                "role": "assistant",
                "content": "Noted inbox messages. I'll process them."
            })
        
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + messages,
                tools=TOOLS,
                max_tokens=8000,
                temperature=0.7
            )
            
            assistant_message = response.choices[0].message
            
            if assistant_message.content:
                Logger.info(f"💬 领导响应: {assistant_message.content[:150]}...")
            
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            if not assistant_message.tool_calls:
                Logger.success("领导本轮结束")
                return
            
            results = []
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                Logger.tool_call("lead", tool_name, arguments)
                
                handler = TOOL_HANDLERS.get(tool_name)
                try:
                    output = handler(**arguments) if handler else f"Unknown tool: {tool_name}"
                except Exception as e:
                    output = f"Error: {e}"
                    Logger.error(f"工具执行失败: {e}")
                
                output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                Logger.info(f"工具输出: {output_preview}")
                
                results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50000]
                })
            
            messages.extend(results)
            
        except Exception as e:
            Logger.error(f"领导循环错误: {e}")
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
    Logger.section("📊 自治Agent系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    print(f"   任务目录: {TASKS_DIR}")
    print(f"   空闲轮询间隔: {POLL_INTERVAL}s")
    print(f"   空闲超时: {IDLE_TIMEOUT}s")
    print()
    print("   当前团队成员:")
    print(TEAM.list_all())
    
    # 显示任务统计
    if TASKS_DIR.exists():
        tasks = list(TASKS_DIR.glob("task_*.json"))
        if tasks:
            pending = 0
            in_progress = 0
            completed = 0
            for f in tasks:
                try:
                    task = json.loads(f.read_text())
                    status = task.get("status", "unknown")
                    if status == "pending":
                        pending += 1
                    elif status == "in_progress":
                        in_progress += 1
                    elif status == "completed":
                        completed += 1
                except:
                    pass
            print(f"\n   任务统计: 待处理 {pending} | 进行中 {in_progress} | 已完成 {completed}")
    
    Logger.separator("-")


if __name__ == "__main__":
    Logger.section("🚀 DeepSeek Autonomous Agents System 启动")
    print_status()
    
    print("\n📖 自治Agent系统说明:")
    print("   🤖 自治行为: Agent 在没有指令的情况下主动寻找工作")
    print("   📋 任务板: 未认领的任务自动被空闲 Agent 认领")
    print("   💤 空闲轮询: 空闲时每 5 秒检查一次新任务")
    print("   🔄 生命周期: 工作 -> 空闲 -> 工作 -> ... -> 超时关闭")
    print("   🆔 身份注入: 上下文压缩后自动注入身份信息")
    print()
    print("📚 领导可用工具:")
    print("   • spawn_teammate      - 生成自治队友")
    print("   • list_teammates      - 列出所有队友")
    print("   • create_test_task    - 创建测试任务")
    print("   • send_message        - 发送消息给队友")
    print("   • broadcast           - 广播消息")
    print("   • shutdown_request    - 请求队友关闭")
    print("   • shutdown_teammate   - 强制关闭队友")
    print()
    print("💡 使用示例:")
    print("   • '生成一个后端开发 alice，让她处理 API 开发'")
    print("   • '创建测试任务: 实现用户登录功能'")
    print("   • '列出所有队友'")
    print("   • '请求 alice 关闭'")
    print()
    print("🔄 自治流程:")
    print("   1. 领导生成自治队友")
    print("   2. 队友进入工作阶段，执行任务")
    print("   3. 无任务时调用 idle 进入空闲阶段")
    print("   4. 空闲时每 5 秒检查收件箱和任务板")
    print("   5. 发现新任务后自动认领并恢复工作")
    print("   6. 空闲超时 60 秒后自动关闭")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • '/team' - 查看所有队友")
    print("   • '/inbox' - 查看领导的收件箱")
    print("   • '/tasks' - 查看任务板")
    print("   • '/status' - 查看系统状态")
    print("   • 'clear' - 清空对话历史")
    print("   • 'exit' 或 'q' - 退出程序")
    Logger.separator("=")
    
    history = []
    
    while True:
        try:
            query = input("\n\033[36m📝 领导 >> \033[0m").strip()
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
        
        if query.lower() == '/status':
            print_status()
            continue
        
        if query.strip() == '/team':
            print(TEAM.list_all())
            continue
        
        if query.strip() == '/inbox':
            inbox = BUS.read_inbox("lead")
            if inbox:
                print(json.dumps(inbox, indent=2, ensure_ascii=False))
            else:
                print("收件箱为空")
            continue
        
        if query.strip() == '/tasks':
            TASKS_DIR.mkdir(exist_ok=True)
            tasks_found = False
            for f in sorted(TASKS_DIR.glob("task_*.json")):
                tasks_found = True
                t = json.loads(f.read_text())
                marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
                owner = f" @{t['owner']}" if t.get("owner") else ""
                print(f"  {marker} #{t['id']}: {t['subject']}{owner}")
            if not tasks_found:
                print("任务板为空")
            continue
        
        if not query:
            continue
        
        history.append({"role": "user", "content": query})
        Logger.info(f"📨 领导收到: {query}")
        
        agent_loop(history)
        
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 领导 >>\033[0m")
            print(f"{last_msg['content']}")
        
        # 显示活跃队友状态
        active_members = [m for m in TEAM.config["members"] 
                         if m.get("status") in ("working", "idle")]
        if active_members:
            Logger.info("活跃队友:")
            for m in active_members:
                Logger.info(f"  - {m['name']}: {m['status']}")
        
        Logger.separator("=")