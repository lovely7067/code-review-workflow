"""审查 Agent（Review Agent）：静态检查 + LLM 深度审查，输出结构化审查报告。

Workflow 中的第二个节点：代码 -> 审查报告
特色：复用 Week1 项目的 execute_python 工具做真实语法检查与冒烟运行。
"""
from agents.base import AgentResult, BaseAgent, register_agent
from core import llm
from core.tools import execute_python
from workflow.state import WorkflowState

SYSTEM_PROMPT = """你是一位严格的代码审查专家（审查 Agent）。

职责：审查给定的 Python 代码，找出真实存在的问题，并输出结构化审查报告。

审查重点（按严重程度）：
- high：会导致程序崩溃或结果错误（语法/逻辑错误、越界、除零、可变默认参数、资源未关闭）
- medium：健壮性/可维护性问题（缺少异常处理、参数校验缺失、命名不规范、重复代码）
- low：风格建议（注释、类型注解、可读性优化）

输出要求：只输出一个 JSON 对象（不要任何额外文字），格式：
{
  "score": 0-100 的整数（代码质量评分）,
  "summary": "一句话总体评价",
  "issues": [
    {"severity": "high|medium|low", "line": 行号(不确定填0), "problem": "问题描述", "suggestion": "修改建议"}
  ]
}
若代码质量良好，issues 可以是空数组。
"""


@register_agent("reviewer")
class ReviewAgent(BaseAgent):
    agent_name = "reviewer"
    description = "审查 Agent：静态检查 + LLM 审查，输出结构化问题列表"

    def __init__(self, name: str | None = None, run_smoke_test: bool = True):
        super().__init__(name)
        self.run_smoke_test = run_smoke_test

    # ---------- 工具使用：真实的静态检查（复用 Week1 工具） ----------

    def _static_check(self, code: str) -> tuple[bool, str]:
        """语法检查（compile）+ 可选冒烟运行（execute_python 工具）。"""
        try:
            compile(code, "<candidate>", "exec")
        except SyntaxError as e:
            return False, f"语法错误：第 {e.lineno} 行 {e.msg}"

        if not self.run_smoke_test:
            return True, "语法检查通过（未执行冒烟测试）"

        result = execute_python(code)
        if "[exit code] 0" in result:
            return True, f"语法检查通过；冒烟执行成功\n{result[:600]}"
        return False, f"语法检查通过，但执行报错：\n{result[:600]}"

    def run(self, state: WorkflowState) -> AgentResult:
        code = state.get("current_code")
        if not code:
            raise ValueError("审查 Agent 未在 state 中找到待审代码（current_code）")

        round_no = state.get("review_round", 0) + 1
        origin = state.get("code_origin", "unknown")
        state.post_message(
            self.agent_name, "reviewer",
            f"开始第 {round_no} 轮审查，代码来源：{origin}",
        )

        # 1) 先做机器可验证的静态检查（工具调用）
        passed, check_detail = self._static_check(code)
        state.post_message(self.agent_name, "state", f"静态检查结果：{check_detail[:120]}")

        # 2) LLM 深度审查（结构化 JSON 输出）
        user_prompt = f"""请审查以下 Python 代码（这是第 {round_no} 轮审查，代码来源：{origin}）。

【自动静态检查结果】
{check_detail}

【待审查代码】
```python
{code}
```
"""
        raw = llm.ask(SYSTEM_PROMPT, user_prompt, json_mode=True)
        report = self.parse_json(raw)

        if not report:
            # 解析失败时降级为保守报告，保证流程不中断
            report = {
                "score": 0,
                "summary": "审查报告解析失败，已降级处理",
                "issues": [{
                    "severity": "medium", "line": 0,
                    "problem": "模型未返回合法 JSON",
                    "suggestion": "请人工复核代码可运行性",
                }],
            }

        report["round"] = round_no
        report["static_check_passed"] = passed
        report["code_origin"] = origin

        state.set("review_round", round_no, by=self.agent_name)
        state.set(f"review_report_r{round_no}", report, by=self.agent_name)
        state.set("latest_review", report, by=self.agent_name)

        blocking = [i for i in report.get("issues", []) if i.get("severity") in ("high", "medium")]
        state.post_message(
            self.agent_name, "fixer" if blocking else "state",
            f"发现 {len(report.get('issues', []))} 个问题（其中 {len(blocking)} 个需修复），评分 {report.get('score')}",
            meta={"blocking": len(blocking), "round": round_no},
        )

        detail = (f"第{round_no}轮：评分 {report.get('score')}，问题 {len(report.get('issues', []))} 个"
                  f"（阻塞 {len(blocking)} 个）")
        return AgentResult(self.agent_name, raw, {
            "round": round_no,
            "score": report.get("score"),
            "issues": len(report.get("issues", [])),
            "blocking": len(blocking),
            "static_ok": passed,
            "detail": detail,
        })
