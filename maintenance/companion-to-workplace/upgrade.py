"""Targeted, conflict-aware Workhorse upgrade and rollback. No data writes."""

from __future__ import annotations
import argparse, ast, datetime, hashlib, json, os, shutil, socket, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def linked(p):
    return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())


def safe(root, relative):
    p = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Unsafe release path.")
    for item in [p, *p.parents]:
        if item == root:
            break
        if linked(item):
            raise ValueError("Linked installation path refused: " + relative)
    if p.exists() and p.is_file() and p.stat().st_nlink > 1:
        raise ValueError("Hard-linked installation file refused: " + relative)
    return p


def atomic(p, raw):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=p.parent, prefix=".workhorse-upgrade-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, p)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply_hunks(text, hunks):
    for h in hunks:
        if text.count(h["old"]) != 1:
            raise ValueError(
                "Version conflict: a required source block is missing or ambiguous. Nothing has been overwritten."
            )
        text = text.replace(h["old"], h["new"], 1)
    return text


def ensure_stopped(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError(
                f"Port {port} is active. Stop Workhorse before applying or rolling back. Use --port if you configured a different port."
            )


def check_python(root):
    python = (
        root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(python if python.exists() else Path(sys.executable))


def smoke(root, python):
    result = subprocess.run(
        [python, str(root / "scripts" / "verify_install.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise ValueError(
            "Startup health check failed: " + (result.stderr or result.stdout)[-1800:]
        )
    return result.stdout.strip()


def restore(root, backup, check=True):
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest["target"] != str(root):
        raise ValueError("Backup belongs to a different installation.")
    # Validate every backup and current target before changing anything.
    for name, item in manifest["files"].items():
        p = safe(root, name)
        if check and (sha(p.read_bytes()) if p.exists() else None) != item["after"]:
            raise ValueError(
                "Later edits detected: " + name + ". Refusing to overwrite them."
            )
        if (
            item["before"] is not None
            and sha((backup / name).read_bytes()) != item["before"]
        ):
            raise ValueError("Backup checksum mismatch: " + name)
    for name, item in manifest["files"].items():
        p = safe(root, name)
        if item["before"] is None:
            p.unlink(missing_ok=True)
        else:
            atomic(p, (backup / name).read_bytes())
    manifest["status"] = "rolled_back"
    atomic(backup / "manifest.json", json.dumps(manifest, indent=2).encode())
    return manifest


def install(root, yes=False, port=8765):
    ensure_stopped(port)
    runtime = safe(root, "workhorse/runtime.py")
    if not runtime.exists():
        raise ValueError("Choose the existing installed Workhorse directory.")
    original = runtime.read_text(encoding="utf-8")
    if "WORKHORSE_WORKPLACE_V1" in original:
        print("This upgrade is already installed. No changes made.")
        return
    if "WORKHORSE_COMPANION_V2" not in original or "c.close()" not in safe(root, "server.py").read_text(encoding="utf-8"):
        raise ValueError(
            "Companion 0.3.1 is required; install the SQLite-fix release first."
        )
    profile = "workplace"
    manifest = json.loads((HERE / "release.json").read_text())
    changes = {}
    before_hashes = {}
    for name in (
        set(manifest["patches"][profile]) | set(manifest["assets"]) | {"web/index.html"}
    ):
        p = safe(root, name)
        before_hashes[name] = sha(p.read_bytes()) if p.exists() else None
    for name, hunks in manifest["patches"][profile].items():
        p = safe(root, name)
        content = p.read_text(encoding="utf-8")
        changes[name] = apply_hunks(content, hunks).encode()
    html = safe(root, "web/index.html")
    content = html.read_text(encoding="utf-8")
    if content.count("</head>") != 1:
        raise ValueError("HTML head not recognised; cannot safely add assets.")
    additions = "".join(
        tag
        for path, tag in [
            (
                "/workplace.css",
                '<link rel="stylesheet" href="/workplace.css">',
            ),
            ("/workplace.js", '<script src="/workplace.js" defer></script>'),
            (
                "/workhorse-appearance.css",
                '<link rel="stylesheet" href="/workhorse-appearance.css">',
            ),
        ]
        if path not in content
    )
    if additions:
        changes["web/index.html"] = content.replace(
            "</head>", additions + "</head>"
        ).encode()
    for name, entry in manifest["assets"].items():
        p = safe(root, name)
        raw = (HERE / "files" / name).read_bytes()
        if sha(raw) != entry["sha256"]:
            raise ValueError("Release payload checksum failed: " + name)
        if p.exists() and sha(p.read_bytes()) not in entry["accepted"] + [
            entry["sha256"]
        ]:
            raise ValueError(
                "Unrecognised edited file: "
                + name
                + ". Nothing changed; provide your current source to merge it."
            )
        changes[name] = raw
    for name, raw in changes.items():
        if name.endswith(".py"):
            ast.parse(raw.decode(), filename=name)
    # Validate the candidate in a source-only isolated copy, never the real SQLite DB.
    python = check_python(root)
    with tempfile.TemporaryDirectory(prefix="workhorse-candidate-") as temp:
        candidate = Path(temp)
        for folder in ("workhorse", "web", "scripts"):
            for p in (root / folder).rglob("*"):
                if (
                    p.is_file()
                    and "__pycache__" not in p.parts
                    and p.suffix in (".py", ".js", ".css", ".html", ".svg")
                ):
                    source = safe(root, p.relative_to(root).as_posix())
                    dest = candidate / p.relative_to(root)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(source.read_bytes())
        (candidate / "server.py").write_bytes(safe(root, "server.py").read_bytes())
        for name, raw in changes.items():
            p = candidate / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        print(smoke(candidate, python))
    print("Target:", root)
    print("Changed files:\n" + "\n".join(sorted(changes)))
    print(
        "Preserved: base stylesheet, SQLite, .env, workspaces and models. Chat JS receives a snapshot hook."
    )
    if (
        not yes
        and input("Type APPLY to install this reviewed upgrade: ").strip() != "APPLY"
    ):
        print("Cancelled.")
        return
    for name in changes:
        p = safe(root, name)
        if (sha(p.read_bytes()) if p.exists() else None) != before_hashes[name]:
            raise ValueError("Installation changed during review: " + name)
    safe(root, "backups")
    backup = (
        root
        / "backups"
        / ("workplace-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    )
    backup.mkdir(parents=True)
    journal = {"target": str(root), "status": "applying", "files": {}}
    for name, raw in changes.items():
        p = safe(root, name)
        before = p.read_bytes() if p.exists() else None
        if before is not None:
            b = backup / name
            b.parent.mkdir(parents=True, exist_ok=True)
            b.write_bytes(before)
        journal["files"][name] = {
            "before": sha(before) if before is not None else None,
            "after": sha(raw),
        }
    atomic(backup / "manifest.json", json.dumps(journal, indent=2).encode())
    try:
        for name, raw in changes.items():
            atomic(safe(root, name), raw)
        print(smoke(root, python))
        journal["status"] = "installed"
        atomic(backup / "manifest.json", json.dumps(journal, indent=2).encode())
    except BaseException:
        restore(root, backup, check=False)
        raise
    print("Installed. Backup:", backup)
    print("Restart Workhorse and press Ctrl+F5. Open Preview & files and choose Working style.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "rollback"])
    parser.add_argument(
        "--target", type=Path, default=Path.home() / "Desktop" / "Workhorse_Local_Agent"
    )
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    root = args.target.resolve(strict=True)
    if args.action == "install":
        install(root, args.yes, args.port)
    else:
        ensure_stopped(args.port)
        backups = sorted((root / "backups").glob("workplace-*"))
        backup = (
            args.backup.resolve(strict=True)
            if args.backup
            else backups[-1] if backups else None
        )
        if not backup:
            raise ValueError("No upgrade backup found.")
        state = json.loads((backup / "manifest.json").read_text())["status"]
        if state == "rolled_back":
            print("Already rolled back.")
            return
        if (
            not args.yes
            and input("Type RESTORE to roll back " + str(backup) + ": ").strip()
            != "RESTORE"
        ):
            return
        restore(root, backup, check=state != "applying")
        print("Restored source files. SQLite and project data were preserved.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Upgrade stopped:", e, file=sys.stderr)
        sys.exit(1)
