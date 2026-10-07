"""Local process manager for user projects. Uses subprocess + psutil for real status/metrics."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import signal
import time
from pathlib import Path
from typing import Any

import psutil

from core.config import USER_BOTS_DIR, DATA_DIR


class ProcessManager:
    """Manages isolated user project processes on the host."""

    def __init__(self):
        self._procs: dict[int, asyncio.subprocess.Process] = {}
        self._meta: dict[int, dict] = {}

    # ── paths ──────────────────────────────────────────────
    # Layout:  user_bots/user001/bot_1/   (files)    data/user001/   (config, db, logs, runtime, backups)
    @staticmethod
    def user_code(user_id: int) -> str:
        return f"user{int(user_id):03d}"

    def user_data_dir(self, user_id: int) -> Path:
        """data/userNNN/ (created with its standard content on first use)."""
        d = DATA_DIR / self.user_code(user_id)
        if not (d / "config.json").exists():
            for sub in ("logs", "runtime", "backups"):
                (d / sub).mkdir(parents=True, exist_ok=True)
            (d / "config.json").write_text(json.dumps({"user": self.user_code(user_id), "hostings": []}, indent=2))
            db_file = d / "database.db"
            if not db_file.exists():
                con = sqlite3.connect(db_file)
                con.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
                con.commit()
                con.close()
        return d

    def project_dir(self, user_id: int, folder: str) -> Path:
        """user_bots/userNNN/<folder>/ -- the only place a hosting's files live."""
        d = USER_BOTS_DIR / self.user_code(user_id) / folder
        d.mkdir(parents=True, exist_ok=True)
        self.user_data_dir(user_id)
        return d

    def log_path(self, user_id: int, folder: str) -> Path:
        d = self.user_data_dir(user_id) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{folder}.log"

    def backup_dir(self, user_id: int) -> Path:
        d = self.user_data_dir(user_id) / "backups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def runtime_path(self, user_id: int, folder: str) -> Path:
        d = self.user_data_dir(user_id) / "runtime"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{folder}.json"

    def write_runtime(self, user_id: int, folder: str, **info) -> None:
        """Per-hosting runtime info (pid, started_at, state) in data/userNNN/runtime/<folder>.json."""
        try:
            self.runtime_path(user_id, folder).write_text(json.dumps(info, indent=2))
        except OSError:
            pass

    # ── lifecycle ──────────────────────────────────────────
    async def start(
        self,
        project_id: int,
        user_id: int,
        folder: str,
        command: str,
        env: dict | None = None,
        cwd: Path | None = None,
        ram_mb: int | None = None,
        cpu: float | None = None,
    ) -> dict[str, Any]:
        if project_id in self._procs:
            proc = self._procs[project_id]
            if proc.returncode is None:
                return {"ok": False, "error": "Already running", "pid": proc.pid}

        work = cwd or self.project_dir(user_id, folder)
        log_file = self.log_path(user_id, folder)
        env_vars = os.environ.copy()
        if env:
            env_vars.update({str(k): str(v) for k, v in env.items()})
        # Where this hosting may keep its own data (never another user's)
        env_vars["ANAJAK_DATA_DIR"] = str(self.user_data_dir(user_id))
        env_vars["ANAJAK_PROJECT_DIR"] = str(work)
        # Soft resource hints for child process (best-effort on shared hosts)
        if ram_mb:
            env_vars["ANJAK_RAM_LIMIT_MB"] = str(int(ram_mb))
        if cpu:
            env_vars["ANJAK_CPU_LIMIT"] = str(cpu)

        log_f = open(log_file, "a", encoding="utf-8")
        try:
            import time as _time
            log_f.write("\n===== START " + _time.strftime("%Y-%m-%d %H:%M:%S") + " =====\n")
            log_f.write(f"[anajak] cwd={work}\n")
            log_f.write(f"[anajak] command={command}\n")
            try:
                listing = sorted([p.name for p in Path(work).iterdir()])[:40]
                log_f.write("[anajak] files: " + ", ".join(listing) + "\n")
            except Exception:
                pass
            for hint in ("main.py", "bot.py", "app.py", "index.js", "package.json", "requirements.txt"):
                if (Path(work) / hint).exists():
                    log_f.write(f"[anajak] found {hint}\n")
            log_f.flush()
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work),
                env=env_vars,
                stdin=asyncio.subprocess.PIPE,
                stdout=log_f,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            log_f.write(f"[anajak] process started pid={proc.pid}\n")
            log_f.flush()
            if ram_mb:
                log_f.write(f"[anajak] resource limits requested: ram={ram_mb}MB cpu={cpu}\n")
                log_f.flush()
        except Exception as e:
            try:
                log_f.write(f"[anajak] START FAILED: {e}\n")
                log_f.flush()
                log_f.close()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}

        self._procs[project_id] = proc
        self._meta[project_id] = {
            "pid": proc.pid,
            "user_id": user_id,
            "folder": folder,
            "started_at": time.time(),
            "log_handle": log_f,
        }
        self.write_runtime(user_id, folder, project_id=project_id, pid=proc.pid, state="running",
                           started_at=time.time(), command=command, path=str(work))
        return {"ok": True, "pid": proc.pid, "status": "running"}

    async def stop(self, project_id: int) -> dict[str, Any]:
        proc = self._procs.get(project_id)
        meta = self._meta.get(project_id, {})
        if not proc:
            # try kill by stored pid
            pid = meta.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            return {"ok": True, "status": "stopped"}

        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=8)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            lh = meta.get("log_handle")
            if lh:
                try:
                    lh.close()
                except Exception:
                    pass
            self._procs.pop(project_id, None)
            self._meta.pop(project_id, None)
            if meta.get("folder"):
                self.write_runtime(meta["user_id"], meta["folder"], project_id=project_id, pid=None,
                                   state="stopped", stopped_at=time.time())
        return {"ok": True, "status": "stopped"}

    async def restart(self, project_id: int, user_id: int, folder: str, command: str, env: dict | None = None, ram_mb: int | None = None, cpu: float | None = None) -> dict:
        await self.stop(project_id)
        await asyncio.sleep(1)
        return await self.start(project_id, user_id, folder, command, env, ram_mb=ram_mb, cpu=cpu)


    async def force_kill(self, project_id: int) -> dict[str, Any]:
        """SIGKILL process tree for emergency stop."""
        meta = self._meta.get(project_id, {})
        proc = self._procs.get(project_id)
        pid = (proc.pid if proc else None) or meta.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # try process group
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception:
                pass
        lh = meta.get("log_handle")
        if lh:
            try:
                lh.close()
            except Exception:
                pass
        self._procs.pop(project_id, None)
        self._meta.pop(project_id, None)
        if meta.get("folder"):
            self.write_runtime(meta["user_id"], meta["folder"], project_id=project_id, pid=None,
                               state="stopped", stopped_at=time.time())
        return {"ok": True, "status": "stopped"}

    def status(self, project_id: int) -> dict[str, Any]:
        proc = self._procs.get(project_id)
        meta = self._meta.get(project_id, {})
        if proc and proc.returncode is None:
            return {
                "status": "running",
                "pid": proc.pid,
                "uptime_sec": int(time.time() - meta.get("started_at", time.time())),
            }
        # check if pid still alive externally
        pid = meta.get("pid")
        if pid:
            try:
                p = psutil.Process(pid)
                if p.is_running():
                    return {"status": "running", "pid": pid, "uptime_sec": int(time.time() - meta.get("started_at", time.time()))}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"status": "stopped", "pid": None, "uptime_sec": 0}

    def metrics(self, project_id: int) -> dict[str, Any]:
        st = self.status(project_id)
        if st["status"] != "running" or not st.get("pid"):
            return {
                "cpu_percent": None,
                "ram_mb": None,
                "status": "stopped",
                "message": "Metric unavailable",
            }
        try:
            p = psutil.Process(st["pid"])
            with p.oneshot():
                cpu = p.cpu_percent(interval=0.1)
                mem = p.memory_info().rss / (1024 * 1024)
            return {
                "cpu_percent": round(cpu, 1),
                "ram_mb": round(mem, 1),
                "status": "running",
                "uptime_sec": st.get("uptime_sec", 0),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"cpu_percent": None, "ram_mb": None, "status": "stopped", "message": "Metric unavailable"}

    async def send_command(self, project_id: int, text: str) -> dict[str, Any]:
        proc = self._procs.get(project_id)
        if not proc or proc.returncode is not None or proc.stdin is None:
            return {"ok": False, "error": "Server is offline"}
        try:
            proc.stdin.write((text.rstrip("\n") + "\n").encode())
            await proc.stdin.drain()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def clear_logs(self, user_id: int, folder: str) -> None:
        path = self.log_path(user_id, folder)
        if path.exists():
            open(path, "w").close()

    def read_logs(self, user_id: int, folder: str, lines: int = 200) -> str:
        path = self.log_path(user_id, folder)
        if not path.exists():
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.readlines()
            return "".join(content[-lines:])
        except Exception:
            return ""


process_manager = ProcessManager()
