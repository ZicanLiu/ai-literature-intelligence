# 团队 Git 协作说明

> 适用仓库：`ZicanLiu/ai-literature-intelligence`  
> 适用工具：GitHub、VS Code、Git  
> 本文只说明团队代码协作规范，不包含 Python 环境配置、依赖安装或项目运行方法。

---

# 一、协作原则

本项目统一采用：

```text
Issue → 最新 main → 任务分支 → Commit → Push → Pull Request → 审核 → 合并
```

所有成员都应遵守以下规则：

1. `main` 只保存经过审核的稳定版本。
2. 禁止直接在 `main` 上提交任务成果。
3. 每个任务单独创建一个短期分支。
4. 一个分支只处理一个明确任务。
5. 开始任务前，必须先同步最新 `main`。
6. 完成修改后，通过 Pull Request 请求审核与合并。
7. `.env`、API Key、虚拟环境、缓存和无关运行结果不得提交。
8. 不确定的冲突或高风险 Git 操作，先联系组长确认。

## 1. 仓库、main 和任务分支

### GitHub 仓库

仓库是整个项目的统一存放位置，包含：

- 项目代码与文档；
- Git 提交历史；
- 分支；
- Issues；
- Pull Requests；
- 审核与讨论记录。

本项目仓库为：

```text
ZicanLiu/ai-literature-intelligence
```

### main 分支

`main` 是项目正式主分支，应保持稳定、可运行、可审核。

错误流程：

```text
main
→ 直接修改
→ Commit
→ Push
```

正确流程：

```text
main
→ Pull 最新代码
→ 创建任务分支
→ 修改
→ Commit
→ Push
→ Pull Request
```

### 任务分支

任务分支是从最新 `main` 创建的独立工作空间。

推荐命名：

| 类型 | 用途 | 示例 |
| --- | --- | --- |
| `feat/` | 新功能 | `feat/openalex-filter` |
| `fix/` | 修复问题 | `fix/empty-response` |
| `docs/` | 文档修改 | `docs/team-git-guide` |
| `test/` | 测试任务 | `test/cli-cases` |
| `analysis/` | 分析任务 | `analysis/openalex-quality` |
| `data/` | 数据整理 | `data/mock-cleanup` |

命名要求：

- 使用英文小写；
- 单词之间用短横线 `-`；
- 不使用空格；
- 不使用 `test1`、`new`、`mybranch` 等含义不明确的名称。

---

# 二、标准协作流程

## 1. 查看并确认 Issue

Issue 用于明确：

- 要解决什么问题；
- 由谁负责；
- 任务边界是什么；
- 需要提交哪些文件；
- 如何判断任务完成；
- 是否有数据、安全或格式要求。

开始前应确认：

- Issue 是否分配给自己；
- 是否需要修改公共文件；
- 是否可能与其他成员产生重叠；
- 是否有截止时间；
- 是否有验收标准。

任务描述不清楚时，应先在 Issue、群聊或私聊中确认，不要自行扩大任务范围。

---

## 2. 同步最新 main

创建任务分支之前，必须先同步远程最新 `main`。

> 命令中 `#` 后面的文字是说明性注释，复制到终端也不会执行；手动输入时可以省略注释。

统一使用终端命令：

```bash
git switch main  # 切换到本地 main 分支
git pull origin main  # 从远程 origin 拉取最新 main
```

确认当前分支：

```bash
git branch --show-current  # 显示当前所在分支
```

应输出：

```text
main
```

如果 `git pull origin main` 成功，常见提示包括：

```text
Already up to date.
```

或者显示本次拉取更新了哪些文件。

先同步 `main` 的原因：

- 组长可能已经更新代码；
- 其他成员的 PR 可能已经合并；
- 从旧版本创建分支会增加冲突；
- 新任务必须基于当前正式版本。

> 为避免不同 VS Code 版本和语言界面导致菜单位置不一致，本项目统一使用终端命令完成 Pull。

---

## 3. 创建任务分支

### VS Code 图形界面

1. 确认当前位于 `main`。
2. 点击左下角的 `main`。
3. 选择：

```text
Create new branch...
```

4. 输入规范分支名，例如：

```text
docs/team-git-guide
```

5. 创建后确认左下角显示新分支名称。

### 终端备用命令

```bash
git switch -c docs/team-git-guide  # 从当前分支创建并切换到文档任务分支
```

确认：

```bash
git branch --show-current  # 显示当前所在分支
```

也可以执行：

```bash
git branch  # 列出本地分支，带 * 的是当前分支
```

当前分支前会有 `*`：

```text
* docs/team-git-guide
  main
```

如果仍显示 `main`，不要提交。

---

## 4. 在任务分支中完成修改

修改时应遵守：

1. 只修改完成任务所必需的文件；
2. 不顺手重构无关代码；
3. 不修改其他成员负责的内容，除非任务明确要求；
4. 不把格式化工具产生的大量无关修改带入 PR；
5. 不删除自己不理解的代码或文档；
6. 不提交临时测试文件；
7. 不提交无关运行输出。

建议随时查看：

```bash
git status --short  # 用简洁格式查看文件状态
```

常见状态：

| 标记 | 含义 |
| --- | --- |
| `??` | 新文件，尚未暂存 |
| ` M` | 文件已修改，尚未暂存 |
| `A ` | 新文件，已经暂存 |
| `M ` | 文件已修改，已经暂存 |
| `D ` | 文件已删除，已经暂存 |

---

## 5. 检查、暂存并 Commit

### 查看修改

VS Code 中，打开“源代码管理”，点击文件即可查看差异：

- 绿色表示新增；
- 红色表示删除；
- 修改通常表现为旧内容删除、新内容新增。

终端命令：

```bash
git diff  # 查看尚未暂存的具体修改
```

只查看某个文件：

```bash
git diff -- 文件路径  # 只查看指定文件尚未暂存的修改
```

查看修改规模：

```bash
git diff --stat  # 只查看各文件的修改规模
```

### 暂存文件

VS Code 中，在“Changes”里点击单个文件右侧的 `+`。

对应终端命令：

```bash
git add 文件路径  # 把指定文件加入暂存区
```

例如：

```bash
git add docs/collaboration/TEAM_GIT_GUIDE.md  # 只暂存团队 Git 协作说明
```

不建议默认使用：

```bash
git add .  # 暂存当前目录全部修改；本项目不建议直接使用
```

因为它可能把无关文件、临时结果或敏感配置一起加入提交。

### 检查暂存区

查看即将提交的内容：

```bash
git diff --cached  # 查看已经暂存、即将进入 Commit 的内容
```

只查看修改规模：

```bash
git diff --cached --stat  # 只查看暂存区内各文件的修改规模
```

只查看某个文件：

```bash
git diff --cached -- docs/collaboration/TEAM_GIT_GUIDE.md  # 只查看该文档已暂存的修改
```

如果进入分页界面，按：

```text
q
```

退出。

发现不该提交的文件时，取消暂存：

```bash
git restore --staged 文件路径  # 取消暂存指定文件，但保留本地修改
```

### 创建 Commit

VS Code 中，在提交说明输入框填写 Commit message，再点击“Commit”。

终端命令：

```bash
git commit -m "docs: add team Git collaboration guide"  # 创建一次文档类本地提交
```

推荐格式：

```text
类型: 简要说明
```

常用类型：

| 类型 | 说明 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 修复 |
| `docs` | 文档修改 |
| `test` | 测试 |
| `analysis` | 分析内容 |
| `data` | 数据整理 |
| `refactor` | 不改变功能的重构 |
| `chore` | 配置或维护 |

示例：

```text
feat: add OpenAlex result filter
fix: handle empty API response
docs: add team Git collaboration guide
test: add mock CLI cases
```

避免使用：

```text
update
修改
改一下
test
new file
```

---

## 6. Push 任务分支

Commit 只保存在本地，Push 才会把提交上传到 GitHub。

统一使用终端命令。

第一次上传当前任务分支：

```bash
git push -u origin 分支名  # 首次推送分支，并建立远程跟踪关系
```

例如：

```bash
git push -u origin docs/team-git-guide  # 首次把该任务分支推送到 GitHub
```

其中：

- `origin` 表示 GitHub 远程仓库；
- `docs/team-git-guide` 表示当前任务分支；
- `-u` 用于建立本地分支与远程分支的跟踪关系。

第一次 Push 成功后，后续只需：

```bash
git push  # 把当前分支的新 Commit 推送到已关联的远程分支
```

Push 前建议确认当前分支：

```bash
git branch --show-current  # 显示当前所在分支
```

确保输出不是：

```text
main
```

> 为避免不同 VS Code 版本和语言界面导致按钮名称不一致，本项目统一使用终端命令完成 Push。

---

## 7. 创建 Pull Request

Pull Request 的作用是请求审核并把任务分支合并到 `main`。

### GitHub 网页操作

1. 打开仓库页面。
2. Push 后通常会出现：

```text
Compare & pull request
```

3. 点击进入创建页面。
4. 确认：

```text
base: main
compare: 自己的任务分支
```

例如：

```text
base: main
compare: docs/team-git-guide
```

5. 填写标题和说明。
6. 打开 `Files changed` 检查全部修改。
7. 确认没有无关内容后，点击：

```text
Create pull request
```

正确方向：

```text
任务分支 → main
```

不要把 `base` 和 `compare` 选反。

### PR 内容要求

PR 应写清楚：

- 修改目的；
- 修改内容；
- 修改文件；
- 实际验证方法与结果；
- 是否涉及数据；
- 是否涉及敏感配置；
- 已知限制；
- 需要审核者重点确认的内容。

推荐模板：

```markdown
## 修改目的

说明本次修改要解决的问题。

## 修改内容

- 修改内容 1
- 修改内容 2

## 修改文件

- `path/to/file1`
- `path/to/file2`

## 验证情况

- [x] 已完成相关本地检查
- [x] 已运行必要测试

验证命令：

```bash
# 在这里填写实际执行过的验证命令
```

## 数据与安全

- 未提交 `.env`
- 未提交 API Key
- 未提交虚拟环境或缓存
- 未提交无关运行结果
- 数据来源：无新增数据 / 填写实际来源

## 已知限制

没有则写“无”。

## 需要审核者确认

没有则写“无”。

Closes #Issue编号
```

没有执行的测试不要勾选，也不要夸大验证结果。

---

## 8. 审核、修改与合并

PR 创建后，组长或审核者会检查：

- 是否符合 Issue；
- 是否只包含本任务内容；
- 是否存在明显错误；
- 是否影响其他模块；
- 是否完成必要测试；
- 是否包含敏感信息；
- 是否可以安全合并。

审核结果通常有：

- `Approved`：可以合并；
- `Comment`：提出建议；
- `Request changes`：需要修改后再审核。

收到修改意见后：

1. 不要新建另一个 PR；
2. 不要直接修改 `main`；
3. 继续在原任务分支修改；
4. Commit 并 Push；
5. 原 PR 会自动更新。

终端流程：

```bash
git add 指定文件  # 只暂存按审核意见修改的相关文件
git commit -m "fix: address review comments"  # 提交对审核意见的修改
git push  # 把当前分支的新 Commit 推送到已关联的远程分支
```

一般由组长或指定审核者完成合并，成员不要自行合并，除非团队明确授权。

---

## 9. 合并后的清理

PR 合并后，本地同步：

```bash
git switch main  # 切换到本地 main 分支
git pull origin main  # 从远程 origin 拉取最新 main
```

删除本地任务分支：

```bash
git branch -d 分支名  # 安全删除已经合并的本地分支
```

如果远程分支未自动删除：

```bash
git push origin --delete 分支名  # 删除 GitHub 上已经完成的远程分支
```

下一次任务重新从最新 `main` 创建新分支，不继续使用已合并的旧分支。

---

# 三、安全与提交边界

## 1. 不得提交的内容

以下内容禁止提交：

- `.env`；
- OpenAlex API Key；
- 其他 API Key、密码和 Token；
- 带密钥的请求地址；
- `.venv/`、`venv/`；
- `__pycache__/`、`*.pyc`；
- 个人手机号、学号等敏感信息；
- 未经授权的 PDF；
- 无法说明来源的数据；
- 无关临时运行结果。

常见不应提交的路径：

```text
.env
.venv/
venv/
__pycache__/
*.pyc
.vscode/
.idea/
*.log
outputs/experiments/
```

除非 Issue 明确要求长期保存某个基线或实验结果，否则默认不要提交运行输出。

---

## 2. `.env` 与 `.env.example`

`.env` 用于保存本地真实配置，只能保留在个人电脑中。

`.env.example` 可以提交，但只能写变量名和示例值，例如：

```text
OPENALEX_API_KEY=your_openalex_api_key_here
```

不得填入真实 Key。

提交前检查：

```bash
git status --short  # 用简洁格式查看文件状态
git check-ignore -v .env  # 显示是哪条 .gitignore 规则忽略了 .env
git ls-files .env  # 检查 .env 是否已被 Git 跟踪；正常应无输出
```

正确结果：

- `git status --short` 中没有 `.env`；
- `git check-ignore -v .env` 显示 `.gitignore` 规则；
- `git ls-files .env` 没有输出。

如果 `.env` 被暂存：

```bash
git restore --staged .env  # 把误暂存的 .env 移出暂存区
```

如果已经被 Git 跟踪：

```bash
git rm --cached .env  # 停止跟踪 .env，但保留本地文件
```

如果真实 Key 曾经 Push 到 GitHub：

1. 立即废弃旧 Key；
2. 生成新 Key；
3. 联系组长处理仓库历史；
4. 不能只删除当前文件就认为已经安全。

---

# 四、协作中的异常情况

## 1. 在 main 上修改但还没有 Commit

先不要提交，立即创建正确任务分支：

```bash
git switch -c 类型/任务名称  # 创建并切换到规范命名的任务分支
```

未提交修改通常会随之进入新分支。

然后确认：

```bash
git branch --show-current  # 显示当前所在分支
git status  # 查看当前分支及工作区详细状态
```

---

## 2. 已经在 main 上 Commit，但还没有 Push

不要 Push。

先创建任务分支保存当前 Commit：

```bash
git switch -c 类型/任务名称  # 创建并切换到规范命名的任务分支
```

然后联系组长确认如何恢复本地 `main`。

不熟悉 Git 时，不要自行执行：

```bash
git reset --hard  # 高风险：丢弃已跟踪文件的本地修改并重置提交位置
```

---

## 3. 任务期间 main 又有更新

如果任务持续时间较长，可以同步最新 `main`。

先更新本地 `main`：

```bash
git switch main  # 切换到本地 main 分支
git pull origin main  # 从远程 origin 拉取最新 main
```

返回任务分支：

```bash
git switch 自己的任务分支  # 切回当前正在开发的任务分支
```

合并最新 `main`：

```bash
git merge main  # 把本地最新 main 合并到当前任务分支
```

如果团队统一使用 rebase，则按组长要求执行：

```bash
git rebase main  # 高风险：把当前分支提交重新排列到最新 main 之后
```

没有统一要求时，不要随意混用 merge 和 rebase。

---

## 4. 出现冲突

冲突通常发生在：

- 两个人修改了同一文件的相同行；
- 分支长期没有同步 `main`；
- 多人同时修改公共配置或文档；
- 一个人删除文件，另一个人修改同一文件。

执行：

```bash
git status  # 查看当前分支及工作区详细状态
```

查看冲突文件。

VS Code 会显示：

```text
Accept Current Change
Accept Incoming Change
Accept Both Changes
Compare Changes
```

不要不看内容直接选择 `Accept Both Changes`。

正确处理方式：

1. 阅读两边修改；
2. 判断最终应保留什么；
3. 手动整理正确版本；
4. 删除冲突标记；
5. 保存文件；
6. 重新运行相关测试；
7. 暂存冲突文件；
8. 完成合并或 rebase。

冲突标记通常是：

```text
<<<<<<< HEAD
当前分支内容
=======
另一分支内容
>>>>>>> main
```

这些标记必须全部删除。

如果无法判断应保留哪一边，联系对应成员或组长，不要自行猜测。

---

## 5. Push 被拒绝

常见提示：

```text
rejected
non-fast-forward
```

如果只是自己的任务分支远程有新提交，可以尝试：

```bash
git pull --rebase  # 拉取远程提交，并在其后重新应用本地提交
git push  # 把当前分支的新 Commit 推送到已关联的远程分支
```

如果不清楚远程修改来源，不要强制 Push。

禁止随意执行：

```bash
git push --force  # 极高风险：强制覆盖远程分支历史，未经确认不得使用
```

如确实需要强制更新，必须先与组长确认，并优先使用：

```bash
git push --force-with-lease  # 较安全的强制推送；远程已变化时会拒绝覆盖
```

---

## 6. PR 中出现大量无关修改

常见原因：

- 分支不是从最新 `main` 创建；
- 自动格式化修改了大量文件；
- 改变了换行符；
- 误执行 `git add .`；
- 在旧任务分支中继续做新任务。

处理方法：

1. 在 `Files changed` 中检查；
2. 删除或恢复无关修改；
3. 必要时从最新 `main` 重新创建干净分支；
4. 不要让审核者从大量无关差异中寻找真正修改。

---

## 7. 高风险命令

未与组长确认时，不要执行：

```bash
git push --force  # 极高风险：强制覆盖远程分支历史，未经确认不得使用
git reset --hard  # 高风险：丢弃已跟踪文件的本地修改并重置提交位置
git clean -fd  # 高风险：永久删除未跟踪的文件和目录
git rebase -i  # 高风险：交互式改写提交历史
git filter-branch  # 高风险：批量改写整个仓库历史，通常不应使用
```

这些命令可能覆盖历史、永久删除文件或影响其他成员。

不确定命令作用时，先询问再执行。

---

# 五、检查清单与命令速查

## 1. Commit 前检查

```bash
git branch --show-current  # 显示当前所在分支
git status --short  # 用简洁格式查看文件状态
git diff  # 查看尚未暂存的具体修改
git diff --cached  # 查看已经暂存、即将进入 Commit 的内容
git check-ignore -v .env  # 显示是哪条 .gitignore 规则忽略了 .env
git ls-files .env  # 检查 .env 是否已被 Git 跟踪；正常应无输出
```

确认：

- [ ] 当前分支不是 `main`
- [ ] 分支对应一个明确任务
- [ ] 只修改本任务需要的文件
- [ ] 已检查尚未暂存的修改
- [ ] 已检查即将提交的修改
- [ ] 暂存区没有无关文件
- [ ] 没有 `.env`
- [ ] 没有 API Key
- [ ] 没有虚拟环境和缓存
- [ ] 已完成必要验证

---

## 2. Pull Request 前检查

确认：

- [ ] 分支已经 Push 到 GitHub
- [ ] `base` 是 `main`
- [ ] `compare` 是任务分支
- [ ] PR 标题明确
- [ ] PR 写明修改目的
- [ ] PR 写明修改文件
- [ ] PR 写明验证方法和结果
- [ ] PR 写明数据来源
- [ ] PR 写明安全检查
- [ ] PR 写明已知限制
- [ ] `Files changed` 没有无关内容
- [ ] 没有未解决冲突

---

## 3. 常用操作与命令对照

| 操作 | 推荐方式 |
| --- | --- |
| 克隆仓库 | `git clone 仓库地址` |
| 切换分支 | `git switch 分支名` |
| 创建分支 | `git switch -c 分支名` |
| 拉取最新 main | `git switch main` 后执行 `git pull origin main` |
| 查看修改 | `git status`、`git diff` |
| 暂存指定文件 | `git add 文件路径` |
| 取消暂存 | `git restore --staged 文件路径` |
| Commit | `git commit -m "说明"` |
| 第一次 Push 分支 | `git push -u origin 分支名` |
| 后续 Push | `git push` |
| 查看提交历史 | `git log --oneline` |
| 创建 PR | 在 GitHub 网页操作 |

---

## 4. 一次标准任务的命令顺序

```bash
# 同步 main
git switch main  # 切换到本地 main 分支
git pull origin main  # 从远程 origin 拉取最新 main

# 创建任务分支
git switch -c docs/team-git-guide  # 从当前分支创建并切换到文档任务分支

# 完成任务后查看修改
git status --short  # 用简洁格式查看文件状态
git diff  # 查看尚未暂存的具体修改

# 精确暂存
git add docs/collaboration/TEAM_GIT_GUIDE.md  # 只暂存团队 Git 协作说明

# 检查即将提交的内容
git diff --cached  # 查看已经暂存、即将进入 Commit 的内容
git status --short  # 用简洁格式查看文件状态

# 安全检查
git check-ignore -v .env  # 显示是哪条 .gitignore 规则忽略了 .env
git ls-files .env  # 检查 .env 是否已被 Git 跟踪；正常应无输出

# Commit
git commit -m "docs: add team Git collaboration guide"  # 创建一次文档类本地提交

# Push
git push -u origin docs/team-git-guide  # 首次把该任务分支推送到 GitHub
```

然后在 GitHub 创建 Pull Request：

```text
base: main
compare: docs/team-git-guide
```

---

# 六、总结

团队 Git 协作可以概括为五点：

1. **从最新 `main` 开始。**
2. **每个任务使用独立分支。**
3. **提交前只暂存本任务文件。**
4. **通过 Pull Request 审核后再进入 `main`。**
5. **任何敏感配置和无关文件都不得提交。**
