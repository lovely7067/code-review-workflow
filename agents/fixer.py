"""修复 Agent（Fix Agent）：根据审查报告修复代码，输出修复后的完整代码。

Workflow 中的第三个节点：审查报告 -> 修复后代码
"""
import json

from agents.base import AgentResult, BaseAgent, register_agent
from core import llm
from workflow.state import WorkflowState

SYSTEM_PROMPT = """你是一位严谨的代码修复工程师（修复 Agent）。

职责：根据审查报告指出的问题，修复代码并输出完整、可直接运行的修复版本。

要求：
1. 逐条修复审查报告中 severity 为 high / medium 的问题
2. 保留原代码中正确的功能与结构，不要重写无关部分
3. 输出完整的修复后代码（不是片段），包含所有 import
4. 代码中不要使用 input() 等交互式输入

输出格式：
先逐条说明每个问题是如何修复的（编号列表），然后给出一个完整的 ```python 代码块。
"""


@register_agent("fixer")
class FixAgent(BaseAgent):
    agent_name = "fixer"
    description = "修复 Agent：按审查报告逐条修复代码"

    def run(self, state: WorkflowState) -> AgentResult:
        code = state.get("current_code")
        report = state.get("latest_review")
        if not code or not report:
            raise ValueError("修复 Agent 缺少输入：需要 current_code 与 latest_review")

        fix_round = state.get("fix_round", 0) + 1
        issues = report.get("issues", [])
        blocking = [i for i in issues if i.get("severity") in ("high", "medium")]

        state.post_message(
            self.agent_name, "fixer",
            f"开始第 {fix_round} 轮修复，待修复问题 {len(blocking)} 个",
        )

        user_prompt = f"""【审查报告（第 {report.get('round')} 轮）】
{json.dumps(report, ensure_ascii=False, indent=2)}

【待修复代码】
```python
{code}
```

请逐条修复 severity 为 high 与 medium 的问题，输出完整修复后的代码。"""

        answer = llm.ask(SYSTEM_PROMPT, user_prompt)
        fixed_code = self.extract_code_block(answer)

        # 更新共享状态：current_code 指向修复后的代码，供下一轮审查使用
        state.set("fix_round", fix_round, by=self.agent_name)
        state.set(f"fixed_code_r{fix_round}", fixed_code, by=self.agent_name)
        state.set("current_code", fixed_code, by=self.agent_name)
        state.set("code_origin", "fixed", by=self.agent_name)
        state.post_message(
            self.agent_name, "reviewer",
            f"第 {fix_round} 轮修复完成（{len(fixed_code.splitlines())} 行），请复审",
        )

        detail = f"第{fix_round}轮修复：处理 {len(blocking)} 个问题，输出 {len(fixed_code.splitlines())} 行代码"
        return AgentResult(self.agent_name, answer, {
            "fix_round": fix_round,
            "fixed_issues": len(blocking),
            "code_lines": len(fixed_code.splitlines()),
            "detail": detail,
        })
