# 团队 GitHub 协作指南

这份指南写给第一次参与团队 GitHub 协作的同学。平时可以使用 VS Code 图形界面；遇到界面状态不清楚时，再用 PowerShell 命令确认。

## 1. 基本原则

- `main` 是稳定主分支，不直接在 `main` 上开发或推送。
- 每个 Issue 对应一个短期任务分支，一个分支只处理一个明确任务。
- 完成后通过 Pull Request（PR）合并，由组长审核，不由成员自行合并。
- PR 合并后删除已结束的任务分支。
- 开始下一个任务时，重新从最新 `main` 创建新分支。
- 提交前先看清修改内容，只提交与当前任务有关的文件。

## 2. 第一次克隆仓库

### VS Code 图形界面

1. 按 `Ctrl + Shift + P` 打开命令面板。
2. 输入并选择 `Git: Clone`。
3. 粘贴仓库地址。
4. 选择准备存放项目的本地目录。
5. 克隆结束后点击“打开”进入项目。

如果 VS Code 询问是否信任仓库，请先核对仓库地址，确认是本项目后再继续。

### PowerShell 备用命令

```powershell
git clone <仓库地址>
cd <项目目录>
```

克隆完成后可以运行 `git status`，确认 Git 已正确识别仓库。

## 3. 开始任务前同步 main

### VS Code

1. 点击左下角当前分支名。
2. 选择 `main`。
3. 打开 Source Control（源代码管理）。
4. 点击 `...`，选择 `Pull`。

### PowerShell

```powershell
git switch main
git pull --ff-only origin main
```

先同步是为了让新分支包含其他人已经合并的修改，减少后面重复修改和冲突。若 `pull` 提示存在未提交修改，不要强行覆盖，先按第 12 节处理。

## 4. 创建任务分支

分支名以 Issue 中规定的名称为准。

### VS Code

1. 点击左下角的 `main`。
2. 选择 `Create new branch`。
3. 输入 Issue 规定的分支名。
4. 创建后确认左下角不再显示 `main`。

### PowerShell

```powershell
git switch -c <Issue中规定的分支名>
git branch --show-current
```

例如，文档任务可以使用 `docs/任务名称`，测试任务可以使用 `test/任务名称`。

## 5. 查看和提交修改

### VS Code

1. 打开 Source Control。
2. 逐个查看 `Changes` 中的文件和差异。
3. 只对本任务文件逐个点击 `+` 暂存。
4. 输入简短、明确的提交说明。
5. 点击 `Commit`。

### PowerShell

```powershell
git status
git diff
git add <具体文件>
git diff --cached
git commit -m "类型: 简要说明"
```

例如：

```powershell
git add docs/TEAM_GIT_GUIDE.md
git commit -m "docs: add team Git guide"
```

不建议无脑使用：

```powershell
git add .
```

它可能把 `.env`、运行输出或与任务无关的修改一起暂存。提交前应使用 `git diff --cached` 再检查一次。

## 6. 推送任务分支

### VS Code

- 第一次推送点击 `Publish Branch`。
- 后续提交可以使用 `Sync Changes`。

### PowerShell

```powershell
git push -u origin HEAD
```

Push 只表示任务分支已上传到 GitHub，不代表已经创建 PR，也不代表已经通过审核。

## 7. 创建 Pull Request

1. 打开 GitHub 上的项目仓库。
2. 点击 `Compare & pull request`；如果没有出现该按钮，可进入 `Pull requests` 页面后点击 `New pull request`。
3. `base` 选择 `main`。
4. `compare` 选择自己的任务分支。
5. 检查变更文件，填写完成内容和验证结果。
6. 创建 PR 后等待组长审核，不要自行合并。

可以使用下面的 PR 模板：

```markdown
## 完成内容

## 提交文件

## 验证方式

## 仍存在的问题

Closes #Issue编号
```

## 8. 收到修改意见后怎么办

- 不需要重新创建分支。
- 不需要重新创建 PR。
- 回到原任务分支继续修改。
- 修改后再次 Commit 和 Push。
- 原 PR 会自动显示新增提交和最新差异。

```powershell
git switch <原任务分支>
git status
git add <本次修改的具体文件>
git commit -m "docs: address review feedback"
git push
```

## 9. PR 合并后的操作

### PowerShell

```powershell
git switch main
git pull --ff-only origin main
git branch -d <已合并任务分支>
git fetch --prune
```

`git branch -d` 只删除本地已合并分支；远程分支通常在 GitHub 合并 PR 时删除，`git fetch --prune` 用于清理本地保存的过期远程分支引用。

### VS Code

1. 点击左下角分支名并切换到 `main`。
2. 在 Source Control 的 `...` 菜单中执行 `Pull`。
3. 按 `Ctrl + Shift + P`，运行 `Git: Delete Branch...`，选择已经合并的本地任务分支。
4. 如需清理远程引用，可在 `...` 菜单中使用 Fetch/Prune；若界面没有该选项，运行上面的 `git fetch --prune`。

## 10. 已经创建分支后，main 又更新怎么办

先确认任务分支中的修改已经保存，工作区状态清楚，再执行：

```powershell
git switch main
git pull --ff-only origin main
git switch <自己的任务分支>
git merge main
```

如果出现冲突，不要盲目删除文件或选择“全部接受”。先阅读冲突标记，保留双方仍需要的内容；不确定时截图并在群里询问组长。解决后再逐个暂存冲突文件并提交合并结果。

## 11. 绝对不能提交的内容

- `.env`
- API Key
- 密码、Token 或带密钥的请求 URL
- `.venv/`、`venv/` 等虚拟环境
- `__pycache__/`、`*.pyc`
- 缓存、日志和临时文件
- 手机号、学号等个人敏感信息
- 申请书原件
- 未经授权的论文全文或 PDF
- 与任务无关的大体积运行输出

发现疑似密钥时不要复制到 Issue、聊天或 PR 中，应先停止暂存并通知组长。

## 12. 常见问题

### Push 后为什么看不到 PR？

Push 只上传分支，不会自动创建 PR。进入 GitHub 仓库的 `Pull requests` 页面，选择 `New pull request`，并确认 `base` 是 `main`、`compare` 是自己的分支。

### 为什么不能直接 Push main？

`main` 需要始终保持可运行。通过任务分支和 PR，其他人可以先检查差异和验证结果，避免未经审核的修改影响全组。

### VS Code 一直卡在 Commit 怎么办？

先确认已经输入提交说明、需要提交的文件已经暂存，并检查 VS Code 是否打开了等待保存或关闭的 Git 编辑器窗口。仍不确定时，用 PowerShell 执行 `git status` 查看真实状态，不要连续点击 Commit。

### 分支名创建错了怎么办？

如果当前分支还没有推送，可以直接重命名：

```powershell
git branch -m <正确分支名>
git branch --show-current
```

如果错误分支已经推送，不要自行强制删除远程分支，先告知组长并确认处理方式。

### Pull 时出现未提交修改怎么办？

先停止 Pull，运行：

```powershell
git status
git diff
```

确认这些修改属于哪个任务。应提交的内容先在原任务分支提交；不应提交或无法判断的内容不要删除、不要强制覆盖，及时询问组长。

### 如何确认当前在哪个分支？

```powershell
git branch --show-current
```

VS Code 左下角也会显示当前分支名。开始修改前应同时确认它不是 `main`。

### 如何确认 `.env` 被忽略？

```powershell
git check-ignore -v .env
git status --short
```

第一条命令应显示命中的 `.gitignore` 规则，第二条命令中不应出现 `.env`。不要为了测试而在命令、截图或文档里写入真实 Key。

## 13. 一次完整流程示例

下面是一组适合 Windows PowerShell 的完整命令：

```powershell
git switch main
git pull --ff-only origin main
git switch -c docs/example-task
git status
git add docs/example.md
git diff --cached
git commit -m "docs: add example document"
git push -u origin HEAD
```

命令执行完成后，仍需进入 GitHub 创建 PR，填写验证方式并等待组长审核。
