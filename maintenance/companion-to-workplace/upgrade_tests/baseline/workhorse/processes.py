from __future__ import annotations
import os, re, signal, shutil, subprocess, threading, time, uuid
from urllib.parse import urlsplit
from .safety import redact


class Processes:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.RLock()

    @staticmethod
    def routine(command):
        # This is an explicit project-trust convenience, NOT an OS sandbox.
        if re.search(r"[;&|><`\n\r$]", command):
            return False
        return bool(
            re.fullmatch(
                r"(?:npm (?:install|ci|run (?:dev|build|test|lint|start)|test)|git (?:status|diff)(?: --[a-z-]+)?|composer install|php artisan (?:test|serve)|python -m (?:pytest|unittest)(?: discover)?)(?: --[A-Za-z0-9=-]+)*",
                command.strip(),
            )
        )

    def start(
        self, workspace, root, command, background=False, timeout=120, cancel=None
    ):
        if len(command) > 4000:
            raise ValueError("Command is too long.")
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise ValueError("PowerShell is not installed.")
            argv = [
                shell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]
        else:
            argv = ["/bin/bash", "--noprofile", "--norc", "-c", command]
        # Do not inherit provider tokens and other incidental credentials.
        safe = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "LANG",
            "LC_ALL",
        }
        env = {k: v for k, v in os.environ.items() if k.upper() in safe}
        env.update(NO_COLOR="1", TERM="dumb", PYTHONUNBUFFERED="1")
        known = []
        for path in root.glob(".env*"):
            if path.is_file() and path.stat().st_size < 100000:
                for line in path.read_text(errors="ignore").splitlines():
                    if "=" in line:
                        known.append(line.split("=", 1)[1].strip().strip("\"'"))
        p = subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        id = uuid.uuid4().hex
        job = {
            "id": id,
            "workspace": workspace,
            "process": p,
            "command": redact(command, known),
            "stdout": "",
            "stderr": "",
            "started": time.monotonic(),
            "urls": [],
            "reason": None,
            "ended": None,
        }
        with self.lock:
            self.jobs[id] = job

        def read(stream, key):
            for line in iter(lambda: stream.readline(4096), ""):
                line = redact(line, known)
                with self.lock:
                    job[key] = (job[key] + line)[-16000:]
                    for raw in re.findall(
                        r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):\d+[^\s\x1b]*",
                        line,
                    ):
                        try:
                            u = urlsplit(raw.rstrip(".,)"))
                            url = f"{u.scheme}://127.0.0.1:{u.port}"
                        except ValueError:
                            continue
                        if url not in job["urls"]:
                            job["urls"].append(url)
            stream.close()

        for stream, key in [(p.stdout, "stdout"), (p.stderr, "stderr")]:
            threading.Thread(target=read, args=(stream, key), daemon=True).start()

        def monitor():
            while p.poll() is None:
                if cancel and cancel.is_set():
                    self.stop(id, workspace, "cancelled")
                    break
                if time.monotonic() - job["started"] > timeout:
                    self.stop(id, workspace, "timeout")
                    break
                time.sleep(0.1)
            job["ended"] = time.monotonic()

        threading.Thread(target=monitor, daemon=True).start()
        if background:
            time.sleep(0.3)
        else:
            p.wait()
            time.sleep(0.05)
        return self.snapshot(id, workspace)

    def snapshot(self, id, workspace):
        with self.lock:
            j = self.jobs.get(id)
            if not j or j["workspace"] != workspace:
                raise ValueError("Process not found in this workspace.")
            return {
                k: j[k] for k in ("id", "command", "stdout", "stderr", "urls", "reason")
            } | {
                "exit_code": j["process"].poll(),
                "running": j["process"].poll() is None,
                "duration_seconds": round(
                    (j["ended"] or time.monotonic()) - j["started"], 2
                ),
            }

    def stop(self, id, workspace, reason="stopped"):
        self.snapshot(id, workspace)
        j = self.jobs[id]
        p = j["process"]
        j["reason"] = reason
        if p.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
            else:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return self.snapshot(id, workspace)

    def urls(self, workspace):
        return {
            u
            for j in self.jobs.values()
            if j["workspace"] == workspace and j["process"].poll() is None
            for u in j["urls"]
        }

    def close(self):
        for j in list(self.jobs.values()):
            self.stop(j["id"], j["workspace"])
