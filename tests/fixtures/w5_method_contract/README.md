# W5 Method Contract Fixtures

`lexical_fixture.csv` 和 `dense_fixture.csv` 是两个虚构但合法的 60-pair 排名。
它们严格覆盖冻结 Candidate Pool，每个 RQ 各 20 条，不包含任何 benchmark label、
judgement 或正式算法结果。

- `lexical_fixture` 使用带并列分数的 `pair_id` 升序，专门覆盖 deterministic tie-breaking；
- `dense_fixture` 使用反向顺序，为 RRF、evaluator adapter 和 error-analysis 提供不同排名。

这些文件只能用于离线测试和独立开发，不代表 BM25、SPECTER2 或其他正式 W5 实验。
正式 method output 必须另行生成 manifest，记录真实代码、环境、参数、模型与运行 provenance。
