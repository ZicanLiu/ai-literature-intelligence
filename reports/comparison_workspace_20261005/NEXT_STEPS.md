# v0.1 后停止范围与审查清单

本次在 v0.1 验收后停止；不继续添加功能。未 push、不开 PR。

若随后用户授权准备 PR，先审查：

- 实际中文 UI 与 3–5 分钟组会脚本是否符合组会展示；使用者是否理解 synthetic / AI 草稿 /
  用户修订 / STALE 的区别。没有声称用户有效性或研究新颖性。
- requirements-workspace 与 package-lock 的支持版本，CI 增量步骤在 Linux 的真实执行结果。
  本次只验证本机，没有声称 GitHub CI 已运行。
- API provider 的真实账户 / 明确模型 / 有授权文本 / 费用。先取得具体 live 使用授权，
  再做最小 smoke；本次没有实施它。
- 特定真实论文的复杂表格 / 公式 / 提取限制和人工解释。对 PDF / 技术受限状态保留手工路径。
- 默认数据目录与需要分享的材料。数据库、个人 PDF、Key、.env 和运行产物不纳入 Git。

真实模型能力与用户有效性需要另行任务和合适设计；本产品不会改变旧 pilot 结论。
本次无 KG、GraphRAG、向量库、OCR、multi-user、cloud、benchmark、新研究实验或旧 pilot 重分析。
