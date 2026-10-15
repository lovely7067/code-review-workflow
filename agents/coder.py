"""编码 Agent（Coding Agent）：根据需求描述生成初始代码。

Workflow 中的第一个节点：需求 -> 代码
"""
from agents.base import AgentResult, BaseAgent, register_agent
from core import llm
from workflow.state import WorkflowState

SYSTEM_PROMPT = """你是一位资深 Python 工程师（编码 Agent）。

职责：根据需求描述，产出高质量、可直接运行的 Python 代码。

要求：
1. 代码必须完整可运行，包含必要的 import，不依赖未安装的第三方库
2. 使用类型注解，函数写简洁的中文 docstring
3. 代码里不要使用 input() 等交互式输入，保证可被自动执行验证
4. 在文件末尾用 `if __name__ == "__main__":` 写一段自测示例

输出格式：
先写 2-4 句话说明设计思路与关键实现，然后给出一个完整的 ```python 代码块。
"""


@register_agent("coder")
class CodingAgent(BaseAgent):
    agent_name = "coder"
    description = "编码 Agent：根据需求描述生成 Python 代码"

    def run(self, state: WorkflowState) -> AgentResult:
        state.post_message(self.agent_name, "coder", f"收到需求：{state.requirement[:60]}...")

        user_prompt = f"""需求描述：
{state.requirement}

请输出满足上述需求的完整 Python 代码。"""

        answer = llm.ask(SYSTEM_PROMPT, user_prompt)
        code = self.extract_code_block(answer)

        # 把产物写入共享状态（供后续 Agent 读取）
        state.set("generated_code", code, by=self.agent_name)
        state.set("current_code", code, by=self.agent_name)
        state.set("code_origin", "generated", by=self.agent_name)
        state.post_message(
            self.agent_name, "reviewer",
            "初始代码已生成，请审查",
            meta={"code_length": len(code)},
        )
        return AgentResult(self.agent_name, answer, {"code_lines": len(code.splitlines())})
