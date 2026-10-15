"""Workflow 编排引擎。

核心能力：
- 顺序执行（必须实现）
- 条件分支：步骤级 condition，为假则跳过（推荐项）
- 循环：LoopStep 支持「审查 -> 修复」反复迭代（推荐项）
- 执行日志与状态追踪（推荐项）
- 错误处理与恢复：步骤失败可 abort / skip / 重试（推荐项）

可扩展性：流程以「步骤对象列表」声明，新增节点或调整流程无需改动引擎。
"""
import time
from dataclasses import dataclass, field
from typing import Callable

from agents.base import create_agent
from workflow.logger import WorkflowLogger
from workflow.state import WorkflowState


# ---------- 步骤定义 ----------

@dataclass
class AgentStep:
    """调用一个 Agent 节点。"""
    name: str
    agent: str
    condition: Callable[[WorkflowState], bool] | None = None
    on_error: str = "abort"          # abort | skip
    kwargs: dict = field(default_factory=dict)


@dataclass
class ActionStep:
    """执行一段普通 Python 代码（非 Agent，如最终验证、结果落盘）。"""
    name: str
    action: Callable[[WorkflowState], str]
    condition: Callable[[WorkflowState], bool] | None = None
    on_error: str = "abort"


@dataclass
class LoopStep:
    """循环执行一组步骤，直到条件不再满足或达到最大迭代次数。

    典型用法：「审查 -> 修复」反复迭代，直到没有 blocking 问题。
    """
    name: str
    steps: list
    while_condition: Callable[[WorkflowState], bool]
    max_iterations: int = 3


# ---------- 引擎 ----------

class WorkflowEngine:
    def __init__(self, steps: list, logger: WorkflowLogger | None = None):
        self.steps = steps
        self.logger = logger or WorkflowLogger()
        self._agent_cache: dict[str, object] = {}   # Agent 实例复用

    # ---------- 对外接口 ----------

    def run(self, state: WorkflowState) -> WorkflowState:
        self.logger.info(f"Workflow 启动 | 任务：{state.task_name} | ID：{state.task_id}")
        state.status = "running"
        try:
            self._execute_steps(self.steps, state, prefix="")
            if state.status == "running":
                state.status = "completed"
        except Exception as e:
            state.status = "failed"
            self.logger.error(f"Workflow 异常终止：{type(e).__name__}: {e}")
        finally:
            self.logger.info(
                f"Workflow 结束 | 状态：{state.status} | 步骤记录 {len(state.history)} 条 | "
                f"消息 {len(state.messages)} 条"
            )
        return state

    # ---------- 内部执行 ----------

    def _execute_steps(self, steps: list, state: WorkflowState, prefix: str) -> None:
        total = len(steps)
        for index, step in enumerate(steps, 1):
            if state.status == "failed":
                return

            label = f"{prefix}{step.name}"
            # 条件分支
            if getattr(step, "condition", None) and not step.condition(state):
                self.logger.skip(f"{label}：条件不满足，跳过")
                state.add_history(label, "skipped", "条件不满足")
                continue

            if isinstance(step, LoopStep):
                self._run_loop(step, state, prefix)
                continue

            self.logger.step(index, total, label)
            start = time.time()
            try:
                detail = self._run_single(step, state)
                duration = time.time() - start
                self.logger.ok(f"{label} 完成（{duration:.1f}s）| {detail}")
                state.add_history(label, "ok", detail, duration)
            except Exception as e:
                duration = time.time() - start
                if getattr(step, "on_error", "abort") == "skip":
                    self.logger.warn(f"{label} 失败，按配置跳过并继续：{type(e).__name__}: {e}")
                    state.add_history(label, "failed", f"{type(e).__name__}: {e}", duration)
                    continue
                self.logger.error(f"{label} 失败并终止流程：{type(e).__name__}: {e}")
                state.add_history(label, "failed", f"{type(e).__name__}: {e}", duration)
                state.status = "failed"
                return

    def _run_single(self, step, state: WorkflowState) -> str:
        if isinstance(step, AgentStep):
            agent = self._get_agent(step.agent, step.kwargs)
            self.logger.agent(step.agent, f"开始执行：{step.name}")
            result = agent.run(state)
            self.logger.agent(step.agent, f"输出摘要：{result.brief()}")
            return result.meta.get("detail") or result.brief()
        if isinstance(step, ActionStep):
            return step.action(state) or "完成"
        raise TypeError(f"未知步骤类型：{type(step)}")

    def _run_loop(self, loop: LoopStep, state: WorkflowState, prefix: str) -> None:
        label = f"{prefix}{loop.name}"
        self.logger.step(0, 0, f"{label}（最多 {loop.max_iterations} 轮）")
        iteration = 0
        start = time.time()
        while loop.while_condition(state) and iteration < loop.max_iterations:
            iteration += 1
            self.logger.info(f"--> {label} 第 {iteration} 轮迭代")
            before = len(state.history)
            self._execute_steps(loop.steps, state, prefix=f"{label}/轮{iteration}/")
            if state.status == "failed":
                return
            if len(state.history) == before:      # 本轮全部被跳过，避免空转
                self.logger.warn(f"{label}：本轮无步骤执行，提前结束循环")
                break
        if iteration == 0:
            self.logger.skip(f"{label}：起始条件不满足，未进入循环")
        duration = time.time() - start
        state.add_history(label, "ok", f"实际迭代 {iteration} 轮", duration)

    def _get_agent(self, name: str, kwargs: dict):
        """按名字创建并缓存 Agent 实例（Agent 之间不直接通信，只通过 state 交互）。"""
        if name not in self._agent_cache:
            self._agent_cache[name] = create_agent(name, **kwargs)
            self.logger.info(f"实例化 Agent：{name}（{type(self._agent_cache[name]).__name__}）")
        return self._agent_cache[name]


# ---------- 常用条件函数 ----------

def has_blocking_issues(state: WorkflowState) -> bool:
    """审查报告是否包含 high/medium 级别问题。"""
    report = state.get("latest_review") or {}
    issues = report.get("issues", []) or []
    return any(i.get("severity") in ("high", "medium") for i in issues)


def smoke_test_ok(state: WorkflowState) -> bool:
    """最近一次静态检查是否通过。"""
    report = state.get("latest_review") or {}
    return bool(report.get("static_check_passed"))
