# 李亦凡的 AI Agent 项目协作入门记录

> 本文档是 Issue #72「Practice：完成 GitHub + Claude Code 项目协作入门」的练习交付物。
> 它是一份**学习记录**，不是正式项目功能文档，也不参与 W6 科研交付。

- 记录人：李亦凡（GitHub: `lyf541236`）
- 练习分支：`learning/liyifan-agent-onboarding`
- 完成日期：2026-09-20

---

## 1. 我现在理解这个项目是做什么的

这是一个 SRTP 项目的第一阶段 MVP，主题是「AI 在天文光谱数据处理中的应用文献的智能检索、
结构化处理与初步排序」。

它做的事情是：给一段关键词，自动去 OpenAlex 拉一批论文，然后把论文清洗干净、去掉重复的、
按一套透明规则算一个初步排序分，最后存成 CSV 和 SQLite，并画出图表、写一份运行摘要。

处理流程是：

```text
关键词输入
→ OpenAlex 或本地 mock 数据
→ 字段标准化
→ DOI/标题去重
→ 缺失字段统计
→ 初步文献排序
→ CSV/SQLite 保存
→ 图表和运行摘要
```

排序公式是：

```text
preliminary_score =
0.40 × relevance_score
+ 0.30 × impact_score
+ 0.20 × recency_score
+ 0.10 × completeness_score
```

我理解这个分数**不是**「论文价值评价」，只是一个透明的初筛参考，不能说明某篇论文学术价值更高。

项目现在推进到 W6 阶段：W2 做了基础工程（OpenAlex 获取、去重、TF-IDF 排序），
W4 做了 60 条论文的人工标注评价基准，W5 在这个基准上比较了 6 种排序方法，
W6 是新一轮的研究契约和并行开发准备。

---

## 2. 我了解到的几个主要目录

| 目录 | 放什么 |
| --- | --- |
| `app/` | 命令行入口。我运行 `python -m app.xxx` 时，先执行的就是这里的文件 |
| `src/` | 真正干活的代码：获取数据、清洗、去重、打分、存库、画图 |
| `tests/` | 测试。改代码之后用来检查有没有把原来的功能弄坏 |
| `docs/` | 项目文档：当前状态、架构说明、协作规范、周报 |
| `data/` | 数据：固定样例、人工标注、评价基准 |
| `configs/` | 配置文件，比如批量运行的参数 |
| `outputs/` | 每次运行生成的产物：CSV、SQLite、图表、摘要 |
| `scripts/` | 辅助脚本，不属于主程序流程 |

我学到的一条项目规则：`app/` 里的代码只能调用 `src/` 里的代码，反过来不行。

---

## 3. 我运行过哪些命令

| 命令 | 作用 | 结果 |
| --- | --- | --- |
| 用 GitHub Desktop 克隆仓库 | 把 GitHub 上的项目复制到我电脑上 | 成功，放在 `Documents/GitHub/ai-literature-intelligence` |
| 登录 GitHub CLI | 让命令行能访问我的 GitHub 账号 | 成功 |
| `git status` | 看当前在哪个分支、工作区有没有改动 | `On branch learning/liyifan-agent-onboarding`，工作区干净 |
| `git branch` | 列出本地所有分支 | 看到 `* learning/liyifan-agent-onboarding` 和 `main` |
| `python -m app.validate_w6_bootstrap` | 检查 W6 的数据包结构对不对 | `W6 Bootstrap validation PASSED: topics=2, records=10, pool_items=13, methods=3.` |
| `python -m unittest tests.automated.test_processor -v` | 跑清洗/去重/打分这三块的自动测试 | 全部 `ok`，最后 `OK` |

我对这两条 Python 命令的理解：

- **validator（验证器）**：检查「我手上的这份数据包」结构完整不完整、字段对不对。它不评价数据好不好，只管结构。
- **测试（unittest）**：检查「代码有没有被我改坏」。它的输出格式是 `测试名字 ... ok`，全 `ok` 就是通过。

---

## 4. branch / commit / push / PR 分别是什么意思

| 概念 | 我的理解 |
| --- | --- |
| **Repository（仓库）** | 装着这个项目所有文件和历史记录的地方。分两份：**本地仓库**在我电脑上，**远端仓库**在 GitHub 上 |
| **main** | 项目的主分支。大家公认的「正式版本」都放在这里 |
| **branch（分支）** | 一条独立的修改线。我在自己的分支上改东西，不会影响 main |
| **commit** | 把我当前的修改在**本地**存成一个记录点，附一句说明 |
| **push** | 把本地的 commit **上传到 GitHub**。push 之前，GitHub 网站上什么都看不到 |
| **pull** | 把 GitHub 上的新内容**下载到本地** |
| **origin** | 本地仓库给远端仓库起的默认名字，指的就是 GitHub 上那个仓库 |
| **Issue** | 一条任务单。组长在上面写要做什么、有什么要求 |
| **Pull Request（PR）** | 一个请求：「我这条分支上做完了，请把它合并进 main」。同时也是给别人看、让别人评论的地方 |
| **merge** | 真正把分支的内容合进 main。这一步在这类练习里由组长来做，不是我做 |

一条我记住的规则：**正式协作里不要直接在 main 上改东西**，所有修改都从 main 切一条新分支，
做完走 PR 合并回去。

还有一个我原来没搞清楚的区分：**commit ≠ push**。commit 只是存在我自己的电脑上，
要 push 了才会出现在 GitHub 网站上。

---

## 5. 我让 Claude Code 帮我完成了哪些事情

- 读并讲解了 `AGENTS.md`、`docs/CURRENT_STATUS.md`、`docs/project/AI_PROJECT_ONBOARDING.md`；
- 解释了 `app/main.py` 的六步流程，以及 `app/` 和 `src/` 的分工；
- 解释了 W6 Bootstrap validator 到底在检查什么；
- 解释了自动测试输出的每一行是什么意思；
- 把 GitHub Desktop 界面汉化成了中文；
- 帮我找到并解释了 `tests/automated/test_processor.py` 里的几条测试规则
  （比如 DOI 要转小写、DOI 相同算重复、标题只是包含关系不算重复）；
- 解释了 `git status` 和 `git branch` 的输出。

我自己的操作：克隆仓库、登录 GitHub CLI、在终端亲手跑 validator、亲手跑测试、
亲手敲 `git status` 和 `git branch`。

---

## 6. 我遇到了什么不懂的问题

### （1）一开始名词太多，整体听不懂

刚开始讲项目流程的时候，我回了一句「你说的这都是啥啊，我没有基础，一点也听不懂」。

不是卡在某一个词上，是因为 Repository、main、branch、commit 这些词全是第一次见，
它们一起出现，我没法把它们串成一个整体。后来一个一个拆开讲，才慢慢接上。

### （2）打比方反而更难懂

为了让概念好懂，会用一些生活里的东西来对照讲解。但那些被人拿来对照的东西，
我本身也不熟，等于多学了一层，反而更绕。

我跟 Claude Code 说「你别给我比喻了，越比喻我越晕，你就正常解释，解释的清楚一点就行」。
改成直接讲定义和流程之后，才顺了。

### （3）分不清 validator 和 Quality Gate

当时只记住一件事：「有两个东西，都是做检测的，一个在事前，一个在事后」。

后来弄清楚了：

- **validator** 检查的是**数据包**——字段全不全、数量对不对、里面的 hash 对不对得上。
  在干活**之前**跑。
- **Quality Gate（质量门禁）** 检查的是**整个仓库的代码**——扫描所有文件，看有没有格式错误。
  在改完代码**之后**跑。

一句话：**validator 管材料，事前；Quality Gate 管成品，事后。**

### （4）`[origin/main]` 那个方括号，当时没懂

`git branch -vv` 的输出里，`main` 后面跟着 `[origin/main]`，练习分支后面什么都没有。

当时 Claude Code 只给了我命令让我复制，我没搞懂方括号是什么意思，就先把命令敲了。

后来懂了：`origin` 是远端仓库的默认名字，指 GitHub 上那个仓库；
`[origin/main]` 表示本地的 `main` 和 GitHub 上的 `main` 绑定了——绑定了之后，
`git status` 能告诉你两边差几个提交，`git pull` / `git push` 也不用写全名。

练习分支后面没有，是因为它还没 push 过，GitHub 上还没有这条分支。

### （5）SHA-256 hash 是干嘛的，不知道

`docs/CURRENT_STATUS.md` 里有一长串像 `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c...` 的东西，
当时完全不知道那是什么。

后来懂了：hash 是对一段内容算出来的 64 位字符串，**内容改动一个字，整串就完全变样**。
项目用它来证明「这份文件从冻结那天起没有人动过」。

比如 W4 那 60 条人工标注做完后，标注文件的 hash 会写进 manifest。以后任何人改了里面一个标签，
hash 立刻对不上，validator 就会拒绝。所以 `CURRENT_STATUS.md` 里那一长串就是冻结证据。

### （6）感觉自己在复制粘贴

我亲手做的：用 GitHub Desktop 克隆仓库、在浏览器里点 gh 授权、在终端跑 validator、
跑测试、敲 `git status` 和 `git branch`。

但 Git 那几条命令都是 Claude Code 给我的，我只是照着敲。这一点在第 8 节写了。

---

## 7. 我现在觉得 AI Agent 最方便的地方是什么

- **它把三份文档读完直接讲给我听**（`AGENTS.md`、`docs/CURRENT_STATUS.md`、
  `docs/project/AI_PROJECT_ONBOARDING.md`）。我自己读要读很久，还不一定抓得住重点。
- **它能把报错直接吃掉。** 今天有个 PowerShell 脚本因为中文注释的编码问题报错，
  我自己完全不知道从哪儿查起。
- **它能定位文件。** 我问「测试在哪里」，它直接给路径，不用我一个一个目录翻。
- **它一边讲一边给我能直接用的命令。**
- **它记得住上下文。** 我不用每次都重新解释我是谁、在做什么。
- **它能把难的东西拆成小步。** 我卡住了就让它再拆一层。

如果只能留一个，我留第一个：**读文档，讲给我听。**

---

## 8. 我还有哪些不理解的地方

**Git 的命令我还不能独立敲出来。** 今天这几条是 Claude Code 给我的，
下次没有它，我大概还得再问一遍。

这一点我在练习中间就问过：是不是走完这一遍我以后还是不会？
现在我知道两件事：

1. 该背下来的是**少数几条命令**——`git status`、`git branch`、`git add`、`git commit`、
   `git push`，加上「分支 → commit → push → PR」这一个流程，这些是可以练熟的；
2. 项目里的算法和科研内容（BM25、SPECTER2、RRF 怎么算的、W6 contract 有哪些字段）
   不需要背，遇到不会的直接问 Claude Code 就行——组长在 Issue 第二十节里写的就是这个意思。

所以我现在遇到不懂的，会直接问 Claude Code，不再自己硬扛。
