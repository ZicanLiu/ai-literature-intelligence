import unittest
import os

class TestCIContract(unittest.TestCase):
    """
    验证 CI 配置本身符合 W5 的工程规范
    """
    
    def setUp(self):
        self.ci_yaml_path = ".github/workflows/ci.yml"
        self.assertTrue(os.path.exists(self.ci_yaml_path), "CI workflow file is missing!")
        
        with open(self.ci_yaml_path, "r", encoding="utf-8") as f:
            self.ci_content = f.read()

    def test_ci_triggers(self):
        """验证 Trigger 是否正确保护 main 分支"""
        self.assertIn("push:", self.ci_content)
        self.assertIn("pull_request:", self.ci_content)
        self.assertIn("main", self.ci_content)

    def test_python_environment(self):
        """验证核心环境隔离 (Python 3.13, 仅核心依赖)"""
        self.assertIn('python-version: "3.13"', self.ci_content, "Must strictly use Python 3.13")
        self.assertIn("pip install -r requirements.txt", self.ci_content, "Must only install core requirements")

    def test_required_commands_exist(self):
        """验证所有要求的执行门禁都存在且拼写正确"""
        required_commands = [
            "python -m app.validate_w4_benchmark",
            "python -m unittest discover -s tests/automated -p \"test_*.py\" -q",
            "python -m app.quality_gate --level basic",
            "python scripts/check_w5_method_artifacts.py"
        ]
        for cmd in required_commands:
            self.assertIn(cmd, self.ci_content, f"Missing required command in CI: {cmd}")

    def test_security_and_live_api_isolation(self):
        """验证不包含 secret 且配置了禁用 Live API 的环境标识"""
        self.assertNotIn("secrets.", self.ci_content, "CI must NOT depend on any secrets")
        self.assertIn("DISABLE_LIVE_API", self.ci_content, "CI must declare DISABLE_LIVE_API")

if __name__ == '__main__':
    unittest.main()
