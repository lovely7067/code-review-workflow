"""Agent 抽象基类 + 注册机制。

可扩展性设计：新增一个 Agent 只需三步 ——
1. 继承 BaseAgent 并实现 run()
2. 用 @register_agent("名字") 装饰
3. 在 pipeline 中把名字加进流程配置
无需修改引擎代码。
"""
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from workflow.state import WorkflowState


@dataclass
class AgentResult:
    """Agent 一次执行的返回结果。"""
    agent: str
    output: str
    meta: dict = field(default_factory=dict)

    def brief(self, limit: int = 100) -> str:
        text = self.output.replace("\n", " ")
        return text[:limit] + ("..." if len(text) > limit else "")


# ---------- 注册表：名字 -> Agent 类 ----------

AGENT_REGISTRY: dict[str, type["BaseAgent"]] = {}


def register_agent(name: str):
    """装饰器：把 Agent 类注册到全局注册表，供流程配置按名字引用。"""
    def decorator(cls: type["BaseAgent"]):
        cls.agent_name = name
        AGENT_REGISTRY[name] = cls
        return cls
    return decorator


def create_agent(name: str, **kwargs) -> "BaseAgent":
    """按名字实例化 Agent（供引擎调用）。"""
    if name not in AGENT_REGISTRY:
        raise KeyError(f"未注册的 Agent：{name}，已注册：{list(AGENT_REGISTRY)}")
    return AGENT_REGISTRY[name](**kwargs)


def list_agents() -> dict[str, str]:
    """列出所有已注册 Agent 及其描述（供 CLI 展示）。"""
    return {
        name: getattr(cls, "description", "")
        for name, cls in AGENT_REGISTRY.items()
    }


class BaseAgent(ABC):
    """所有 Workflow 节点的统一接口。"""

    agent_name: str = "base"
    description: str = ""

    def __init__(self, name: str | None = None):
        if name:
            self.agent_name = name

    @abstractmethod
    def run(self, state: WorkflowState) -> AgentResult:
        """执行本节点逻辑：从 state 读取输入，把产物写回 state，返回结果。"""

    # ---------- 通用工具方法 ----------

    @staticmethod
    def extract_code_block(text: str) -> str:
        """从 LLM 回答中提取最后一个 ```python 代码块内容。"""
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
        if blocks:
            return blocks[-1].strip()
        return text.strip()

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        """尽力从模型输出中解析 JSON（容忍多余的解释文字）。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}
