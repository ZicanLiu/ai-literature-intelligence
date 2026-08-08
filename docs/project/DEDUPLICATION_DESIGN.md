# 两级去重设计文档

**版本:** v0.2.0-w2  
**模块:** `src/deduplication.py`  
**配套 CLI:** `app/review_duplicates.py`  
**依赖:** `src/utils.py`（value_is_missing）, Python 标准库 `difflib`

---

## 1. 设计目标

在保留旧 baseline 严格去重（`src/processor.py` 的 `remove_duplicates`）的前提下，新增两级去重：

- **Level 1 — 确定重复（Exact）**：可自动合并，无需人工干预
- **Level 2 — 疑似重复（Suspected）**：进入人工复核队列，**绝不自动删除**

两级结果严格分离。

---

## 2. 数据结构

### 2.1 输入要求

每条论文必须包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `keyword` | str | 检索关键词，用于来源追踪 |
| `run_id` | str | 查询批次标识 |
| `openalex_id` | str | OpenAlex 作品 ID（可为空字符串） |
| `doi` | str | DOI（可为空字符串） |
| `title` | str | 论文标题 |
| `authors` | str | 分号分隔的作者名 |
| `publication_year` | int/str | 出版年 |

### 2.2 确定重复记录结构

```
{
    "rule": "same_openalex_id | same_doi | same_title_no_id",
    "kept_openalex_id": str,
    "kept_title": str,
    "merged_openalex_id": str,
    "merged_title": str,
    "source_keyword": [str, str],
    "source_run_id": [str, str],
    "merged_at": str (ISO 8601)
}
```

### 2.3 疑似重复记录结构

```
{
    "pair_id": "SP-xxxxxxxx",
    "left_id": str, "right_id": str,
    "left_title": str, "right_title": str,
    "title_similarity": float (0-1),
    "author_overlap": float (0-1),
    "year_difference": int,
    "doi_relation": str,
    "suspected_reason": str,
    "recommended_action": "manual_review",
    "review_status": "pending",
    "reviewer_note": "",
    "left_keyword": str, "right_keyword": str,
    "left_run_id": str, "right_run_id": str,
    "created_at": str (ISO 8601)
}
```

---

## 3. Level 1：确定重复

### 3.1 三条规则（优先级递减）

| 优先级 | 规则 | 判定条件 | 自动操作 |
|:------:|------|---------|---------|
| 1 | `same_openalex_id` | `openalex_id` 完全相同 | 合并为一条 |
| 2 | `same_doi` | 非空 DOI 经 `normalize_doi()` 标准化后相同 | 合并为一条 |
| 3 | `same_title_no_id` | `openalex_id` 缺失时，标准化标题完全相同 | 合并为一条 |

### 3.2 DOI 标准化

`normalize_doi()` 处理以下差异：
- 大小写不同：`10.1234/AbC` → `10.1234/abc`
- 前缀差异：`https://doi.org/10.1234/test` → `10.1234/test`
- `http://` vs `https://` vs `doi:` vs 无前缀

### 3.3 标题标准化（用于精确匹配）

`normalize_title()` 处理：
- 大小写统一为小写
- 去除 HTML 标签（`<i>`、`<scp>` 等）
- 去除 arXiv ID（`[arXiv:2301.12345v2]`）
- 所有标点替换为空格
- 连续空白合并为单个空格

### 3.4 执行逻辑

遍历论文列表，每篇论文依次检查三条规则。当一条规则命中时，该论文被标记为确定重复（相对于最先遇到的那条），后续规则不再检查。未被命中的论文进入 kept_papers 供 Level 2 使用。

---

## 4. Level 2：疑似重复

### 4.1 设计原则

- **可解释性优先**：每条疑似记录附带清晰的原因标签
- **保守策略**：宁可漏判（false negative）也不误判（false positive），因为疑似对仅进入人工队列
- **可追溯**：保留双方的关键词、run_id、原始标题

### 4.2 Blocking 策略

为减少 O(n²) 比较，采用两层 blocking：

1. **年份窗口**：仅比较 `|year_a - year_b| ≤ 2` 的论文对
2. **DOI 排除**：若两侧均有非空 DOI 且标准化后不同，直接排除（强证据表明是不同论文）

### 4.3 相似度信号

#### 主信号（标题）

1. **Jaccard 相似度**：对标题做 `normalize_title()` 后拆分为词项（长度 ≥ 2），计算 Jaccard 系数。阈值 ≥ 0.50。
2. **SequenceMatcher**：对两个标准化标题做 `difflib.SequenceMatcher.ratio()`。阈值 ≥ 0.65。

满足任一主信号 + 辅助确认 → 进入疑似队列。

#### 辅助确认信号

3. **作者姓氏重合**：从 `authors` 字段提取姓氏（最后一个词），计算 Jaccard 重合度。阈值 ≥ 0.3。
   - 例外：若标题 Jaccard ≥ 0.80，即使作者重合度低也进入队列（可能同一作者用不同署名）

4. **年份差异**：`|year_a - year_b|` ≤ 2（已在 blocking 中应用）

5. **DOI 关系分类**：
   - `both_missing`：双方都无 DOI
   - `one_missing`：一方有 DOI 一方无
   - `one_arxiv_one_publisher`：一方 arXiv DOI 一方正式出版 DOI（预印本-正式版关系）
   - `both_present_different`：两侧 DOI 不同（已被 blocking 排除）
   - `both_present_same`：两侧 DOI 相同（已在 Level 1 处理）

### 4.4 原因标签格式

`_determine_reason()` 从四个维度拼接可读原因：

```
title_very_high_similarity|author_high_overlap|year_close
title_moderate_similarity|author_low_overlap|year_nearby
title_high_similarity|author_moderate_overlap|year_close|preprint_publisher_pair
```

---

## 5. pair_id 生成

基于双方 `openalex_id` 的 MD5 哈希前 8 位，格式为 `SP-xxxxxxxx`，保证确定性（同一对始终产生相同 ID）。

---

## 6. 与旧 baseline 的关系

| 方面 | 旧 baseline (`processor.py`) | 新增 (`deduplication.py`) |
|------|----------------------------|--------------------------|
| 位置 | `remove_duplicates()` | `find_exact_duplicates()` + `find_suspected_duplicates()` |
| 精确规则 | DOI + 标题完全相同 | OpenAlex ID + DOI + 标题完全相同 |
| 模糊匹配 | 无 | Jaccard + SequenceMatcher + 作者 |
| 疑似队列 | 无 | 有（人工复核） |
| 来源追踪 | 部分（kept_openalex_id） | 完整（keyword + run_id + 双向） |

---

## 7. CLI 审核工具

`app/review_duplicates.py` 提供交互式和列表式两种模式：

```powershell
# 交互式逐条审核
python -m app.review_duplicates

# 列出所有待审核
python -m app.review_duplicates --list

# 查看统计
python -m app.review_duplicates --stats
```

交互模式下支持的操作：
- `y`：确认重复 → `review_status=confirmed`, `recommended_action=merge`
- `n`：不是重复 → `review_status=distinct`, `recommended_action=keep_separate`
- `s`：跳过当前
- `q`：退出审核

---

## 8. 潜在误判类型

| 类型 | 场景 | 可能性 | 缓解 |
|------|------|:------:|------|
| **False Positive**（相似但不同论文） | 同一课题组的多篇系列论文标题相似 | 中 | 人工审核队列 |
| **False Negative**（未检测到的重复） | 标题差异大但内容相同（重组段落） | 高 | 超出当前轻量方法的范围 |
| **False Negative** | 年份差异 > 2（arXiv 预印本 vs 多年后正式出版） | 中 | 当前 blocking 策略的已知限制 |
| **False Positive** | 标题高度重叠但学科不同 | 低 | 当前数据集同领域为主 |
| **DOI 差异导致的漏判** | 同一论文有 arXiv DOI 和 publisher DOI | 中 | 已在 Level 2 特别标注 `preprint_publisher_pair` |
