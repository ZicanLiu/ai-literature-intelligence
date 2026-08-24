# W6 Issue #64 fixture packages

本目录只包含由公共 W6 Bootstrap synthetic artifacts 生成的离线验证包，不是一个真实 W6
Benchmark，也不含真实 annotation、Hidden Test label 或评价结果。

- `benchmark_package/`：`bootstrap_fixture` 状态的 hash-pinned Benchmark workflow package，覆盖
  blind annotation protocol、deterministic review plan、Benchmark manifest 和完整 input graph；
- `boundary_method/`：13-row dynamic-pool Boundary-Aware ranking package，使用公共 fake Topic/Pool/
  source records，严格保持 W5 五列语义并由 W6 method validator 校验。

两包均从 clean revision `74d5956b48ed67082a1b475900e8694bf6f4deff` 生成。Boundary package
声明 `source_records` auxiliary input，且 `relevance_labels_read=false`、
`hidden_test_labels_read=false`。Fixture PASS 只证明结构、hash、determinism 和 no-label contract
兼容，不是方法效果或 Benchmark quality 的科研结论。

复核命令：

```powershell
python -m app.validate_w6_benchmark `
  --package tests/fixtures/w6_issue64/benchmark_package/package_manifest.json
python -m unittest tests.automated.test_w6_benchmark `
  tests.automated.test_w6_boundary_ranking -v
```
