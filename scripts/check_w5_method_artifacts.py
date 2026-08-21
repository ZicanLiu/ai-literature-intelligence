import sys
import subprocess
from pathlib import Path

def main():
    """
    轻量级检查机制：
    如果不依赖未来算法 PR，当前没有正式 method artifact 时，不报错，直接跳过；
    如果有 manifest 文件，则调用验证入口。
    """
    # 扫描目录下是否包含 W5 method manifest 的 JSON 文件
    manifest_candidates = list(Path('.').rglob('*w5_method*manifest*.json'))

    if not manifest_candidates:
        print("ℹ️ 当前没有待验证的正式 W5 artifact。检查通过。")
        sys.exit(0)

    print(f"✅ 发现待验证的 W5 Method Artifact: {[str(p) for p in manifest_candidates]}")
    print("🚀 开始执行 W5 可复现检查...")

    try:
        # 调用已有的 validate_w5_method
        subprocess.run(
            [sys.executable, "-m", "app.validate_w5_method"],
            check=True,
            text=True
        )
        print("✅ W5 Method Artifact 验证 PASS！")
    except subprocess.CalledProcessError as e:
        print(f"❌ W5 Method Artifact 验证 FAIL，退出码: {e.returncode}")
        # 如果验证失败，必须将错误传递给 CI，让工作流变红
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
