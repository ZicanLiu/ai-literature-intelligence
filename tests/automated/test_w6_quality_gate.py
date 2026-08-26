import unittest
from pathlib import Path
from app.w6_quality_gate import W6QualityGate

class TestW6QualityGate(unittest.TestCase):
    def setUp(self):
        # 指定好咱们已知的好数据 (Valid Bundle)
        self.valid_manifest = Path("tests/fixtures/w6_bootstrap/valid/bundle_manifest.json")

    def test_valid_bundle_passes(self):
        """测试：合法的完整数据包必须 100% 亮绿灯通过"""
        gate = W6QualityGate(self.valid_manifest, mode="full")
        report = gate.run_all_checks()
        
        self.assertEqual(report["gate_result"], "PASS", "合法的 fixture 必须通过门禁")
        self.assertEqual(len(report["errors"]), 0, "合法的 fixture 不应有任何 error")
        self.assertGreater(len(report["files_checked"]), 0, "必须读取到文件")

    def test_dev_hidden_overlap_fails(self):
        """测试：故意制造数据泄漏 (Dev 和 Hidden 集合重叠)，门禁必须精准拦截"""
        gate = W6QualityGate(self.valid_manifest, mode="basic")
        
        # 先正常跑一遍，把基础数据加载进 gate.bundle_data
        gate.run_all_checks()
        
        # 核心破坏逻辑：手动篡改内存里的数据，让 dev 集合里混入 hidden 的数据
        gate.bundle_data["split_sets"] = {
            "dev": {"topic_1", "topic_2"},
            "hidden": {"topic_2", "topic_3"}  # 重点：topic_2 同时出现在两边，发生泄漏！
        }
        
        # 重置报告状态，单独测试防泄漏检查
        gate.report["errors"] = []
        gate.report["gate_result"] = "PASS"
        gate._check_leakage_cross_boundary()
        
        # 验证门禁是否成功报错并修改状态
        self.assertEqual(gate.report["gate_result"], "FAIL", "发生泄漏时，门禁必须 FAIL")
        self.assertEqual(len(gate.report["errors"]), 1, "必须记录 1 条具体的泄漏错误")
        self.assertIn("LeakageCheck", gate.report["errors"][0]["check"])

if __name__ == "__main__":
    unittest.main()