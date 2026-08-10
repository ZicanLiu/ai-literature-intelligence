# W4 Query Relevance 标注指南

本指南用于 W4 Pilot Annotation。每位成员只判断论文与给定 research question 的相关性，
不评价论文的绝对科学质量、创新水平或学术价值。

## 1. 核心判断原则

判断论文的**核心研究任务**是否与 research question 对应，不是统计标题或摘要出现了几个
关键词。必须结合研究对象、输入数据、核心方法和主要输出判断。

统一原则：

1. 只标 Query Relevance，不标绝对论文质量；
2. 双标必须独立，不查看另一标注者答案；
3. Title + Abstract 足够时不必查全文；
4. 有歧义时查看可靠外部页面；
5. 仍不确定时再看全文关键位置；
6. 无法可靠判断时允许 `?`，禁止硬猜；
7. AI 可以辅助理解，但最终 label 由成员本人确认；
8. AI 使用程度必须如实记录；
9. 不查看当前算法分数、引用量、排名、selection bucket 或人工旧标签；
10. `reason` 必须简短说明判断依据。

## 2. Label 定义

### `2`：高度相关

论文的核心研究对象、输入数据和主要任务与 research question 直接对应。机器学习或数据
驱动方法是解决该任务的重要方法，而不是背景提及。

### `1`：部分相关

论文与问题有真实、可解释的交集，但目标更宽、更窄或只覆盖其中一个子任务；也可能该
任务是论文的重要组成部分，但不是唯一核心目标。

### `0`：不相关

仅共享表面词汇，核心对象、数据或任务不一致；或者机器学习、恒星光谱及目标任务之一只
在背景中出现，不能回答当前 research question。

### `?`：待讨论 / 证据不足

现有标题、摘要和可访问证据不足以可靠判断，或证据相互矛盾。`?` 不是偷懒选项，必须在
`reason` 中写明缺少什么证据。

## 3. 三个 Research Query 的判定边界

### RQ01：恒星光谱分类 / 恒星类型识别

- 正例：以恒星光谱为输入，使用机器学习预测光谱型、恒星类型或分类标签。
- 边界例：建立包含分类在内的通用恒星光谱分析 Pipeline，分类只是多个重要任务之一。
- 反例：星系分类、医学光谱分类，或只使用测光数据进行恒星分类。

### RQ02：恒星参数估计

- 正例：从恒星光谱估计 Teff、log g、metallicity、元素丰度或其他恒星标签。
- 边界例：方法同时做光谱建模和参数估计，但摘要没有说明参数推断是否为主要输出。
- 反例：只使用已有恒星参数研究银河系结构，或参数来自目录而不是从光谱推断。

### RQ03：恒星光谱预处理与质量改进

- 正例：机器学习直接用于恒星光谱降噪、归一化、校准、伪影去除或质量恢复。
- 边界例：预处理是完整分析系统的重要模块，但论文主要贡献可能是下游分类或参数估计。
- 反例：常规数据清洗、一句话提到 normalization，或处理的是医学、遥感等其他光谱。

## 4. 常见误判

- **stellar spectra vs medical spectra**：出现 spectrum、classification、denoising 不够，必须确认研究对象是恒星光谱；
- **stellar classification vs galaxy classification**：天文学领域相同不等于任务相同；
- **机器学习是核心方法 vs 背景提及**：摘要只说“机器学习发展迅速”不能判相关；
- **参数估计是核心目标 vs 使用已有参数**：输入/输出方向必须看清；
- **光谱预处理 vs 一般数据清洗**：只有预处理本身是研究方法或主要贡献才高度相关；
- **标题相关、摘要偏题**：以摘要揭示的核心任务为准，必要时查外部页面；
- **高引用或发表在知名期刊**：不影响 Query Relevance label；
- **排名靠前**：不能作为人工判断证据。

## 5. Confidence

- `high`：证据直接、边界清楚，基本没有其他合理解释；
- `medium`：总体可以判断，但范围或任务角色存在少量不确定；
- `low`：证据有限、需要推断，或保留明显疑点。

Confidence 表示对 relevance 判断的把握，不表示论文质量。

## 6. Evidence Level

### A：Title + Abstract 足够

标题和摘要已经清楚说明对象、数据、任务和方法。`source_checked` 填
`title_abstract`，`evidence_url` 可以留空。

### B：需要可靠外部页面

标题和摘要不足，需要查看 OpenAlex landing page、ADS/SciX、arXiv、出版社或 DOI 页面。
`source_checked` 使用受控值并填写对应 `evidence_url`。

### C：需要全文关键部分

外部摘要仍不足，需要查看 PDF/全文中的 Abstract、Introduction、Methods/Data 或
Conclusion。`source_checked` 必须包含 `pdf_fulltext`，并填写可靠来源 URL。

受控的 `source_checked` 值为：

```text
title_abstract
openalex
ads_scix
arxiv
publisher
doi_page
pdf_fulltext
```

查看多个来源时用英文分号分隔，例如 `title_abstract;arxiv`。

## 7. 证据升级流程

```text
Title + Abstract
        ↓
能明确判断？── 是 → 标注，Evidence A
        │
        否
        ↓
查看 ADS / SciX / arXiv / publisher / DOI 等可靠页面
        ↓
能明确判断？── 是 → 标注，Evidence B
        │
        否
        ↓
查看全文关键部分
        ↓
能明确判断？── 是 → 标注，Evidence C
        │
        否
        ↓
标记 ?，说明缺少的证据
```

不要求所有论文阅读全文。信息不足时不得硬猜。

## 8. AI 辅助规则

允许 AI：

- 翻译摘要、解释天文术语；
- 总结研究对象、输入数据、核心方法和论文输出；
- 指出与 research question 的直接联系和可能误判点；
- 建议还需要核对哪些证据。

最终 label 必须由成员本人确认。`ai_assistance` 只允许：

- `none`：没有使用 AI；
- `translation`：只用于翻译；
- `explanation`：用于术语或论文内容解释，但没有让 AI 给 label；
- `label_suggestion`：AI 明确建议了 `0/1/2/?`，成员复核后自行决定最终 label。

不能把使用 `label_suggestion` 的标签描述为完全无 AI 的纯人工标签。AI 不得看到另一位
标注者的答案。

## 9. 可复制给 AI 的提示词

```text
你现在帮助我理解一篇科研论文，我正在进行 query relevance 人工标注。

Research Question：
<填写当前问题>

Title：
<填写标题>

Abstract：
<填写摘要>

请先不要替我直接决定最终人工标签。请依次告诉我：
1. 论文研究对象；
2. 使用的数据；
3. 核心方法；
4. 主要研究任务；
5. 与 Research Question 的直接相关点；
6. 可能导致误判的点；
7. 仅根据当前摘要是否已有足够证据。

如果信息不足，请明确指出还需要查什么。不要使用论文引用量、当前算法分数、
排名或其他标注者答案来判断相关性。
```

如果成员明确要求 AI 给建议标签，可以最后增加 `suggested_label`，但最终仍由成员确认，
并把 `ai_assistance` 填为 `label_suggestion`。

## 10. 个人 CSV 字段

前半部分是只读信息，不得修改：

- `pair_id`、`research_query_id`；
- 中英文 research question；
- `openalex_id`、`title`、`abstract`、`landing_page_url`；
- `publication_year`、`doi`、`annotator`。

成员填写：

| 字段 | 允许值或要求 |
| --- | --- |
| `label` | `2`、`1`、`0`、`?` |
| `confidence` | `high`、`medium`、`low` |
| `evidence_level` | `A`、`B`、`C` |
| `reason` | 非空，简短说明核心判断依据 |
| `source_checked` | 使用第 6 节受控值，多个值用英文分号 |
| `evidence_url` | A 可空；B/C 必须填写 HTTP(S) 可靠来源 |
| `ai_assistance` | `none`、`translation`、`explanation`、`label_suggestion` |

## 11. 开工和验证

先从最新 `main` 建自己的 W4 分支，再生成个人文件：

```powershell
python -m app.create_annotation_task --annotator <自己的 slug>
```

生成器默认拒绝覆盖已有文件。普通成员不要使用 `--force`。

填写完成后运行：

```powershell
python -m app.validate_annotation_task `
  --file "data/annotation_tasks/w4/annotations/<自己的 slug>.csv"
```

Validator 只检查 assignment、只读字段、枚举、证据和 CSV 契约，不会根据 label 判断“标得
对不对”。通过 validator 也不表示该标签已经成为 ground truth。
