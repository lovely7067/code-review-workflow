"""工作流状态：Agent 间通信与状态共享的中心（黑板模式 / Blackboard）。

设计要点：
- 所有 Agent 不直接互相调用，只读写同一个 WorkflowState
- artifacts（共享产物）承担"数据传递"，messages（消息）承担"通信记录"
- history（步骤日志）用于状态追踪与事后回溯
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """Agent 之间传递的一条消息。"""
    sender: str
    receiver: str
    content: str
    meta: dict = field(default_factory=dict)

    def brief(self, limit: int = 80) -> str:
        text = self.content.replace("\n", " ")
        if len(text) > limit:
            text = text[:limit] + "..."
        return f"{self.sender} -> {self.receiver}: {text}"


class WorkflowState:
    """工作流全局状态（所有 Agent 共享）。"""

    def __init__(self, task_name: str, requirement: str):
        self.task_name = task_name
        self.requirement = requirement
        self.task_id = time.strftime("%Y%m%d-%H%M%S")
        self.artifacts: dict[str, Any] = {}       # 共享产物：generated_code / review_report / fixed_code ...
        self.messages: list[Message] = []          # Agent 间消息记录
        self.history: list[dict] = []              # 步骤执行记录
        self.status = "pending"                    # pending / running / completed / failed
        self.started_at = time.time()

    # ---------- 状态共享（产物读写） ----------

    def set(self, key: str, value: Any, by: str) -> None:
        """写入共享产物，并自动广播一条状态更新消息。"""
        self.artifacts[key] = value
        self.post_message(
            sender=by,
            receiver="state",
            content=f"写入产物 [{key}]，长度 {len(str(value))} 字符",
            meta={"artifact": key},
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)

    def has(self, key: str) -> bool:
        return bool(self.artifacts.get(key))

    # ---------- Agent 间通信 ----------

    def post_message(self, sender: str, receiver: str, content: str, meta: dict | None = None) -> None:
        self.messages.append(Message(sender, receiver, content, meta or {}))

    def get_messages(self, receiver: str | None = None) -> list[Message]:
        if receiver is None:
            return list(self.messages)
        return [m for m in self.messages if m.receiver == receiver]

    # ---------- 状态追踪 ----------

    def add_history(self, step: str, status: str, detail: str, duration: float = 0.0) -> None:
        self.history.append({
            "step": step,
            "status": status,        # ok / skipped / failed
            "detail": detail,
            "duration": round(duration, 2),
            "time": time.strftime("%H:%M:%S"),
        })

    # ---------- 输出 ----------

    def summary(self) -> dict:
        """状态摘要，用于最终报告与日志文件。"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "requirement": self.requirement,
            "status": self.status,
            "artifacts": {
                k: (f"<{len(str(v))} 字符>") for k, v in self.artifacts.items()
            },
            "message_count": len(self.messages),
            "elapsed": round(time.time() - self.started_at, 2),
            "history": self.history,
        }

    def save_report(self, path: str) -> None:
        """把状态摘要写入 JSON 文件（状态追踪落盘）。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=2)
