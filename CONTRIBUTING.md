# 贡献指南

本项目当前稳定基线为 v0.2.0。真实文献数据来自 OpenAlex；稳定功能包括文献获取、清洗、严格规则去重、初步排序、CSV、SQLite、图表和运行摘要。

## 1. 开始 Issue 前

1. 切换到 `main` 并拉取最新远程基线；
2. 阅读 [`AGENTS.md`](AGENTS.md)；
3. 阅读 [`AI_PROJECT_ONBOARDING.md`](docs/project/AI_PROJECT_ONBOARDING.md)；
4. 阅读 [`CURRENT_STATUS.md`](docs/CURRENT_STATUS.md)；
5. 阅读自己的 Issue 和相关模块文档；
6. 从最新 `main` 创建独立任务分支；
7. 如果使用 AI，先让 AI 只读核对 Git 状态、相关源码、测试和调用关系，再开始修改。

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/<issue-name>
```

可复制到新 Issue：

> ## 开始前必读
>
> 开始本 Issue 前，请先同步最新 `main`，并阅读 `AGENTS.md`、`docs/project/AI_PROJECT_ONBOARDING.md`、`docs/CURRENT_STATUS.md` 及与本 Issue 相关的模块文档。如果使用 AI 辅助开发，请先让 AI 核对当前源码、测试和 Git 状态，不要基于旧分支、旧压缩包或历史聊天直接修改。

## 2. 分支与合并规则

- 禁止直接向 `main` 推送或在 `main` 上提交任务成果。
- 开始任务前先同步最新 `main`，再为单个任务创建独立短期分支。
- 一个分支只解决一个明确任务，完成后通过 Pull Request 合并。
- 分支建议使用 `docs/`、`test/`、`analysis/`、`data/`、`fix/` 或 `feat/` 前缀。
- Pull Request 合并后及时同步本地 `main`；已结束的短期分支不继续堆积新任务。

示例：

```text
docs/week1-environment-git
analysis/week1-openalex-quality
test/week1-cli-cases
```

## 3. 安全与文件边界

不得提交：

- `.env`、API Key 或带密钥的请求 URL；
- `.venv/`、`venv/` 等虚拟环境；
- `__pycache__/`、`*.pyc` 和工具缓存；
- 个人手机号、学号、申请书原件或未经授权的 PDF；
- 无法说明来源和用途的数据文件。

提交前运行：

```powershell
git status --short
git check-ignore -v .env
```

不要用 `git add .`。应精确添加本任务修改的文件，避免把本地配置或无关结果带入提交。

## 4. 输出与实验数据

- 普通运行写入 `outputs/experiments/<run_id>/`，每次目录独立，默认由 `.gitignore` 忽略。
- `outputs/baselines/` 保存经过验证、可复现的固定基线。
- `outputs/live_test_*/` 保存有明确日期、检索词和记录数的小规模真实测试。
- 不要直接强制添加普通实验。确有长期价值的结果应核对数据来源、敏感信息、记录数和
  `run_config.json` 后，通过单独任务提升到 `outputs/baselines/`。
- 不得把 mock 数据描述成真实论文，也不得把小样本实验描述成算法评测结论。

## 5. 修改与验证

本阶段不随意修改评分权重、去重规则或核心流程。若任务确实需要修改核心行为，必须先在 Issue 中说明问题、证据和影响范围。

普通文档或分析任务至少检查相关文件；影响运行流程的改动至少执行：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
python -m unittest discover -s tests/automated -p "test_*.py" -v
```

只有本地合法配置 OpenAlex Key 时，才执行 live 验证；不得把密钥写进命令行、代码、日志或报告。

## 6. Pull Request 要求

Pull Request 必须写明：

1. 修改目的；
2. 修改文件和主要内容；
3. 实际验证命令与结果；
4. 是否涉及数据文件及其来源；
5. 已知限制或需要组长确认的事项。

提交 PR 前确认：

- [ ] 分支不是 `main`；
- [ ] 只包含本任务相关文件；
- [ ] 未提交 `.env`、API Key、虚拟环境或缓存；
- [ ] 没有个人敏感材料或未经授权的 PDF；
- [ ] `preliminary_score` 没有被描述为真实学术价值；
- [ ] 验证方法和实际结果已写入 PR。

## 7. 第二周协作规则

- 开始前阅读
  [`docs/collaboration/W2_FILE_OWNERSHIP.md`](docs/collaboration/W2_FILE_OWNERSHIP.md)，
  以文件归属表为主要边界；共享文件默认由组长在集成时修改。
- 每项任务使用 `tests/fixtures/` 下的独立子目录，不改写其他任务的 fixture。
- live 结果只提交经过整理、来源清楚且体积适中的样例或摘要，不提交完整普通实验目录。
- 涉及真实检索或样例的 PR 必须记录 `keyword`、`run_id` 和记录数量；未执行 live 时
  应明确写“未执行”。
- Git 提交说明默认使用简洁中文，说明实际完成的事情，不把计划写成成果。
- 分支可使用 `feature/`、`test/`、`data/`、`docs/`、`fix/` 或 `chore/` 等前缀。
- 需要修改共享文件时先在 PR 描述中提出，由组长决定如何集成。

## 8. 第四周人工标注任务

涉及 W4 Query Relevance 标注的 Issue 还必须阅读
[`W4_ANNOTATION_GUIDELINE.md`](docs/project/W4_ANNOTATION_GUIDELINE.md)。成员只生成和提交
自己的 `data/annotation_tasks/w4/annotations/<slug>.csv`，不得修改公共 candidate pool、
assignment、research query 配置或其他成员文件。
