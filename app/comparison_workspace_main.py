"""One-process launcher: optional frontend build, then loopback FastAPI."""
import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动本地科研比较工作台 v0.1")
    parser.add_argument("--data-dir", type=Path, help="本地 SQLite / 原始 PDF 目录（默认在仓库外）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--rebuild", action="store_true", help="重新构建前端")
    parser.add_argument("--enable-api", action="store_true", help="显式启用外部 API；还需环境配置及关闭硬离线开关")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    frontend = root / "web/comparison-workspace"
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if args.rebuild or not (frontend / "dist/index.html").is_file():
        if not npm:
            parser.error("首次启动需要 Node.js / npm 来构建前端。")
        if not (frontend / "node_modules").is_dir():
            subprocess.run([npm, "ci"], cwd=frontend, check=True)
        subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    from src.comparison_workspace.storage.repository import Repository
    from src.comparison_workspace.services.workspace import Workspace
    from app.comparison_workspace_api import create_app, default_data_dir
    import uvicorn
    repo = Repository(args.data_dir or default_data_dir())
    providers = {}
    if args.enable_api:
        from src.comparison_workspace.providers.openai_provider import OpenAIProvider
        providers["api"] = OpenAIProvider.from_environment(explicit_enabled=True)
    service = Workspace(repo, providers)
    app = create_app(workspace=service)
    print(f"科研比较工作台 v0.1: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
