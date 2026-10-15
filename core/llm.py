"""LLM 调用层（复用自 Week1 项目，新增 JSON 模式支持）。

所有 Agent 通过本模块统一访问 LLM，具备客户端复用与指数退避重试能力。
"""
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError(
                "未检测到 LLM_API_KEY：请复制 .env.example 为 .env 并填入你的 API Key"
            )
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def chat(messages: list, tools: list | None = None, json_mode: bool = False):
    """调用 LLM，失败时指数退避重试。

    :param tools: Function Calling 工具描述（可选）
    :param json_mode: True 时要求模型返回严格 JSON（用于结构化审查报告）
    """
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            kwargs = {"model": MODEL, "messages": messages}
            if tools:
                kwargs["tools"] = tools
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = get_client().chat.completions.create(**kwargs)
            return resp.choices[0].message
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BASE_DELAY ** attempt
                print(f"  [LLM重试 {attempt}/{MAX_RETRIES}] {e}，{wait} 秒后重试...")
                time.sleep(wait)
    raise RuntimeError(f"LLM 调用连续 {MAX_RETRIES} 次失败：{last_err}")


def ask(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """单轮问答的便捷封装（Agent 最常用的调用方式）。"""
    message = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=json_mode,
    )
    return message.content or ""
