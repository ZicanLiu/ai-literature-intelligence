# 本次工程验证

被验业务HEAD：128c187fefb81af701663fe3e95996f8b3716e51，真实linked worktree / clean。

| 检查 | 结果 |
| --- | --- |
| S1/live_ai/live_safety 定向 unittest | 43 / 12.150s / PASS |
| TypeScript/Vite build | PASS；现有lockfile离线安装76包 |
| Playwright正常/失败/授权/导出流程 | 19 passed / 57.4s；loopback mock，无真实API |
| canonical完整unittest | 1169 / 448.202s / OK，15 skipped；实际exit=0；仅1次 |
| Basic Gate --skip-tests | PASS，0 errors / 0 warnings |
| Full Gate --skip-tests | PASS，0 errors / 3既有warning |
| 完整diff / whitespace | PASS |
| prelive sentinel/实际credential scan | 100 files / 0 findings |

固定canonical顺序遵守：定向/浏览器→完整unittest一次→Basic/Full明确skip-tests→diff→secret scan。

外部日志摘要包装脚本在测试已退出0、result.json已写出之后，打印尾日志时触发UTF-8/GBK UnicodeEncodeError，包装退出1。原log中1169/OK及实际子进程exit0均独立核对；只修仓外日志展示，不改产品或测试环境编码，不重复suite。完整wrapper耗时457.628s与unittest本身448.202s分开。

Full保留历史W1 CSV结构问题、19个旧annotation ID不在统一样例、旧tracked experiment三条warning。负例的坏PDF和missing input报错保留，不当作新回归，也没有删断言或降低错误。

Live后的代码没有改变。收口只检查新增报告的来源边界、完整diff、key/sentinel持久化及Git状态，不再次运行完整suite/Gate。详细原始验证日志/result在仓外validation/，没有提交普通输出或数据库。
