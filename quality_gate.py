import argparse
import sys
import os
import json
import csv
import re

def check_basic_rules():
    errors = []
    warnings = []

    # 1. 必需目录检查 (兼容 src/app/tests/docs 或 data/tests/docs)
    if not os.path.exists("tests"):
        errors.append("缺失必需目录: tests")
    if not os.path.exists("docs"):
        errors.append("缺失必需目录: docs")
    if not (os.path.exists("data") or os.path.exists("src") or os.path.exists("app")):
        errors.append("缺失必需目录: data / src / app")

    # 2. 常见敏感文件风险检查 (放行 .example 和 .template)
    sensitive_patterns = [r"^\.env$", r".*id_rsa$", r".*\.pem$"]
    for root, _, files in os.walk("."):
        if ".git" in root or ".pytest_cache" in root or "venv" in root:
            continue
        for f in files:
            if f.endswith(".example") or f.endswith(".template"):
                continue
            for pattern in sensitive_patterns:
                if re.match(pattern, f):
                    errors.append(f"发现敏感文件风险: {os.path.join(root, f)}")

    # 3. 硬编码 API Key / 敏感信息检测
    key_pattern = re.compile(r'(sk-[a-zA-Z0-9]{20,}|api[_-]?key\s*=\s*["\'][a-zA-Z0-9]{15,}["\'])', re.IGNORECASE)
    for root, _, files in os.walk("."):
        if ".git" in root or ".pytest_cache" in root or "venv" in root:
            continue
        for f in files:
            if f.endswith((".md", ".py")):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
                        for idx, line in enumerate(file, 1):
                            if "your_api_key" in line or "dummy" in line or "mock" in line or "YOUR_API_KEY" in line:
                                continue
                            if key_pattern.search(line):
                                errors.append(f"文件中发现疑似硬编码敏感信息/API Key: {filepath} (第 {idx} 行)")
                except Exception:
                    pass

    # 4. JSON 格式检查 (遍历所有 .json 文件，确保 bad.json 等非规范文件能被检测出来)
    for root, _, files in os.walk("."):
        if ".git" in root or ".pytest_cache" in root or "venv" in root:
            continue
        for f in files:
            if f.endswith(".json"):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", encoding="utf-8-sig") as jf:
                        json.load(jf)
                except Exception as e:
                    errors.append(f"{filepath} 格式非法: {str(e)}")

    # 5. Markdown 本地链接检查
    for root, _, files in os.walk("."):
        if ".git" in root or "venv" in root:
            continue
        for f in files:
            if f.endswith(".md"):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as md_f:
                        content = md_f.read()
                        links = re.findall(r"\[.*?\]\((?!http|https|#)(.*?)\)", content)
                        for link in links:
                            link_path = link.split("#")[0]
                            if link_path and not os.path.exists(os.path.join(os.path.dirname(filepath), link_path)):
                                errors.append(f"{filepath} 中存在失效本地链接: {link}")
                except Exception:
                    pass

    return errors, warnings

def check_full_rules():
    errors, warnings = check_basic_rules()

    # CSV 表头、ID 唯一性与数据一致性检查
    sample_csv = "tests/manual/week2_test_cases.csv"
    if os.path.exists(sample_csv):
        try:
            with open(sample_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    errors.append(f"{sample_csv} 表头为空")
                else:
                    seen_ids = set()
                    for idx, row in enumerate(reader, start=2):
                        if not row: continue
                        if len(row) != len(header):
                            errors.append(f"{sample_csv} 第 {idx} 行列数与表头不一致")
                        case_id = row[0].strip() if len(row) > 0 else ""
                        if case_id in seen_ids:
                            errors.append(f"{sample_csv} 存在重复 ID: {case_id}")
                        seen_ids.add(case_id)
        except Exception as e:
            errors.append(f"读取 CSV 失败: {str(e)}")

    return errors, warnings

def main():
    parser = argparse.ArgumentParser(description="Quality Gate CLI")
    parser.add_argument("--level", choices=["basic", "full"], default="basic", help="检查级别: basic 或 full")
    args = parser.parse_args()

    print(f"=== 质量门禁 (Quality Gate) 开始检查 [级别: {args.level.upper()}] ===")
    
    if args.level == "basic":
        errors, warnings = check_basic_rules()
    else:
        errors, warnings = check_full_rules()

    if warnings:
        print("\n--- 警告信息 (Warnings) ---")
        for w in warnings:
            print(f"  * {w}")

    if errors:
        print(f"\n[严重错误 (ERRORS): {len(errors)} 项]")
        for idx, e in enumerate(errors, 1):
            safe_e = re.sub(r"(sk-[a-zA-Z0-9]{20,})", "sk-******", e)
            print(f"  {idx}. {safe_e}")
        print("\n结论: 质量门禁未通过 (FAILED)！")
        sys.exit(1)
    else:
        print("\n结论: 质量门禁检查全部通过 (PASSED)！")
        sys.exit(0)
def run_quality_gate(level="basic", root_dir="."):
    """为自动化测试脚本提供导出的入口函数，支持传入临时目录 root_dir"""
    current_dir = os.getcwd()
    try:
        if root_dir and str(root_dir) != ".":
            os.chdir(root_dir)

        if level == "basic":
            errors, warnings = check_basic_rules()
        else:
            errors, warnings = check_full_rules()

        if errors:
            return 1
        return 0
    finally:
        os.chdir(current_dir)

# --- 强制加上打印，看看到底有没有进到这里 ---
if __name__ == "__main__":
    print(">>> 成功进入 main 入口！<<<")
    main()