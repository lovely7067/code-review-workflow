"""工具集：Agent 可调用的三种能力。

1. read_file      读取指定代码文件（含行号）
2. search_code    在目录中按正则搜索代码
3. execute_python 沙箱执行 Python 代码片段（用于验证代码行为）
"""
import os
import re
import subprocess
import sys
import tempfile

MAX_FILE_SIZE = 100 * 1024        # 单文件最大读取 100KB，防止撑爆上下文
MAX_SEARCH_FILES = 200            # 搜索时最多遍历的文件数
MAX_OUTPUT_CHARS = 4000           # 工具返回给模型的最大字符数
EXEC_TIMEOUT = 15                 # 代码执行超时（秒）

# ---------- OpenAI Function Calling 工具描述（供 LLM 了解如何调用） ----------

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定路径的文本/代码文件内容，返回带行号的源码。用于解释代码前获取源码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对或绝对路径均可"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在指定目录下按正则表达式搜索代码，返回匹配的文件与行。用于定位某个函数/类/关键字在哪里定义或使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "要搜索的目录，默认为当前目录"},
                    "pattern": {"type": "string", "description": "正则表达式，如 'def \\w+'"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "在沙箱中执行一段 Python 代码并返回 stdout/stderr。用于验证代码行为、测试小片段。不能访问网络，限时15秒。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 代码"}
                },
                "required": ["code"],
            },
        },
    },
]

# ---------- 工具实现 ----------

def read_file(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        return f"错误：文件不存在 -> {path}"
    if not os.path.isfile(path):
        return f"错误：不是文件 -> {path}"
    size = os.path.getsize(path)
    if size > MAX_FILE_SIZE:
        return f"错误：文件过大（{size} 字节，上限 {MAX_FILE_SIZE}）"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return f"错误：读取失败 -> {e}"

    numbered = "".join(f"{i:>5} | {line}" for i, line in enumerate(lines, 1))
    header = f"文件：{path}（共 {len(lines)} 行）\n"
    return (header + numbered)[:MAX_OUTPUT_CHARS]


def search_code(directory: str = ".", pattern: str = "") -> str:
    if not pattern:
        return "错误：pattern 不能为空"
    directory = os.path.abspath(os.path.expanduser(directory or "."))
    if not os.path.isdir(directory):
        return f"错误：目录不存在 -> {directory}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"错误：无效的正则表达式 -> {e}"

    SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
    results, scanned = [], 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if scanned >= MAX_SEARCH_FILES:
                results.append(f"（已达 {MAX_SEARCH_FILES} 个文件上限，结果截断）")
                break
            if not name.endswith((".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".md", ".txt")):
                continue
            scanned += 1
            fpath = os.path.join(root, name)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{fpath}:{lineno}: {line.rstrip()}")
            except OSError:
                continue
        if scanned >= MAX_SEARCH_FILES:
            break

    if not results:
        return f"在 {directory} 中未找到匹配 '{pattern}' 的内容"
    return "\n".join(results)[:MAX_OUTPUT_CHARS]


def execute_python(code: str) -> str:
    """将代码写入临时文件，用子进程隔离执行，限时 EXEC_TIMEOUT 秒。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        # 显式指定 UTF-8 编解码：Windows 默认 GBK，遇到中文输出会解码失败
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXEC_TIMEOUT,
            env=env,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        result = ""
        if out:
            result += f"[stdout]\n{out}\n"
        if err:
            result += f"[stderr]\n{err}\n"
        result += f"[exit code] {proc.returncode}"
        return result[:MAX_OUTPUT_CHARS]
    except subprocess.TimeoutExpired:
        return f"错误：代码执行超时（>{EXEC_TIMEOUT} 秒），已被强制终止"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------- 工具分发 ----------

def execute_tool(name: str, arguments: dict) -> str:
    """根据 LLM 选择的工具名执行对应实现，任何异常都转为文本结果返回给模型。"""
    try:
        if name == "read_file":
            return read_file(arguments["path"])
        if name == "search_code":
            return search_code(arguments.get("directory", "."), arguments.get("pattern", ""))
        if name == "execute_python":
            return execute_python(arguments["code"])
        return f"错误：未知工具 -> {name}"
    except KeyError as e:
        return f"错误：缺少参数 {e}"
    except Exception as e:  # 兜底：工具内部错误不中断 Agent 循环
        return f"错误：工具执行异常 -> {type(e).__name__}: {e}"
