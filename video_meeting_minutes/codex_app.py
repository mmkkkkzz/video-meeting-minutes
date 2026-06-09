from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, TextIO


class CodexAppServerError(RuntimeError):
    pass


class CodexAppServerClient:
    def __init__(
        self,
        *,
        cwd: Path,
        command: str = "codex",
        model: str | None = None,
        timeout_seconds: float = 600,
        keep_stderr: bool = False,
    ) -> None:
        self.cwd = cwd
        self.command = command
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._next_id = 1
        self._thread_id: str | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        stderr = None if keep_stderr else subprocess.DEVNULL
        self._process = subprocess.Popen(
            [command, "app-server", "--stdio"],
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(target=self._read_stdout_lines, daemon=True)
        self._stdout_thread.start()

    def _read_stdout_lines(self) -> None:
        if not self._process.stdout:
            self._stdout_queue.put(None)
            return

        for line in self._process.stdout:
            self._stdout_queue.put(line)
        self._stdout_queue.put(None)

    def _readline(self, *, deadline: float, context: str) -> str:
        if not self._process.stdout:
            raise CodexAppServerError("codex app-server stdout is not connected")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexAppServerError(f"Timed out waiting for {context}")

        stdout_queue = getattr(self, "_stdout_queue", None)
        if stdout_queue is None:
            stdout: TextIO = self._process.stdout
            line = stdout.readline()
        else:
            try:
                line = stdout_queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise CodexAppServerError(f"Timed out waiting for {context}") from exc
        if not line:
            raise CodexAppServerError("codex app-server exited unexpectedly")
        return line

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def __enter__(self) -> "CodexAppServerClient":
        self.initialize()
        self.start_thread()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._process.stdin or not self._process.stdout:
            raise CodexAppServerError("codex app-server process is not connected")

        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            line = self._readline(deadline=deadline, context=method)
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CodexAppServerError(json.dumps(message["error"], ensure_ascii=False))
            return message["result"]

        raise CodexAppServerError(f"Timed out waiting for {method}")

    def _read_until_turn_completed(self, turn_id: str) -> str:
        if not self._process.stdout:
            raise CodexAppServerError("codex app-server stdout is not connected")

        deadline = time.monotonic() + self.timeout_seconds
        deltas: list[str] = []
        final_messages: list[str] = []
        while time.monotonic() < deadline:
            line = self._readline(deadline=deadline, context=f"turn {turn_id}")

            message = json.loads(line)
            method = message.get("method")
            params = message.get("params") or {}
            if params.get("turnId") not in {None, turn_id}:
                continue

            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if delta:
                    deltas.append(str(delta))
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                    text = item.get("text")
                    if text:
                        final_messages.append(str(text))
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                error = turn.get("error")
                if error:
                    raise CodexAppServerError(json.dumps(error, ensure_ascii=False))
                if final_messages:
                    return final_messages[-1].strip()
                return "".join(deltas).strip()
            elif method == "error":
                raise CodexAppServerError(json.dumps(params, ensure_ascii=False))

        raise CodexAppServerError(f"Timed out waiting for turn {turn_id}")

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "video-meeting-minutes",
                    "title": "video-meeting-minutes",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "requestAttestation": False,
                    "optOutNotificationMethods": [
                        "mcpServer/startupStatus/updated",
                        "thread/tokenUsage/updated",
                        "account/rateLimits/updated",
                    ],
                },
            },
        )

    def start_thread(self) -> None:
        params: dict[str, Any] = {
            "cwd": str(self.cwd),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "baseInstructions": (
                "日本語で簡潔かつ正確に回答してください。"
                "あなたは動画会議録生成CLIから呼ばれる解析ワーカーです。"
                "ファイル変更、コマンド実行、外部アクセスは行わず、与えられた入力だけで回答してください。"
                "最終回答だけを返してください。"
            ),
        }
        if self.model:
            params["model"] = self.model

        result = self._request("thread/start", params)
        self._thread_id = result["thread"]["id"]

    def ask(
        self,
        text: str,
        *,
        local_images: list[Path] | None = None,
        output_schema: dict[str, Any] | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> str:
        if not self._thread_id:
            raise CodexAppServerError("thread has not been started")

        inputs: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": text,
                "text_elements": [],
            }
        ]
        for image in local_images or []:
            inputs.append(
                {
                    "type": "localImage",
                    "path": str(image.resolve()),
                    "detail": "high",
                }
            )

        params: dict[str, Any] = {
            "threadId": self._thread_id,
            "input": inputs,
            "approvalPolicy": "never",
        }
        turn_model = model or self.model
        if turn_model:
            params["model"] = turn_model
        if effort:
            params["effort"] = effort
        if output_schema:
            params["outputSchema"] = output_schema

        result = self._request("turn/start", params)
        turn_id = result["turn"]["id"]
        return self._read_until_turn_completed(turn_id)
