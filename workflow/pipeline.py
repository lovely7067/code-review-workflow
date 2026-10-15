"""流程定义：以声明式方式组装 Workflow。

流程即「步骤对象列表」，调整流程 / 新增 Agent 节点只需改这里，无需修改引擎。
"""
import json
import os

from core.tools import execute_python
from workflow.engine import (
    ActionStep,
    AgentStep,
    LoopStep,
    has_blocking_issues,
)
from workflow.state import WorkflowState

MAX_FIX_ROUNDS = 2   # 最多修复轮数（循环上限）


# ---------- 循环条件 ----------

def review_fix_continue(state: WorkflowState) -> bool:
    """审查-修复循环是否继续：首次必审；之后仅当仍有阻塞问题且未超轮数上限。"""
    if state.get("review_round", 0) == 0:
        return True
    if state.get("fix_round", 0) >= MAX_FIX_ROUNDS:
        return False
    return has_blocking_issues(state)


# ---------- 非 Agent 步骤（Action） ----------

def load_code_from_file(path: str):
    """生成一个 Action：把指定文件读入共享状态（用于审查已有代码）。"""
    def action(state: WorkflowState) -> str:
        if not os.path.exists(path):
            raise FileNotFoundError(f"文件不存在：{path}")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        state.set("input_code", code, by="engine")
        state.set("current_code", code, by="engine")
        state.set("code_origin", "existing_file", by="engine")
        return f"已加载 {path}（{len(code.splitlines())} 行）"
    return action


def verify_final_code(state: WorkflowState) -> str:
    """最终验证：对最终代码做语法检查 + 实际运行（复用 Week1 工具）。"""
    code = state.get("current_code") or ""
    if not code:
        return "无代码可验证"

    try:
        compile(code, "<final>", "exec")
        syntax_ok, syntax_msg = True, "语法检查通过"
    except SyntaxError as e:
        syntax_ok, syntax_msg = False, f"语法错误：第 {e.lineno} 行 {e.msg}"

    run_output = execute_python(code) if syntax_ok else "（语法未通过，跳过运行）"
    run_ok = syntax_ok and "[exit code] 0" in run_output

    verification = {
        "syntax_ok": syntax_ok,
        "run_ok": run_ok,
        "detail": f"{syntax_msg}；运行{'成功' if run_ok else '未通过'}",
        "output": run_output[:1500],
    }
    state.set("verification", verification, by="engine")
    state.post_message("engine", "state", f"最终验证：{verification['detail']}")
    return verification["detail"]


def save_artifacts(state: WorkflowState) -> str:
    """把所有中间产物与状态报告落盘到 output/<task_id>/。"""
    out_dir = os.path.join("output", state.task_id)
    os.makedirs(out_dir, exist_ok=True)

    written = []
    if state.has("generated_code"):
        _write(os.path.join(out_dir, "01_generated_code.py"), state.get("generated_code"))
        written.append("01_generated_code.py")
    if state.has("latest_review"):
        _write(os.path.join(out_dir, "02_review_report.json"),
               json.dumps(state.get("latest_review"), ensure_ascii=False, indent=2))
        written.append("02_review_report.json")
    for key in sorted(k for k in state.artifacts if k.startswith("fixed_code_r")):
        name = f"03_fixed_code_{key.split('_r')[-1]}.py"
        _write(os.path.join(out_dir, name), state.get(key))
        written.append(name)
    if state.has("current_code"):
        _write(os.path.join(out_dir, "04_final_code.py"), state.get("current_code"))
        written.append("04_final_code.py")

    state.save_report(os.path.join(out_dir, "run_report.json"))
    written.append("run_report.json")

    state.set("output_dir", out_dir, by="engine")
    return f"产物已保存到 {out_dir}/（{len(written)} 个文件）"


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------- 流程组装 ----------

def build_review_loop() -> LoopStep:
    """「审查 -> 修复」循环：修复步骤带条件，无阻塞问题时自动跳过。"""
    return LoopStep(
        name="②③ 审查-修复循环",
        steps=[
            AgentStep(name="代码审查", agent="reviewer"),
            AgentStep(name="代码修复", agent="fixer", condition=has_blocking_issues, on_error="skip"),
        ],
        while_condition=review_fix_continue,
        max_iterations=MAX_FIX_ROUNDS,
    )


def build_full_pipeline() -> list:
    """完整流程：需求 -> 编码 -> 审查 -> (修复 -> 复审) -> 验证 -> 落盘。"""
    return [
        AgentStep(name="① 编码", agent="coder"),
        build_review_loop(),
        ActionStep(name="④ 最终验证", action=verify_final_code, on_error="skip"),
        ActionStep(name="⑤ 结果落盘", action=save_artifacts, on_error="skip"),
    ]


def build_review_pipeline(code_path: str) -> list:
    """审查已有代码的流程（跳过编码 Agent，展示流程可配置）。"""
    return [
        ActionStep(name="① 加载代码文件", action=load_code_from_file(code_path)),
        build_review_loop(),
        ActionStep(name="④ 最终验证", action=verify_final_code, on_error="skip"),
        ActionStep(name="⑤ 结果落盘", action=save_artifacts, on_error="skip"),
    ]
