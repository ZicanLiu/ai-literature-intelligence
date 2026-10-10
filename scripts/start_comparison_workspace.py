"""Windows team preview bootstrap; all runtime data stays outside the checkout."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description="Install/start the offline team preview")
    parser.add_argument("--install", action="store_true", help="Install/update Python dependencies")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the frontend after updating code")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ is required (3.13 recommended).")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        parser.error("Install Node.js 22.13+ with npm, then reopen your terminal.")
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    if tuple(map(int, version.split(".")[:2])) < (22, 13):
        parser.error("Node.js 22.13+ is required.")
    root = Path(__file__).resolve().parents[1]
    directory = root / ".venv-workspace"
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # This launcher always hard-disables Live, including connection probes. Never load .env.
    env = {key: value for key, value in os.environ.items()
           if not key.endswith("_API_KEY") and key not in {"COMPARISON_OPENAI_MODEL", "COMPARISON_DEEPSEEK_MODEL"}}
    env["DISABLE_LIVE_API"] = "true"
    fresh = not python.is_file()
    if fresh:
        print("Creating isolated .venv-workspace...", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    if fresh or args.install:
        subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements-workspace.txt"],
                       cwd=root, env=env, check=True)
    if args.install:
        subprocess.run([npm, "ci"], cwd=root / "web/comparison-workspace", env=env, check=True)
    command = [str(python), "-m", "app.comparison_workspace_main", "--port", str(args.port)]
    if args.rebuild or args.install:
        command.append("--rebuild")
    if args.data_dir:
        command.extend(["--data-dir", str(args.data_dir.resolve())])
    print(f"Team Preview (Live hard-disabled): http://127.0.0.1:{args.port}\nStop: Ctrl+C", flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Startup failed: {exc}. See docs/comparison_workspace/TEAM_PREVIEW.md", file=sys.stderr)
        sys.exit(1)
