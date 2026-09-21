"""Bounded subprocess calls into a separate Semantica environment."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from .contracts import VERSION, dumps

ACTIONS = frozenset({'extract', 'conflicts', 'answer', 'probe'})


class Runtime:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.last = {"status": "not_probed"}
        self.process = None
        self.process_lock = threading.Lock()
        self.closed = False
        self.probed_at = 0.0

    def close(self):
        with self.process_lock:
            self.closed = True
            process = self.process
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def command(self) -> list[str] | None:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
        executable = base / "knowledge-runtime" / "knowledge-worker.exe"
        if executable.is_file():
            return [str(executable)]
        python = os.environ.get("ZH_PIPELINE_PYTHON")
        script = base / "src" / "knowledge_worker.py"
        if python and not getattr(sys, "frozen", False) and Path(python).is_file() and script.is_file():
            return [python, str(script)]
        return None

    def status(self) -> dict:
        last = self.last
        if last.get("status") == "ready" and time.monotonic() - self.probed_at > 300:
            last = {**last, "status": "probe_expired"}
        command = self.command()
        return {"configured": not self.closed and bool(command) and bool(os.environ.get("ZH_PIPELINE_MODEL")),
                "worker_installed": bool(command), "last_probe": last,
                "closed": self.closed, "model": os.environ.get("ZH_PIPELINE_MODEL", ""),
                "remote_inference": False}

    def call(self, action: str, body: dict) -> dict:
        if action not in ACTIONS or not isinstance(body, dict) or 'action' in body:
            raise ValueError("不支持的 worker 操作或保留字段 action 被覆盖")
        if self.closed:
            raise RuntimeError("知识运行时已关闭")
        command = self.command()
        if not command:
            raise RuntimeError("Semantica 知识处理运行时未安装；请配置 ZH_PIPELINE_PYTHON 或打包 knowledge-runtime")
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("知识模型正在处理另一请求，请稍后重试")
        # All operations after acquiring the lock must be inside try/finally,
        # including mkdir: permission/disk errors must not permanently lock it.
        try:
            work = self.root / "pipeline-runtime"
            work.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="request-", dir=work) as temp:
                source, target = Path(temp) / "input.json", Path(temp) / "output.json"
                payload = dumps({"action": action, **body})
                if len(payload.encode("utf-8")) > 8 * 1024 * 1024:
                    raise ValueError("worker 请求超过大小限制")
                source.write_text(payload, "utf-8")
                env = os.environ.copy()
                env.update({"PYTHONIOENCODING": "utf-8", "SEMANTICA_DISABLE_PROGRESS": "1",
                            "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1"})
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                    env.pop(key, None)
                log_path = work / "last-worker.log"
                with log_path.open("wb") as log:
                    with self.process_lock:
                        if self.closed:
                            raise RuntimeError("知识运行时已关闭")
                        self.process = subprocess.Popen(command + [str(source), str(target)],
                            stdout=log, stderr=subprocess.STDOUT, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        process = self.process
                    try:
                        process.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise RuntimeError("本地模型调用超过 180 秒，已结束 worker；可重试")
                if process.returncode or not target.is_file():
                    raise RuntimeError("Semantica 调用失败；详见本机 pipeline-runtime/last-worker.log")
                if target.stat().st_size > 8 * 1024 * 1024:
                    raise RuntimeError("Semantica 返回内容超过限制")
                result = json.loads(target.read_text("utf-8"))
                if not isinstance(result, dict) or result.get("protocol") != VERSION or not result.get("semantica_version"):
                    raise RuntimeError("Semantica 返回协议不兼容")
                if action == "probe":
                    self.last = result
                    self.probed_at = time.monotonic()
                return result
        except Exception as exc:
            if action == "probe":
                self.last = {"status": "failed", "message": str(exc)}
            raise
        finally:
            with self.process_lock:
                self.process = None
            self.lock.release()
