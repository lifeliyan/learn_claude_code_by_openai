#!/usr/bin/env python3
# Harness: protocols -- structured handshakes between models.
"""
s10_team_protocols.py - Team Protocols (DeepSeek版本)

Shutdown protocol and plan approval protocol, both using the same
request_id correlation pattern. Builds on s09's team messaging.

    Shutdown FSM: pending -> approved | rejected

    Lead                              Teammate
    +---------------------+          +---------------------+
    | shutdown_request     |          |                     |
    | {                    | -------> | receives request    |
    |   request_id: abc    |          | decides: approve?   |
    | }                    |          |                     |
    +---------------------+          +---------------------+
                                             |
    +---------------------+          +-------v-------------+
    | shutdown_response    | <------- | shutdown_response   |
    | {                    |          | {                   |
    |   request_id: abc    |          |   request_id: abc   |
    |   approve: true      |          |   approve: true     |
    | }                    |          | }                   |
    +---------------------+          +---------------------+
            |
            v
    status -> "shutdown", thread stops

    Plan approval FSM: pending -> approved | rejected

    Teammate                          Lead
    +---------------------+          +---------------------+
    | plan_approval        |          |                     |
    | submit: {plan:"..."}| -------> | reviews plan text   |
    +---------------------+          | approve/reject?     |
                                     +---------------------+
                                             |
    +---------------------+          +-------v-------------+
    | plan_approval_resp   | <------- | plan_approval       |
    | {approve: true}      |          | review: {req_id,    |
    +---------------------+          |   approve: true}     |
                                     +---------------------+

    Trackers: {request_id: {"target|from": name, "status": "pending|..."}}

Key insight: "Same request_id correlation pattern, two domains."
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
    def protocol(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 🔐 {message}\033[0m")
    
    @staticmethod
    def team(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[36m[{timestamp}] 👥 {message}\033[0m")
    
    @staticmethod
    def message(from_agent: str, to_agent: str, content: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[33m[{timestamp}] 📨 [{from_agent} -> {to_agent}] {content[:80]}\033[0m")
    
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

SYSTEM = f"""You are a team lead at {WORKDIR}. Manage teammates with shutdown and plan approval protocols.

Protocol Guidelines:
1. Shutdown Protocol: Request teammate shutdown, wait for response, confirm completion
2. Plan Approval Protocol: Review teammate plans, approve/reject with feedback
3. Use request_id to track all protocol interactions
4. Always verify protocol state before proceeding
"""

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}

# ============================================================
# Request trackers: correlate by request_id
# ============================================================

shutdown_requests = {}  # request_id -> {target, status, timestamp}
plan_requests = {}      # request_id -> {from, plan, status, timestamp}
_tracker_lock = threading.Lock()


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
            Logger.protocol(f"消息包含协议数据: {list(extra.keys())}")
        
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        Logger.message(sender, to, content[:100])
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
                        if msg.get("type") in ["shutdown_request", "shutdown_response", 
                                                "plan_approval_response"]:
                            Logger.protocol(f"协议消息: {msg['type']} from {msg.get('from')}")
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
# TeammateManager with shutdown + plan approval
# ============================================================

class TeammateManager:
    """队友管理器，支持 shutdown 和 plan approval 协议"""
    
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}
        self.stop_events = {}
        
        Logger.team(f"队友管理器初始化，配置: {self.config_path}")
        self._log_team_status()

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
        Logger.info(f"配置已保存")

    def _find_member(self, name: str) -> dict:
        """查找队友"""
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _log_team_status(self):
        """记录团队状态"""
        if self.config["members"]:
            Logger.team("当前团队成员:")
            for m in self.config["members"]:
                Logger.team(f"  - {m['name']} ({m['role']}): {m.get('status', 'unknown')}")

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """生成队友"""
        Logger.team(f"生成队友: {name} (角色: {role})")
        
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
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
            name=f"Teammate-{name}"
        )
        self.threads[name] = thread
        thread.start()
        
        Logger.success(f"队友 {name} 已启动")
        return f"Spawned '{name}' (role: {role})"

    def _teammate_loop(self, name: str, role: str, prompt: str):
        """队友主循环"""
        Logger.team(f"[{name}] 线程启动，角色: {role}")
        
        sys_prompt = (
            f"You are '{name}', role: {role}, at {WORKDIR}. "
            f"Submit plans via plan_approval before major work. "
            f"Respond to shutdown_request with shutdown_response. "
            f"Use send_message to communicate with teammates."
        )
        
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()
        should_exit = False
        iteration = 0
        max_iterations = 50
        
        while iteration < max_iterations:
            iteration += 1
            Logger.info(f"[{name}] 第 {iteration} 轮")
            
            # 检查停止信号
            if self.stop_events.get(name, threading.Event()).is_set():
                Logger.warning(f"[{name}] 收到停止信号")
                should_exit = True
                break
            
            # 读取收件箱
            inbox = BUS.read_inbox(name)
            if inbox:
                Logger.info(f"[{name}] 收到 {len(inbox)} 条消息")
                for msg in inbox:
                    messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})
                    
                    # 记录协议消息
                    if msg.get("type") == "shutdown_request":
                        Logger.protocol(f"[{name}] 收到 shutdown 请求: {msg.get('request_id')}")
            
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
                    Logger.info(f"[{name}] 响应: {assistant_message.content[:100]}...")
                
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": assistant_message.tool_calls
                })
                
                if not assistant_message.tool_calls:
                    Logger.info(f"[{name}] 无工具调用，结束本轮")
                    break
                
                results = []
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    Logger.tool_call(name, tool_name, arguments)
                    
                    output = self._exec(name, tool_name, arguments)
                    
                    # 检查是否触发退出
                    if tool_name == "shutdown_response" and arguments.get("approve"):
                        should_exit = True
                        Logger.protocol(f"[{name}] 批准 shutdown，准备退出")
                    
                    output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                    Logger.info(f"[{name}] 输出: {output_preview}")
                    
                    results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(output)[:50000]
                    })
                
                messages.extend(results)
                
            except Exception as e:
                Logger.error(f"[{name}] 错误: {e}")
                break
        
        # 更新状态
        member = self._find_member(name)
        if member:
            new_status = "shutdown" if should_exit else "idle"
            member["status"] = new_status
            self._save_config()
            Logger.success(f"[{name}] 状态更新: {new_status}")
        
        Logger.team(f"[{name}] 线程结束")

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
                    shutdown_requests[req_id]["responded_at"] = datetime.now().isoformat()
                    Logger.protocol(f"Shutdown 请求 {req_id}: {'批准' if approve else '拒绝'}")
            
            BUS.send(
                sender, "lead", args.get("reason", ""),
                "shutdown_response", {"request_id": req_id, "approve": approve},
            )
            return f"Shutdown {'approved' if approve else 'rejected'}"
        
        if tool_name == "plan_approval":
            plan_text = args.get("plan", "")
            req_id = str(uuid.uuid4())[:8]
            with _tracker_lock:
                plan_requests[req_id] = {
                    "from": sender,
                    "plan": plan_text,
                    "status": "pending",
                    "created_at": datetime.now().isoformat()
                }
            Logger.protocol(f"Plan 请求 {req_id}: 来自 {sender}, 计划: {plan_text[:100]}")
            
            BUS.send(
                sender, "lead", plan_text, "plan_approval_response",
                {"request_id": req_id, "plan": plan_text},
            )
            return f"Plan submitted (request_id={req_id}). Waiting for lead approval."
        
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
                            "command": {"type": "string", "description": "Command to execute"}
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
                            "path": {"type": "string", "description": "File path"},
                            "limit": {"type": "integer", "description": "Max lines"}
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
                            "path": {"type": "string", "description": "File path"},
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
                    "description": "Replace text in file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
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
                    "name": "send_message",
                    "description": "Send a message to a teammate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient"},
                            "content": {"type": "string", "description": "Message"},
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
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shutdown_response",
                    "description": "Respond to shutdown request.",
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
                            "plan": {"type": "string", "description": "Plan description"}
                        },
                        "required": ["plan"]
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
        shutdown_requests[req_id] = {
            "target": teammate,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
    Logger.protocol(f"发送 shutdown 请求 {req_id} 给 {teammate}")
    
    BUS.send(
        "lead", teammate, "Please shut down gracefully.",
        "shutdown_request", {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}' (status: pending)"

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    """处理计划审批"""
    with _tracker_lock:
        req = plan_requests.get(request_id)
    
    if not req:
        Logger.error(f"未知的 plan 请求: {request_id}")
        return f"Error: Unknown plan request_id '{request_id}'"
    
    with _tracker_lock:
        req["status"] = "approved" if approve else "rejected"
        req["reviewed_at"] = datetime.now().isoformat()
        req["feedback"] = feedback
    
    Logger.protocol(f"Plan 请求 {request_id}: {'批准' if approve else '拒绝'} - {feedback[:100]}")
    
    BUS.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {req['status']} for '{req['from']}'"

def check_shutdown_status(request_id: str) -> str:
    """检查 shutdown 请求状态"""
    with _tracker_lock:
        req = shutdown_requests.get(request_id)
        if req:
            Logger.protocol(f"查询 shutdown 请求 {request_id}: {req['status']}")
            return json.dumps(req, indent=2, ensure_ascii=False)
    return json.dumps({"error": "not found"})

def list_pending_plans() -> str:
    """列出待处理的计划"""
    with _tracker_lock:
        pending = {rid: req for rid, req in plan_requests.items() 
                  if req["status"] == "pending"}
    
    if not pending:
        return "No pending plans"
    
    lines = ["待审批计划:"]
    for rid, req in pending.items():
        lines.append(f"  {rid}: from {req['from']} - {req['plan'][:100]}")
    return "\n".join(lines)


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
    "list_pending_plans": lambda **kw: list_pending_plans(),
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"}
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
                    "path": {"type": "string", "description": "File path"},
                    "limit": {"type": "integer", "description": "Max lines"}
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
                    "path": {"type": "string", "description": "File path"},
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
            "description": "Replace text in file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
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
            "name": "spawn_teammate",
            "description": "Spawn a persistent teammate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Teammate name"},
                    "role": {"type": "string", "description": "Teammate role"},
                    "prompt": {"type": "string", "description": "Task description"}
                },
                "required": ["name", "role", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_teammates",
            "description": "List all teammates.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
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
                    "to": {"type": "string", "description": "Recipient"},
                    "content": {"type": "string", "description": "Message"},
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
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast",
            "description": "Send a message to all teammates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Message to broadcast"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_request",
            "description": "Request a teammate to shut down gracefully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "teammate": {"type": "string", "description": "Teammate name"}
                },
                "required": ["teammate"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_response",
            "description": "Check the status of a shutdown request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Request ID to check"}
                },
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
                    "request_id": {"type": "string", "description": "Request ID"},
                    "approve": {"type": "boolean", "description": "True to approve, false to reject"},
                    "feedback": {"type": "string", "description": "Optional feedback"}
                },
                "required": ["request_id", "approve"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_plans",
            "description": "List all pending plan approval requests.",
            "parameters": {
                "type": "object",
                "properties": {}
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
    Logger.section("📊 多Agent协议系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    print(f"   团队目录: {TEAM_DIR}")
    print()
    
    with _tracker_lock:
        print(f"   活跃协议:")
        print(f"     - Shutdown 请求: {len(shutdown_requests)}")
        print(f"     - Plan 请求: {len(plan_requests)}")
        
        pending_shutdown = [rid for rid, req in shutdown_requests.items() 
                           if req["status"] == "pending"]
        if pending_shutdown:
            print(f"      待处理 shutdown: {pending_shutdown}")
        
        pending_plans = [rid for rid, req in plan_requests.items() 
                        if req["status"] == "pending"]
        if pending_plans:
            print(f"      待审批计划: {pending_plans}")
    
    print()
    print("   当前团队成员:")
    print(TEAM.list_all())
    Logger.separator("-")


if __name__ == "__main__":
    Logger.section("🚀 DeepSeek Team Protocols System 启动")
    print_status()
    
    print("\n📖 协议系统说明:")
    print("   🔐 Shutdown 协议: 领导请求队友关闭，队友响应批准/拒绝")
    print("   📋 Plan Approval 协议: 队友提交计划，领导审批")
    print("   🆔 Request ID: 所有协议使用 request_id 关联请求和响应")
    print("   📊 状态跟踪: shutdown_requests 和 plan_requests 全局跟踪器")
    print()
    print("📚 领导可用协议工具:")
    print("   • shutdown_request   - 请求队友关闭")
    print("   • shutdown_response  - 检查关闭请求状态")
    print("   • plan_approval      - 审批队友的计划")
    print("   • list_pending_plans - 列出待审批的计划")
    print("   • spawn_teammate     - 生成队友")
    print("   • list_teammates     - 列出所有队友")
    print("   • send_message       - 发送消息")
    print("   • broadcast          - 广播消息")
    print()
    print("💡 使用示例:")
    print("   • '生成队友 alice，让她实现一个功能'")
    print("   • '请求 alice 关闭'")
    print("   • '审批计划 req_123，批准'")
    print("   • '列出待审批的计划'")
    print("   • '查看关闭请求状态 req_456'")
    print()
    print("🔄 协议流程:")
    print("   Shutdown 协议:")
    print("     1. 领导调用 shutdown_request('alice')")
    print("     2. 系统生成 request_id，发送 shutdown_request 消息")
    print("     3. alice 收到请求，决定是否批准")
    print("     4. alice 发送 shutdown_response")
    print("     5. 领导可以查询状态")
    print()
    print("   Plan Approval 协议:")
    print("     1. 队友调用 plan_approval('计划内容')")
    print("     2. 系统生成 request_id，发送 plan_approval_response")
    print("     3. 领导收到通知，调用 plan_approval 审批")
    print("     4. 队友收到审批结果")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • '/team' - 查看所有队友")
    print("   • '/inbox' - 查看领导的收件箱")
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
        
        if not query:
            continue
        
        history.append({"role": "user", "content": query})
        Logger.info(f"📨 领导收到: {query}")
        
        agent_loop(history)
        
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 领导 >>\033[0m")
            print(f"{last_msg['content']}")
        
        # 显示活跃协议
        with _tracker_lock:
            if shutdown_requests or plan_requests:
                Logger.info("活跃协议:")
                for rid, req in shutdown_requests.items():
                    if req["status"] == "pending":
                        Logger.info(f"  - Shutdown {rid}: {req['target']} - {req['status']}")
                for rid, req in plan_requests.items():
                    if req["status"] == "pending":
                        Logger.info(f"  - Plan {rid}: {req['from']} - {req['plan'][:50]}...")
        
        Logger.separator("=")