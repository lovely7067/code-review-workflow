"""命令行入口：运行多 Agent 协作的代码审查 Workflow。

用法：
    python main.py -r "实现一个学生成绩统计模块，支持平均分/最高分/不及格名单"
    python main.py -f samples/buggy_code.py     # 审查并修复已有代码文件
    python main.py --demo                       # 使用内置示例需求跑完整流程
    python main.py --list                       # 查看已注册的 Agent
"""
import argparse
import sys

import agents  # noqa: F401  导入即注册全部 Agent
from agents.base import list_agents
from workflow.engine import WorkflowEngine
from workflow.logger import WorkflowLogger
from workflow.pipeline import build_full_pipeline, build_review_pipeline
from workflow.state import WorkflowState

DEMO_REQUIREMENT = (
    "实现一个学生成绩统计模块，提供三个函数："
    "average(scores) 计算平均分；top_student(student_scores) 找出分数最高的学生；"
    "pass_rate(scores) 计算及格率。要求对空列表等边界情况做处理，"
    "并在文件末尾写自测示例。"
)


def print_report(state: WorkflowState) -> None:
    """打印 Workflow 最终报告。"""
    print("\n" + "=" * 62)
    print("Workflow 执行报告")
    print("=" * 62)
    print(f"任务名称 : {state.task_name}")
    print(f"任务 ID  : {state.task_id}")
    print(f"最终状态 : {state.status}")
    print(f"耗时     : {round(state.summary()['elapsed'], 1)} 秒")

    print("\n-- 步骤执行轨迹 " + "-" * 45)
    for item in state.history:
        mark = {"ok": "[OK]  ", "skipped": "[SKIP]", "failed": "[FAIL]"}.get(item["status"], "      ")
        print(f"{mark} {item['time']}  {item['step']:<28} {item['detail'][:60]}")

    print("\n-- Agent 间消息流 " + "-" * 43)
    for m in state.messages:
        if m.receiver == "state":
            continue
        print(f"  {m.sender:>8} -> {m.receiver:<8} | {m.content[:70]}")

    review = state.get("latest_review")
    if review:
        print("\n-- 审查结果 " + "-" * 49)
        print(f"  质量评分 : {review.get('score')}")
        print(f"  总体评价 : {review.get('summary')}")
        print(f"  问题列表 : 共 {len(review.get('issues', []))} 个")
        for issue in review.get("issues", []):
            print(f"    - [{issue.get('severity'):<6}] 第{issue.get('line', 0):>3}行 "
                  f"{issue.get('problem', '')[:50]}")

    verify = state.get("verification")
    if verify:
        print("\n-- 最终代码验证 " + "-" * 45)
        print(f"  {verify.get('detail')}")

    if state.has("output_dir"):
        print(f"\n产物目录 : {state.get('output_dir')}/")
    print("=" * 62)


def main() -> None:
    parser = argparse.ArgumentParser(description="代码审查 Workflow（多 Agent 协作）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-r", "--requirement", help="需求描述（走完整流程：编码→审查→修复）")
    group.add_argument("-f", "--file", help="审查并修复已有的代码文件")
    group.add_argument("--demo", action="store_true", help="使用内置示例需求运行完整流程")
    group.add_argument("--list", action="store_true", help="列出已注册的 Agent 节点")
    args = parser.parse_args()

    if args.list:
        print("已注册的 Agent 节点：")
        for name, desc in list_agents().items():
            print(f"  - {name:<10} {desc}")
        print("\n（新增 Agent 后会自动出现在这里，无需修改引擎）")
        return

    # 组装流程与初始状态
    if args.file:
        state = WorkflowState(
            task_name=f"审查已有代码：{args.file}",
            requirement=f"审查并修复代码文件 {args.file} 中的问题",
        )
        steps = build_review_pipeline(args.file)
    else:
        requirement = args.requirement or DEMO_REQUIREMENT
        state = WorkflowState(task_name="代码审查 Workflow", requirement=requirement)
        steps = build_full_pipeline()

    print("=" * 62)
    print("代码审查 Workflow（编码 Agent -> 审查 Agent -> 修复 Agent）")
    print("=" * 62)
    print(f"需求/任务：{state.requirement[:70]}")
    print("-" * 62)

    logger = WorkflowLogger(task_id=state.task_id)
    engine = WorkflowEngine(steps, logger=logger)
    try:
        engine.run(state)
    finally:
        logger.close()

    print_report(state)
    print(f"\n完整执行日志：{logger.path}")
    sys.exit(0 if state.status == "completed" else 1)


if __name__ == "__main__":
    main()
