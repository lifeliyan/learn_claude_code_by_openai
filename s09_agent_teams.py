#!/usr/bin/env python3
# Harness: team mailboxes -- multiple models, coordinated through files.
"""
s09_agent_teams.py - Agent Teams (DeepSeek版本)

Persistent named agents with file-based JSONL inboxes. Each teammate runs
its own agent loop in a separate thread. Communication via append-only inboxes.

    Subagent (s04):  spawn -> execute -> return summary -> destroyed
    Teammate (s09):  spawn -> work -> idle -> work -> ... -> shutdown

    .team/config.json                   .team/inbox/
    +----------------------------+      +------------------+
    | {"team_name": "default",   |      | alice.jsonl      |
    |  "members": [              |      | bob.jsonl        |
    |    {"name":"alice",        |      | lead.jsonl       |
    |     "role":"coder",        |      +------------------+
    |     "status":"idle"}       |
    |  ]}                        |      send_message("alice", "fix bug"):
    +----------------------------+        open("alice.jsonl", "a").write(msg)

                                        read_inbox("alice"):
    spawn_teammate("alice","coder",...)   msgs = [json.loads(l) for l in ...]
         |                                open("alice.jsonl", "w").close()
         v                                return msgs  # drain
    Thread: alice             Thread: bob
    +------------------+      +------------------+
    | agent_loop       |      | agent_loop       |
    | status: working  |      | status: idle     |
    | ... runs tools   |      | ... waits ...    |
    | status -> idle   |      |                  |
    +------------------+      +------------------+

    5 message types (all declared, not all handled here):
    +-------------------------+-----------------------------------+
    | message                 | Normal text message               |
    | broadcast               | Sent to all teammates             |
    | shutdown_request        | Request graceful shutdown (s10)   |
    | shutdown_response       | Approve/reject shutdown (s10)     |
    | plan_approval_response  | Approve/reject plan (s10)         |
    +-------------------------+-----------------------------------+

Key insight: "Teammates that can talk to each other."
"""

import json
import os
import subprocess
import threading
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
    def team(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[35m[{timestamp}] 👥 {message}\033[0m")
    
    @staticmethod
    def message(from_agent: str, to_agent: str, content: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\033[36m[{timestamp}] 📨 [{from_agent} -> {to_agent}] {content[:80]}\033[0m")
    
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

SYSTEM = f"""You are a team lead at {WORKDIR}. Spawn teammates and communicate via inboxes.

Team Lead Responsibilities:
1. Spawn teammates with specific roles when complex tasks arise
2. Coordinate work by sending messages to teammates
3. Monitor team progress through inbox messages
4. Broadcast important information to all teammates
5. Manage team lifecycle (spawn, idle, shutdown)
"""

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}


# ============================================================
# MessageBus: JSONL inbox per teammate
# ============================================================

class MessageBus:
    """
    消息总线：基于文件的邮箱系统
    每个队友有独立的 JSONL 格式的收件箱
    """
    
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        Logger.team(f"消息总线初始化，目录: {self.dir}")

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        """
        发送消息给指定的队友
        """
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
        with open(inbox_path, "a") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        Logger.message(sender, to, content)
        Logger.info(f"消息类型: {msg_type}, 收件箱: {inbox_path}")
        
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        """
        读取并清空收件箱（drain）
        """
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            Logger.info(f"收件箱 {name}.jsonl 不存在")
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
                        Logger.error(f"解析消息失败: {e}, 内容: {line[:100]}")
        
        # 清空收件箱
        if messages:
            Logger.info(f"读取 {name} 的收件箱: {len(messages)} 条消息")
            for msg in messages:
                Logger.info(f"  - 来自 {msg.get('from', 'unknown')}: {msg.get('content', '')[:50]}")
            inbox_path.write_text("", encoding='utf-8')
        else:
            Logger.info(f"收件箱 {name}.jsonl 为空")
        
        return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        """
        广播消息给所有队友
        """
        Logger.team(f"广播消息: 从 {sender} 到 {len(teammates)} 个队友")
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


# ============================================================
# TeammateManager: persistent named agents with config.json
# ============================================================

class TeammateManager:
    """
    队友管理器：管理持久化的命名 Agent
    每个队友在独立线程中运行自己的 agent 循环
    """
    
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}  # name -> thread
        self.stop_events = {}  # name -> threading.Event for graceful shutdown
        
        Logger.team(f"队友管理器初始化，配置: {self.config_path}")
        self._log_team_status()

    def _load_config(self) -> dict:
        """加载团队配置"""
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text())
            Logger.info(f"加载现有配置: {len(config.get('members', []))} 个队友")
            return config
        default_config = {"team_name": "default", "members": []}
        Logger.info("创建新团队配置")
        return default_config

    def _save_config(self):
        """保存团队配置"""
        self.config_path.write_text(json.dumps(self.config, indent=2, ensure_ascii=False))
        Logger.info(f"配置已保存: {len(self.config['members'])} 个队友")

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
        """
        生成一个新的队友（在独立线程中运行）
        """
        Logger.team(f"尝试生成队友: {name} (角色: {role})")
        
        # 检查是否已存在
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                Logger.warning(f"队友 {name} 正在运行中，状态: {member['status']}")
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
            Logger.info(f"唤醒已存在的队友: {name}")
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
            Logger.success(f"创建新队友: {name}")
        
        self._save_config()
        
        # 创建停止事件用于优雅关闭
        self.stop_events[name] = threading.Event()
        
        # 启动队友线程
        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
            name=f"Teammate-{name}"
        )
        self.threads[name] = thread
        thread.start()
        
        Logger.success(f"队友 {name} 已启动 (线程: {thread.name})")
        return f"Spawned '{name}' (role: {role})"

    def _teammate_loop(self, name: str, role: str, prompt: str):
        """
        队友的主循环（在独立线程中运行）
        """
        thread_name = threading.current_thread().name
        Logger.team(f"[{name}] 线程启动: {thread_name}")
        
        sys_prompt = (
            f"You are '{name}', role: {role}, at {WORKDIR}. "
            f"Use send_message to communicate with teammates. "
            f"Use read_inbox to check for messages from the lead or other teammates. "
            f"Complete your assigned task and then go idle."
        )
        
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()
        iteration = 0
        max_iterations = 50
        
        Logger.info(f"[{name}] 开始执行任务: {prompt[:100]}...")
        
        while iteration < max_iterations:
            iteration += 1
            Logger.info(f"[{name}] 第 {iteration} 轮")
            
            # 检查是否收到停止信号
            if self.stop_events.get(name, threading.Event()).is_set():
                Logger.warning(f"[{name}] 收到停止信号，退出循环")
                break
            
            # 读取收件箱
            inbox = BUS.read_inbox(name)
            if inbox:
                Logger.info(f"[{name}] 收到 {len(inbox)} 条消息")
                for msg in inbox:
                    messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})
            
            try:
                # 调用 DeepSeek API
                Logger.info(f"[{name}] 调用 API...")
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": sys_prompt}] + messages,
                    tools=tools,
                    max_tokens=8000,
                    temperature=0.7
                )
                
                assistant_message = response.choices[0].message
                
                # 记录响应
                if assistant_message.content:
                    Logger.info(f"[{name}] 响应: {assistant_message.content[:100]}...")
                
                # 添加到历史
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": assistant_message.tool_calls
                })
                
                # 如果没有工具调用，任务完成
                if not assistant_message.tool_calls:
                    Logger.success(f"[{name}] 任务完成，进入空闲状态")
                    break
                
                # 处理工具调用
                tool_results = []
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    Logger.tool_call(name, tool_name, arguments)
                    
                    # 执行工具
                    output = self._exec(name, tool_name, arguments)
                    
                    output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)
                    Logger.info(f"[{name}] 工具输出: {output_preview}")
                    
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(output)[:50000]
                    })
                
                messages.extend(tool_results)
                
            except Exception as e:
                Logger.error(f"[{name}] 执行错误: {e}")
                break
        
        # 更新状态为空闲
        member = self._find_member(name)
        if member and member.get("status") != "shutdown":
            member["status"] = "idle"
            self._save_config()
            Logger.success(f"[{name}] 状态已更新为 idle")
        
        Logger.team(f"[{name}] 线程结束，共执行 {iteration} 轮")

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        """
        执行队友的工具调用
        """
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
        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        """
        队友可用的工具（OpenAI格式）
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute a shell command.",
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
                    "description": "Read contents of a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to the file"},
                            "limit": {"type": "integer", "description": "Maximum lines to read"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path where to write"},
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
                    "description": "Replace text in a file.",
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
                    "name": "send_message",
                    "description": "Send a message to a teammate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient name"},
                            "content": {"type": "string", "description": "Message content"},
                            "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES), "description": "Message type"}
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
        """优雅关闭队友"""
        if name in self.stop_events:
            Logger.team(f"发送停止信号给队友 {name}")
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
        Logger.warning(f"阻止危险命令: {command}")
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
        return f"Wrote {len(content)} bytes to {path}"
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
# 领导工具（Lead tools）
# ============================================================

TOOL_HANDLERS = {
    "bash":            lambda **kw: _run_bash(kw["command"]),
    "read_file":       lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file":      lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file":       lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate":  lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":  lambda **kw: TEAM.list_all(),
    "send_message":    lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":      lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2, ensure_ascii=False),
    "broadcast":       lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
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
            "description": "Read contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "limit": {"type": "integer", "description": "Maximum lines to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path where to write"},
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
            "description": "Replace text in a file.",
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
            "name": "spawn_teammate",
            "description": "Spawn a persistent teammate that runs in its own thread.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Teammate name"},
                    "role": {"type": "string", "description": "Teammate role (e.g., coder, reviewer)"},
                    "prompt": {"type": "string", "description": "Task description for the teammate"}
                },
                "required": ["name", "role", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_teammates",
            "description": "List all teammates with their status.",
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
            "description": "Send a message to a teammate's inbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name"},
                    "content": {"type": "string", "description": "Message content"},
                    "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES), "description": "Message type"}
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
    }
]


# ============================================================
# 领导主循环
# ============================================================

def agent_loop(messages: list):
    """领导的主循环"""
    round_num = 0
    
    while True:
        round_num += 1
        Logger.separator("-", 80)
        Logger.info(f"🔄 领导第 {round_num} 轮")
        
        # 检查领导自己的收件箱
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
            
            # 记录响应
            if assistant_message.content:
                Logger.info(f"💬 领导响应: {assistant_message.content[:150]}...")
            
            # 添加到历史
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            })
            
            # 如果没有工具调用，结束
            if not assistant_message.tool_calls:
                Logger.success("领导本轮结束")
                return
            
            # 处理工具调用
            tool_results = []
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
                
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50000]
                })
            
            messages.extend(tool_results)
            
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
    Logger.section("📊 多Agent团队系统状态")
    print(f"   工作目录: {WORKDIR}")
    print(f"   使用模型: {MODEL}")
    print(f"   团队目录: {TEAM_DIR}")
    print(f"   收件箱目录: {INBOX_DIR}")
    print()
    print(f"   有效消息类型: {', '.join(VALID_MSG_TYPES)}")
    print()
    print("   当前团队成员:")
    print(TEAM.list_all())
    Logger.separator("-")


if __name__ == "__main__":
    Logger.section("🚀 DeepSeek Multi-Agent Team System 启动")
    print_status()
    
    print("\n📖 多Agent团队系统说明:")
    print("   👥 持久化队友: 队友在独立线程中运行，状态持久化")
    print("   📨 消息传递: 基于文件的JSONL收件箱系统")
    print("   🔄 异步通信: 队友间可以互相发送消息")
    print("   💤 空闲状态: 任务完成后自动进入空闲，可被唤醒")
    print("   🎭 角色分工: 每个队友有特定角色和系统提示")
    print()
    print("📚 领导可用工具:")
    print("   • spawn_teammate   - 生成新的队友")
    print("   • list_teammates   - 列出所有队友")
    print("   • send_message     - 发送消息给队友")
    print("   • read_inbox       - 读取领导的收件箱")
    print("   • broadcast        - 广播消息给所有队友")
    print("   • bash/read/write  - 标准文件操作")
    print()
    print("💡 使用示例:")
    print("   • '生成一个代码审查员 alice，让她审查 app.py'")
    print("   • '给 bob 发送消息: 请修复这个bug'")
    print("   • '列出所有队友'")
    print("   • '广播: 项目已完成'")
    print()
    print("🔄 架构说明:")
    print("   1. 领导负责协调和分配任务")
    print("   2. 每个队友在独立线程中运行自己的 Agent 循环")
    print("   3. 通信通过文件收件箱实现（JSONL格式）")
    print("   4. 读取收件箱即清空（drain模式）")
    print("   5. 队友完成任务后自动进入空闲状态")
    print()
    print("⌨️  命令:")
    print("   • 输入任意问题开始对话")
    print("   • '/team' - 查看所有队友")
    print("   • '/inbox' - 查看领导的收件箱")
    print("   • 'status' - 查看系统状态")
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
        
        if query.lower() == 'status':
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
        
        # 添加用户消息到历史
        history.append({"role": "user", "content": query})
        Logger.info(f"📨 领导收到用户输入: {query}")
        
        # 运行领导循环
        agent_loop(history)
        
        # 打印最终响应
        last_msg = history[-1]
        if last_msg.get("content"):
            print(f"\n\033[32m🤖 领导 >>\033[0m")
            print(f"{last_msg['content']}")
        
        # 显示团队成员状态
        if TEAM.config["members"]:
            Logger.team("当前团队状态:")
            print(TEAM.list_all())
        
        Logger.separator("=")