# External Research Evidence Preservation Plan（外部研究证据保存方案）

> 初始状态：**方案比较文档（2026-09-19）**，当时未执行迁移或独立备份。
> 以下原方案保留历史语境；2026-09-21 用户授权执行的实际结果见末节。

## 1. 现状与风险

2026-09-04～09-19 的 29 个证据目录（约 270 MB，含 RCP screening、MCA 人工
裁决、生成器冻结、24 formal outputs、三 Judge 盲评、pre-unblinding 闭包与
授权、first-look 解盲分析、Full Pro 敏感性审计、组会材料）全部位于
`<external-evidence-root>`（非 Git 仓库）；Full Pro 数据曾以
`<external-supplement-location>` 下 zip 存在，**本轮审计期间已被解压删除 zip**
（目录内容仍在）——这本身就是单机单副本风险的现实例证。

已验证事实（2026-09-19，third-layer closure 后口径）：25 个包带 SHA256 manifest，
独立重算得 9,307 VERIFIED_BYTES；supplement 12 个期望成员为
SELF_HASHED_UNANCHORED（无上游锚）；唯一 1 处 mismatch 为下游包已文档化的
空白模板换行符例外；0 缺失（supplement 期望成员 roster 当前 12/12 在场）。
哈希清单提供字节完整性，但**不提供版本历史、异地冗余或时间公证**。

## 2. 方案比较

| 方案 | 可复现性 | 体量/成本 | 隐私 | 不可篡改性 | 协作 | 引用 | 误改风险 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. raw evidence 直接入主 repo | 高（与代码同 ref） | 大：~270MB+，history 膨胀；RCP integration 单包 38MB/4239 文件 | 中：需先清扫个人信息（coordinator_private 等） | 中：Git 可 force-push 改写，需分支保护 | 高 | 高（commit SHA 即引用） | 中：工作区操作易误触 |
| B. 独立 evidence repo（推荐基线） | 高 | 同 A 但与代码库隔离 | 同 A（入库前清扫） | 中（同 A，可加 tag 签名） | 中：仅证据流 | 高（独立 SHA） | 低：单独仓库、只读惯例 |
| C. Git LFS / artifact archive | 高 | 指针轻、存储集中；需 LFS 服务 | 同 A | 中：LFS 对象可被替换，需锁 | 中 | 中（LFS SHA 不在 commit 树内） | 中 |
| D. hash registry + 不可变外部存档 | 高（registry 可复算） | 低（registry 小）| 高（存档可离线） | 高（WORM/对象锁/只读介质） | 低：存档不面向协作 | 中（按 hash 引用） | 极低 |
| E. 混合（B + D，推荐） | 最高 | 中 | 高 | 高 | 中 | 高 | 低 |

## 3. 推荐：E（混合）

1. **独立 evidence repo（方案 B）**：把 29 个目录按原结构 + 各自
   SHA256 manifest 入库，作为 **RAW PRIVATE EVIDENCE**——原始字节一律
   原样保留、访问受限，**绝不为了入库修改任何原始字节**。如需对外共享
   或展示，另行生成 **SANITIZED DERIVATIVE**（脱敏派生副本：独立目录、
   独立 manifest、明确标注 derivation 规则），绝不覆盖或替代 raw evidence。
   一次 initial freeze commit + 每包 annotated tag（如 `freeze/mca-final-20260906`）。
2. **hash registry（方案 D 组件）**：本 workbench 的
   `integrity/evidence_integrity.csv`（9,307 个锚定文件级验证哈希 + supplement 成员身份哈希）+ 每包
   manifest SHA 作为 registry 冻结快照入库（体积小），作为证据 repo 的
   独立交叉锚点。
3. **异地备份**：证据 repo push 到私有远端；关键 freeze tag 附 SHA256
   清单的独立副本（邮件/网盘/WORM 均可），防单点。
4. **时间公证（可选增强）**：对每包 manifest SHA 做 RFC3161 timestamp 或
   commit 签名，弥补"本地哈希不作时间证明"的已知限制。

## 4. 迁移前置检查清单（执行时逐项确认）

- [ ] 每包 SHA256 manifest 独立重算全通过（工具：`python -m app.build_downstream_evidence_registry`）；
- [ ] 文档化例外（目前 1 处）在 registry 中登记且分类依据仍在；
- [ ] `download/` 下解压的 supplement 文件补齐 zip 原件或以其成员哈希为准入账；
- [ ] 隐私清扫：绝对路径、个人身份、`PRIVATE_*` 目录按项目规则处置并记录；
- [ ] 证据 repo 分支保护 + 禁 force-push；
- [ ] 迁移后 registry 在新位置重跑，哈希一致才宣布完成。

## 5. 明确不做

- 不把 evidence 提升为"正式 benchmark/official artifact"（那是科研流程
  决策，不是保存决策）；
- 不在保存过程中 normalize/重排/重打包任何原始字节；
- 不修改本 worktree 之外的任何现有目录来"方便入库"。

## Execution status — 2026-09-21

**Minimum independent backup completed; hash verification completed.**

- 用户授权将 29 个登记 package（10,086 files / 276,455,443 bytes）、现有 manifest、
  Full Pro ZIP/现存 12 个同名成员及本地辅助材料原样保存到另一块物理磁盘。
  整个 backup payload 为 10,121 files / 279,740,567 bytes；逐文件回读 SHA256 全一致，
  missing/unexpected/source drift 均为 0；包括空目录在内的 595 个 package 目录核验一致。
- 从备份位置重新构建 registry 并完成 formal first-look：28/28 MATCH，24/144/72/432 lattice
  完整，Full Pro 24/144 roster 完整。既有 manifest 的 9,307 VERIFIED_BYTES、1 个原分类空白模板
  例外、0 missing 保持；12 个 supplement 成员继续标为 SELF_HASHED_UNANCHORED。
- 现存恢复 ZIP 与下载目录同名文件仅 README 不一致。用户授权以 ZIP 作为后续验证输入；
  两份原始快照和哈希分别保留，无覆盖、无删文件。此冲突独立记录，**不是** frozen manifest
  新豁免，也没有为 ZIP 声称此前不存在的 immutable trust anchor。
- 29 个 package 已迁入逻辑位置 `MVP/evidence_pilot_202609`，仅顶层 lowercase；迁移前后
  所有内部文件名、相对路径和字节一致。新 root 的 registry 与 formal first-look 验证通过。
- 派生 registry/integrity/analysis 和维护记录单独保存，原始 evidence 不进入公共代码库。

这是**同机不同物理磁盘**的最小冗余，尚不等于异地备份、远端独立验证、WORM 或时间公证。
私有 evidence repo、异地冗余和访问控制的长期方案仍未完成；本轮没有创建或发布 evidence repo。
具体私人位置只记录在本地 maintenance 报告，不提交个人绝对路径。
