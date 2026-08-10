# 第二周测试 fixture

第二周各任务使用独立 fixture，约定路径如下，由对应成员在提交测试时创建：

```text
openalex/       OpenAlex HTTP 响应和分页案例
dedup/          确定重复、疑似重复和非重复案例
domain_query/   领域词典、查询生成和标注案例
validation/     正常与故意错误的数据验收案例
ranking/        TF-IDF、排序和指标已知答案案例
pipeline/       多查询、provenance、统一排序与 batch 离线端到端案例
```

统一规则：

1. fixture 必须小型、可读、可解释；
2. 自动测试不得依赖真实网络，也不得读取 `.env`；
3. fixture 不得包含真实 API Key；
4. 成员只修改自己任务对应的 fixture；
5. 故意错误的数据必须在文件名或同目录说明中明确标记；
6. fixture 只服务于离线测试，不能冒充真实实验结果。
