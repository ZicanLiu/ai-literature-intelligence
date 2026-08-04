# 领域检索查询集合说明 W2
## 查询列表
1. q1 泛泛检索
检索思路：集合恒星天体相关实体术语，宽泛召回恒星相关文献，扩大初始文献池。
search_str：title_abstract:((stellar atmosphere OR interstellar medium OR B-type star OR G-type star OR M-type star OR solar spectrum) AND (stellar spectrum))

2. q2 方法导向检索
检索思路：聚焦光谱处理技术类词汇，侧重获取光谱降噪、拟合、标定等算法相关文献。

3. q3 任务应用检索
检索思路：面向恒星参数反演、丰度测算等下游应用场景，筛选工程应用类论文。

4. q4 弱关键词扩充检索
检索思路：增加弱相关领域术语，适度放宽范围，避免遗漏交叉学科文献。

5. q5 精准窄检索
检索思路：组合核心强相关术语，筛选主题高度聚焦恒星光谱的高质量文献，降低无关文献占比。

6. q6 基础通用检索
检索思路：使用光谱基础特征术语，覆盖谱线、红移、吸收发射线等基础理论文献。

## 说明
所有检索语句遵循 OpenAlex title_abstract 语法，可直接用于接口调用。