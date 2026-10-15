"""执行日志：同时输出到控制台与日志文件，支持步骤级状态追踪。"""
import os
import time


class WorkflowLogger:
    """带时间戳的工作流日志记录器（控制台 + 文件双写）。"""

    def __init__(self, log_dir: str = "logs", task_id: str = ""):
        os.makedirs(log_dir, exist_ok=True)
        filename = f"run_{task_id or time.strftime('%Y%m%d-%H%M%S')}.log"
        self.path = os.path.join(log_dir, filename)
        self._file = open(self.path, "w", encoding="utf-8")

    def _write(self, level: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] [{level:^4}] {message}"
        print(line)
        self._file.write(line + "\n")
        self._file.flush()

    # 语义化日志接口
    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def step(self, index: int, total: int, name: str) -> None:
        self._write("STEP", f"=========== 步骤 {index}/{total}：{name} ===========")

    def agent(self, agent_name: str, msg: str) -> None:
        self._write("AGENT", f"<{agent_name}> {msg}")

    def ok(self, msg: str) -> None:
        self._write(" OK ", msg)

    def skip(self, msg: str) -> None:
        self._write("SKIP", msg)

    def warn(self, msg: str) -> None:
        self._write("WARN", msg)

    def error(self, msg: str) -> None:
        self._write("FAIL", msg)

    def close(self) -> None:
        self._file.close()
