# 第一周环境复现记录

## 1. 测试环境

- 测试时间：2026-07-25 19:15（UTC+08:00）
- 测试方式：从远程仓库重新 clone，确认临时克隆默认分支为 `main`
- 操作系统：Microsoft Windows 11 家庭版 中文版，64 位，版本 10.0.26200
- Python：3.13.9，满足项目要求的 Python 3.10+
- 环境方式：在 Windows 临时目录的全新克隆中创建独立 `.venv`

本次没有复用当前项目已有环境，也没有运行 live 模式。

## 2. 安装过程

使用的命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

实际结果：

- 虚拟环境创建成功；
- `requirements.txt` 中的依赖安装成功，安装命令返回码为 0；
- `pip check` 返回码为 0，结果为 `No broken requirements found.`。

## 3. mock 运行结果

实际运行命令：

```powershell
.\.venv\Scripts\python.exe -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

实际结果：

| 检查项 | 结果 |
| --- | ---: |
| 程序返回码 | 0 |
| 原始记录 | 20 |
| 清洗后记录 | 20 |
| 去重后记录 | 18 |
| 重复记录 | 2 |

以下输出均成功生成：

- 原始响应 JSON；
- 排序结果 CSV；
- 去重记录 CSV；
- SQLite 数据库；
- 引用量 Top 10 图表；
- `preliminary_score` Top 10 图表；
- 运行摘要。

## 4. `.env` 忽略验证

在临时克隆中创建了不含真实密钥的占位 `.env`，随后执行：

```powershell
git check-ignore -v .env
git status --short
```

结果：

- `git check-ignore` 返回码为 0；
- 命中 `.gitignore` 第 9 行的 `.env` 规则；
- `git status --short` 没有显示 `.env`，临时克隆仍为干净状态；
- 验证完成后已删除占位 `.env`。

本次没有读取、使用或暴露真实 API Key。

## 5. 遇到的问题及处理

1. 最新 `main` 的 README 已链接 `docs/TEAM_GIT_GUIDE.md`，但远程克隆中实际没有该文件。本任务创建该指南，使协作入口不再指向缺失文档。
2. 当前系统中的 `rg.exe` 无法执行，报错为 `Access is denied`。项目检查改用 `git ls-files` 和 PowerShell 只读命令完成，不影响依赖安装和 mock 运行。
3. 首次依赖安装需要从网络下载软件包，耗时较长，但最终返回码、`pip check` 和 mock 运行均正常。

## 6. 结论

项目可以在全新 clone 和全新 Python 3.13.9 虚拟环境中完成依赖安装并成功运行 mock 全流程。README 中的运行命令与实际入口一致，`requirements.txt` 足以支持本次复现，主要输出均正常生成，`.env` 忽略规则有效。

本次结论只覆盖 mock 模式，不代表 live 模式验证；结果来自实际运行。临时环境没有复制、暂存或提交到当前项目仓库。
