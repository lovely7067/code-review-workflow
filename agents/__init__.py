"""Agent 包：导入即完成注册（供注册表按名字查找）。"""
from agents.coder import CodingAgent
from agents.fixer import FixAgent
from agents.reviewer import ReviewAgent

__all__ = ["CodingAgent", "ReviewAgent", "FixAgent"]
