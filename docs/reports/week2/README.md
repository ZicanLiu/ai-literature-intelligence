# 第二周成果索引

- 计划周期：2026-07-27—2026-08-02
- 组内汇总节点：2026-08-01
- Milestone：第二周检索、数据质量与排序协作

当前六项任务均处于计划或开发阶段。表中的路径是约定交付入口，不表示文件或功能已经
完成；本页面由组长在最终集成时根据实际 Pull Request 更新。

`docs/project/summer_plan_2026.md` 是暑期方向初稿；第二周的实际人员分工和路径以已经
发布的 Issue、本页及文件归属表为准。

| 方向 | 负责人 | 代码入口 | 数据目录 | 测试 | 报告 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 批量实验与集成 | 刘子璨 | 待提交 | `data/samples/w2/integration/` | 待提交 | 待提交 | 计划中 |
| OpenAlex v2 | 武子恒 | 待提交 | `data/samples/w2/openalex_client/` | 待提交 | 待提交 | 计划中 |
| 去重与复核 | 贾馥诚 | 待提交 | `data/review/` | 待提交 | 待提交 | 计划中 |
| 领域查询与标注 | 陈星妤 | 待提交 | `data/domain/`、`data/manual/` | 待提交 | 待提交 | 计划中 |
| 质量门禁 | 黄斌 | 待提交 | `data/samples/w2/quality_gate/` | 待提交 | 待提交 | 计划中 |
| 两阶段排序 | 蒲正杰 | 待提交 | `data/analysis/w2_ranking/` | 待提交 | 待提交 | 计划中 |

## 开始任务前

```powershell
git switch main
git pull --ff-only origin main
python -m unittest discover -s tests/automated -p "test_*.py" -v
git switch -c <Issue 中规定的分支名>
```

协作前先阅读：

- [第二周文件归属与协作边界](../../collaboration/w2_file_ownership.md)
- [第二周数据接口约定](../../project/w2_data_contracts.md)
- [贡献指南](../../../contributing.md)

任务完成后应把代码、数据、测试和报告的真实路径补充到上表；未提交或未验证的内容继续
标记为“待提交”，不能提前写成已完成。
