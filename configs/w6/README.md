# 第六周配置

`score_fusion_primary.json` 冻结 Issue #65 的 primary fusion configuration：input methods、
normalization（z_score / per_topic）、weights、version 与 configuration hash。它在任何
W6 Dev/Hidden 评价结果可见之前冻结，冻结后不得回调；需要调整时必须新建版本号并重新冻结。

当前 input methods 是 W6 Bootstrap fixture 的 sparse/dense 组合（真实 W6 方法的
BM25 + SPECTER2 类比），不包含任何 relevance label 信息。

普通成员不得在个人 Issue 中修改本配置。
