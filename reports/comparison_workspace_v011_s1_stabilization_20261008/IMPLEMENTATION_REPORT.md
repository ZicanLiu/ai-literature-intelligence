# S1 分操作预算与条件双族 pilot

日期：2026-10-08（Asia/Shanghai）。任务基线为clean诊断分支371fe9f；使用Git CLI建立D盘独立worktree和codex/comparison-workspace-v011-s1-stabilization分支，保留入口工作区既有未跟踪报告。任务显式指定此基线，未另行合并main。

业务补丁128c187：DeepSeek extraction none/12000，analysis high/32000；现有显式effort优先。Run、存储/三种导出/UI历史记录max_output_tokens，旧记录unknown/null。没有新增预算用户设置；OpenAI原有12000行为保持。适配器读取相同stage policy，settings只显示预算默认。

只修改预算/provenance、最小UI/guide与现有回归。科学identity/locator validator、prompt、provider schema、parser和冻结科研artifact均未改。Live后业务代码变化=0；Phase D未触发。

最终状态：OFFLINE_PATCH_PASS / S1A_PASS / S1B_FAIL。A的正常真实PDF工作流完整通过并有16个AI审计单元；B在extraction的results[2].evidence[0].paper_id跨paper身份上被安全拒绝，按照零retry边界停止。未把失败proposal保存为科学结果。

仓外live-study目录名：s1_stabilization_two_family_pilot_20261008。完整Run、PDF、数据库、源审计、调用register与captures/exports只在仓外。仓内只提交实现和这三份脱敏交付报告。

真实调用3（均DeepSeek Flash生成），input180735/output35382/total216117，reasoning23601（output子集）；无连接测试、OpenAI或自动retry。Key未输出/哈希/写入产物，.env未读取；交付前扫描实际credential与sentinel仅输出boolean/count。

Validator weakened? NO。AI source audits are not human gold. No push/PR/merge was performed. 未触碰PR #87，未开始R10/R4/S2。

下一行动：FIX_ONE_REPEATED_PRODUCT_PROBLEM_FIRST；只记录下一任务ownership澄清方向，本轮不执行。
