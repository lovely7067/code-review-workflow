"""测试脚本：引擎离线单测（不需要 API）+ 端到端真实测试。

运行：
    python test_workflow.py --offline   # 只跑离线单测，验证编排引擎逻辑
    python test_workflow.py             # 离线单测 + 真实 LLM 端到端流程
"""
import argparse
import os
import sys

import agents  # noqa: F401  导入即注册
from agents.base import AGENT_REGISTRY, create_agent
from workflow.engine import ActionStep, AgentStep, LoopStep, WorkflowEngine
from workflow.logger import WorkflowLogger
from workflow.pipeline import build_review_pipeline
from workflow.state import WorkflowState

results: list[tuple[str, bool]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({extra})" if extra else ""))


def quiet_logger() -> WorkflowLogger:
    """减少测试噪音：日志写入临时目录。"""
    return WorkflowLogger(log_dir="logs/test", task_id="test")


# ============ 一、离线单测：编排引擎能力 ============

def test_registry() -> None:
    print("\n--- 测试1：Agent 注册机制（可扩展性）---")
    check("3 个 Agent 已注册", len(AGENT_REGISTRY) >= 3, f"实际 {list(AGENT_REGISTRY)}")
    check("可按名字实例化", create_agent("coder").agent_name == "coder")
    try:
        create_agent("不存在的Agent")
        check("未注册 Agent 会报错", False)
    except KeyError:
        check("未注册 Agent 会报错", True)


def test_state_sharing() -> None:
    print("\n--- 测试2：状态共享与消息传递 ---")
    state = WorkflowState("t", "需求")
    state.set("a", "1234", by="coder")
    check("产物读写正常", state.get("a") == "1234" and state.has("a"))
    state.post_message("coder", "reviewer", "请审查")
    check("Agent 间消息传递", state.get_messages("reviewer")[0].sender == "coder")
    check("写入产物自动广播", any(m.receiver == "state" for m in state.messages))


def test_conditional_skip() -> None:
    print("\n--- 测试3：条件分支（条件不满足则跳过）---")
    state = WorkflowState("t", "需求")
    engine = WorkflowEngine([
        ActionStep(name="总是执行", action=lambda s: "done"),
        ActionStep(name="被跳过的步骤", action=lambda s: "should not run", condition=lambda s: False),
    ], logger=quiet_logger())
    engine.run(state)
    skipped = [h for h in state.history if h["status"] == "skipped"]
    check("流程正常完成", state.status == "completed")
    check("条件不满足的步骤被跳过", len(skipped) == 1 and skipped[0]["step"] == "被跳过的步骤")


def test_error_recovery() -> None:
    print("\n--- 测试4：错误处理与恢复 ---")
    def boom(state):
        raise RuntimeError("模拟工具故障")

    # 4.1 on_error="skip"：失败后继续后续步骤
    state = WorkflowState("t", "需求")
    engine = WorkflowEngine([
        ActionStep(name="会失败的步骤", action=boom, on_error="skip"),
        ActionStep(name="后续步骤", action=lambda s: "ok"),
    ], logger=quiet_logger())
    engine.run(state)
    check("失败被跳过且流程继续（on_error=skip）",
          state.status == "completed" and any(h["status"] == "failed" for h in state.history))

    # 4.2 on_error="abort"：失败后终止（状态标记 failed）
    state2 = WorkflowState("t", "需求")
    engine2 = WorkflowEngine([
        ActionStep(name="致命失败", action=boom, on_error="abort"),
        ActionStep(name="不会执行", action=lambda s: "ok"),
    ], logger=quiet_logger())
    engine2.run(state2)
    check("失败终止流程并标记 failed（on_error=abort）",
          state2.status == "failed" and len(state2.history) == 1)


def test_loop() -> None:
    print("\n--- 测试5：循环流程控制 ---")
    state = WorkflowState("t", "需求")
    loop = LoopStep(
        name="重试循环",
        steps=[ActionStep(name="迭代体", action=lambda s: s.set("n", s.get("n", 0) + 1, by="engine"))],
        while_condition=lambda s: s.get("n", 0) < 3,
        max_iterations=5,
    )
    engine = WorkflowEngine([loop], logger=quiet_logger())
    engine.run(state)
    check("循环按条件执行 3 轮", state.get("n") == 3, f"实际 {state.get('n')}")

    # 循环上限保护：条件恒为真但不超过 max_iterations
    state2 = WorkflowState("t", "需求")
    loop2 = LoopStep(
        name="死循环保护",
        steps=[ActionStep(name="迭代体", action=lambda s: s.set("m", s.get("m", 0) + 1, by="engine"))],
        while_condition=lambda s: True,
        max_iterations=2,
    )
    WorkflowEngine([loop2], logger=quiet_logger()).run(state2)
    check("循环上限保护生效（最多 2 轮）", state2.get("m") == 2, f"实际 {state2.get('m')}")


def run_offline_tests() -> None:
    print("=" * 62)
    print("第一部分：编排引擎离线单测（不消耗 API）")
    print("=" * 62)
    test_registry()
    test_state_sharing()
    test_conditional_skip()
    test_error_recovery()
    test_loop()


# ============ 二、端到端真实测试：完整 Workflow ============

def run_end_to_end() -> None:
    print("\n" + "=" * 62)
    print("第二部分：端到端 Workflow 测试（真实调用 LLM）")
    print("=" * 62)

    sample = os.path.join("samples", "buggy_code.py")
    state = WorkflowState(task_name="测试：审查示例代码", requirement=f"审查并修复 {sample}")
    steps = build_review_pipeline(sample)
    logger = WorkflowLogger(task_id=f"test-{state.task_id}")
    engine = WorkflowEngine(steps, logger=logger)
    try:
        engine.run(state)
    finally:
        logger.close()

    check("Workflow 正常完成", state.status == "completed", f"状态 {state.status}")
    check("审查 Agent 产出报告", state.has("latest_review"))
    issues = (state.get("latest_review") or {}).get("issues", [])
    check("审查发现了问题（示例代码含多处 bug）", len(issues) > 0, f"{len(issues)} 个问题")
    check("触发了修复（存在阻塞问题）", state.has("fixed_code_r1"))
    check("修复后的代码单独保存", state.has("fixed_code_r1") and state.get("fixed_code_r1") != state.get("generated_code"))
    check("执行了最终验证", state.has("verification"))
    verify = state.get("verification") or {}
    check("修复后代码可运行", bool(verify.get("run_ok")), verify.get("detail", ""))
    check("产物已落盘", state.has("output_dir") and os.path.isdir(state.get("output_dir", "")))
    check("有完整步骤轨迹与消息记录",
          len(state.history) >= 3 and len([m for m in state.messages if m.receiver == "state"]) > 0)
    check("日志文件已生成", os.path.exists(logger.path), logger.path)


# ============ 入口 ============

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="只运行离线单测")
    args = parser.parse_args()

    run_offline_tests()
    if not args.offline:
        run_end_to_end()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("\n" + "=" * 62)
    print(f"测试结果：{passed}/{total} 通过")
    print("=" * 62)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
