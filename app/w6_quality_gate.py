import json
import argparse
from pathlib import Path
from typing import Any, Dict

# 这里就是我们在调用现有的底层 Validator，坚决不重复造轮子
from src.w6_contracts import validate_w6_bootstrap_bundle

class W6QualityGate:
    def __init__(self, manifest_path: Path, mode: str = "basic"):
        self.manifest_path = manifest_path
        self.mode = mode.lower()
        # 这是任务要求的统一报告格式
        self.report = {
            "files_checked": [],
            "gate_result": "PASS",
            "errors": [],
            "warnings": [],
            "failed_checks": []
        }
        self.bundle_data: Dict[str, Any] = {}

    def _log_error(self, check_name: str, detail: str):
        """记录错误，并立刻将最终结果降级为 FAIL"""
        self.report["errors"].append({"check": check_name, "detail": detail})
        self.report["failed_checks"].append(check_name)
        # 任务硬性规定：不得把 error 降级成 warning 只为了 PASS
        self.report["gate_result"] = "FAIL" 

    def run_all_checks(self) -> dict:
        print(f"🚀 开始执行 W6 Quality Gate ({self.mode.upper()} 模式)...")
        
        # 1. 核心步骤：调用底层的公共 Contract
        try:
            # 这个底层函数一旦发现 Leakage 或 Hash Drift，会直接抛出 ValueError
            self.bundle_data = validate_w6_bootstrap_bundle(self.manifest_path)
            self.report["files_checked"] = list(self.bundle_data["paths"].keys())
        except ValueError as e:
            self._log_error("UnderlyingContractValidator", str(e))
            return self.generate_report()

        # 2. 跨产物 (Cross-Artifact) 的高级检查层
        self._check_leakage_cross_boundary()
        
        if self.mode == "full":
            self._check_method_fusion_and_synthesis()

        return self.generate_report()

    def _check_leakage_cross_boundary(self):
        """在底层校验之上，额外增加业务逻辑的防泄漏检查"""
        # 确保 Dev 和 Hidden 集合绝对没有重合
        split_sets = self.bundle_data.get("split_sets", {})
        dev_topics = split_sets.get("dev", set())
        hidden_topics = split_sets.get("hidden", set())
        
        overlap = dev_topics.intersection(hidden_topics)
        if overlap:
            self._log_error("LeakageCheck", f"Dev 和 Hidden 数据集存在泄漏重叠: {overlap}")

    def _check_method_fusion_and_synthesis(self):
        """Full 模式下的 Synthesis 与 Fusion 验证占位"""
        # 等基础框架跑通了，我们再往这里加东西
        pass

    def generate_report(self) -> dict:
        """生成机器和人类都可读的统一报告"""
        print(f"\n=== W6 Quality Gate 报告: {self.report['gate_result']} ===")
        print(f"检查文件数: {len(self.report['files_checked'])}")
        print(f"发现错误数: {len(self.report['errors'])}")
        
        if self.report["errors"]:
            for err in self.report["errors"]:
                print(f" [❌] {err['check']}: {err['detail']}")
        
        # 输出为 JSON 文件供 CI 使用
        report_path = "w6_gate_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ 机器可读报告已生成: {report_path}")
        return self.report

def main():
    parser = argparse.ArgumentParser(description="W6 Data Quality / Leakage / Artifact Gate")
    # 默认使用现有测试里的 valid bundle
    default_manifest = Path("tests/fixtures/w6_bootstrap/valid/bundle_manifest.json")
    
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--mode", choices=["basic", "full"], default="basic")
    args = parser.parse_args()
    
    gate = W6QualityGate(args.manifest, args.mode)
    gate.run_all_checks()

if __name__ == "__main__":
    main()