# 代码审查 Workflow（多 Agent 协作）

Week2 项目：搭建一个由 **3 个 Agent 协作**的代码审查 Workflow，演示 Workflow 编排、Agent 间通信与状态管理等核心概念。

流程：**需求 → 编码 → 审查 → (修复 → 复审) → 验证**

## 一、核心特性

| 能力 | 实现方式 |
|---|---|
| **多 Agent 协作** | 编码 Agent → 审查 Agent → 修复 Agent（3 个独立 Agent） |
| **Agent 间通信** | 消息传递（`state.messages`）+ 共享产物（`state.artifacts`）黑板模式 |
| **顺序流程控制** | 声明式流程配置，引擎顺序执行 |
| **条件分支**（加分） | 审查无阻塞问题时，修复步骤自动跳过 |
| **循环**（加分） | 「审查 → 修复」循环迭代，最多 2 轮，可配置上限 |
| **执行日志与状态追踪**（加分） | 控制台 + `logs/*.log` 双写，含步骤耗时、状态轨迹 |
| **错误处理与恢复**（加分） | LLM 指数退避重试；步骤级 `on_error=abort/skip`；循环上限保护 |
| **可扩展性** | Agent 注册表 + 声明式流程，新增 Agent 无需改引擎 |
| **工具复用** | 复用 Week1 的 `execute_python` 工具做真实语法检查与冒烟运行 |

## 二、快速开始

### 环境要求

- Python 3.10+
- 一个 LLM API Key（默认 DeepSeek，注册：https://platform.deepseek.com ）

### 安装与配置

```bash
cd agent-workflow
pip install -r requirements.txt          # 国内可用 -i https://pypi.tuna.tsinghua.edu.cn/simple

copy .env.example .env                   # Windows，然后编辑 .env 填入 LLM_API_KEY
```

### 运行

```bash
python main.py --demo                        # 内置示例需求，跑完整流程（推荐首次运行）
python main.py -r "实现一个 LRU 缓存类"       # 自定义需求，走完整流程
python main.py -f samples/buggy_code.py      # 审查并修复已有代码文件（跳过编码 Agent）
python main.py --list                        # 查看已注册的 Agent 节点
python test_workflow.py                      # 运行全部测试（22 项）
python test_workflow.py --offline            # 只跑引擎离线单测，不消耗 API
```

### 运行效果示例

```
[STEP] =========== 步骤 1/4：① 编码 ===========
[AGENT] <coder> 开始执行：① 编码
[ OK ] ① 编码 完成（3.9s）| 设计思路：用纯函数实现三个统计功能...
[STEP] =========== 步骤 1/2：②③ 审查-修复循环/轮1/代码审查 ===========
[ OK ] ②③ 审查-修复循环/轮1/代码审查 完成（2.5s）| 第1轮：评分 90，问题 4 个（阻塞 2 个）
[ OK ] ②③ 审查-修复循环/轮1/代码修复 完成（7.9s）| 第1轮修复：处理 2 个问题，输出 151 行代码
[ OK ] ②③ 审查-修复循环/轮2/代码审查 完成（2.6s）| 第2轮：评分 92，问题 3 个（阻塞 0 个）
[SKIP] ②③ 审查-修复循环/轮2/代码修复：条件不满足，跳过      <-- 条件分支
[ OK ] ④ 最终验证 完成（0.1s）| 语法检查通过；运行成功
[ OK ] ⑤ 结果落盘 完成（0.0s）| 产物已保存到 output/20261015-160634/（5 个文件）
```

## 三、项目结构

```
agent-workflow/
├── main.py                    # 命令行入口
├── agents/                    # Agent 节点（每个 Agent 一个文件）
│   ├── base.py                # 抽象基类 + 注册机制（可扩展性核心）
│   ├── coder.py               # 编码 Agent
│   ├── reviewer.py            # 审查 Agent（结构化 JSON 报告 + 工具调用）
│   └── fixer.py               # 修复 Agent
├── workflow/                  # 编排层
│   ├── state.py               # 共享状态（Agent 间通信 + 状态追踪）
│   ├── engine.py              # 编排引擎（顺序/分支/循环/错误恢复）
│   ├── pipeline.py            # 流程定义（声明式组装）
│   └── logger.py              # 执行日志
├── core/                      # 基础层（复用自 Week1 项目）
│   ├── llm.py                 # LLM 调用（重试 + JSON 模式）
│   └── tools.py               # 工具集（读文件/搜索/执行代码）
├── samples/buggy_code.py      # 演示用「问题代码」
├── test_workflow.py           # 测试脚本（22 项）
├── logs/                      # 运行日志（自动生成）
├── output/                    # 流程产物（自动生成）
├── requirements.txt
├── .env.example
└── Design.md                  # 设计文档（含架构图与流程图）
```

## 四、新增一个 Agent（可扩展性演示）

只需 3 步，无需修改引擎：

```python
# 1) 新建 agents/doc_writer.py
from agents.base import BaseAgent, register_agent, AgentResult

@register_agent("doc_writer")                      # 2) 注册
class DocWriterAgent(BaseAgent):
    description = "文档 Agent：把代码转成说明文档"
    def run(self, state):
        code = state.get("current_code")            # 从共享状态读取输入
        ...                                        # 调用 LLM 生成文档
        state.set("document", doc, by=self.agent_name)   # 写回共享状态
        return AgentResult(self.agent_name, doc)

# 3) 在 workflow/pipeline.py 的流程中加一行
#    AgentStep(name="⑥ 生成文档", agent="doc_writer")
```

## 五、输出产物说明

每次运行在 `output/<任务ID>/` 下生成：

| 文件 | 说明 |
|---|---|
| `01_generated_code.py` | 编码 Agent 的初始代码 |
| `02_review_report.json` | 审查报告（评分、问题列表） |
| `03_fixed_code_N.py` | 第 N 轮修复后的代码 |
| `04_final_code.py` | 最终代码 |
| `run_report.json` | 状态报告（步骤轨迹、产物清单、耗时） |

详细设计见 [Design.md](Design.md)。
