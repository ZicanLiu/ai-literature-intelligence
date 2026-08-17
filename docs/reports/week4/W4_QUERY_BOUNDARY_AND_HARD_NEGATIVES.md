# W4 Query Boundary 与 Hard Negative 分析

## 1. 状态、范围与数据基线

本报告服务 Issue #39，分析 W4 Pilot v0.1 三个具体 Research Query 的检索边界，并从冻结
Candidate Pool 中归纳容易被词法检索误判的 Hard Negative 类型。分析基线仅包括：

- [`configs/w4/research_queries.json`](../../../configs/w4/research_queries.json)；
- [`candidate_pool_v0.1.csv`](../../../data/annotation_tasks/w4/candidate_pool_v0.1.csv)；
- [`assignments_v0.1.csv`](../../../data/annotation_tasks/w4/assignments_v0.1.csv)；
- [`W4_ANNOTATION_GUIDELINE.md`](../../project/W4_ANNOTATION_GUIDELINE.md)。

配套的逐例数据见
[`w4_query_boundary_examples.csv`](../../../data/analysis/w4_query_boundary_examples.csv)。其中的
`pair_id`、OpenAlex ID 和标题均直接复制自冻结 Candidate Pool，未新增 live 请求，也未改写
公共 Query、Candidate Pool 或 assignment。

本轮最初生成了
[`chenxingyu.csv`](../../../data/annotation_tasks/w4/annotations/chenxingyu.csv) 的 15 条
AI-assisted label suggestion。陈星妤后来已本人实际审核并确认这 15 条；当前 CSV 标签没有因
本次文档事实修正而改变。它们应准确描述为“本人确认的 AI-assisted human annotation”，仍不
是 expert gold、gold label 或 ground truth。本分析生成建议时没有查看其他标注者答案。

## 2. 统一判定框架

每个 query-paper pair 按四个问题判断：

1. **研究对象**：恒星、星系、超新星遗迹，还是通信、医学、矿业等其他对象；
2. **输入模态**：一维恒星光谱、测光光曲线、宽带颜色、SED、X 射线图像或其他 spectral data；
3. **方法角色**：机器学习是否真正执行目标任务，还是只在背景、正则化或方法名称中出现；
4. **主要输出**：分类标签、恒星参数、质量恢复后的光谱，还是另一个下游科研结果。

只有对象、输入和主要输出与 Query 对齐，且机器学习承担核心方法角色时，才构成高度相关。
Candidate Pool 是高召回候选集合，因此被 acquisition query 命中不等于人工相关。

## 3. RQ01（`rq01_stellar_classification`）：恒星光谱分类或恒星类型识别

### Scope In

- 研究对象是恒星，输入是观测或可靠合成的恒星光谱；
- 机器学习直接预测恒星光谱型、恒星类型、光谱形态类别或可解释的特殊光谱类别；
- 分类是论文的主要任务，而不是参数估计或预处理 Pipeline 中一句附带描述。

真实正例锚点：

- `w4_rq01_004`：t-SNE 映射 GALAH 恒星光谱形态，并形成异常/特殊光谱分类；
- `w4_rq01_008`：随机森林直接分类恒星光谱并评估分类特征。

### Scope Out

- 只使用测光光曲线或宽带颜色，即使输出包含 star 或 stellar；
- star/galaxy/QSO 对象级分类，而不是恒星内部的光谱型或恒星类型识别；
- 星系、通信、材料等领域的 spectrum classification；
- 使用 ML 估计恒星参数、周期或其他量，但不输出恒星光谱类别。

### 常见边界与 Hard Negatives

- **测光替代光谱**：`w4_rq01_010` 从 Kepler 光曲线估计自转周期；
  `w4_rq01_015` 用宽带颜色做 star/galaxy/QSO 分类和 Teff 回归。
- **对象分类替代恒星类型分类**：`w4_rq01_016` 的标题和背景包含 stellar
  classification，但摘要给出的输出是 Galaxy 与 Star。
- **跨领域 spectrum/classification 同名**：`w4_rq01_014` 的 spectrum 是无线电频谱，
  classification 是调制方式识别。

词法检索容易误检，是因为 `machine learning`、`classification`、`stellar` 和 `spectrum`
可以分别出现在背景、输入或完全不同的领域中。后续候选方法应显式抽取“恒星对象 +
光谱输入 + 分类输出”，不能只累计词项命中。

### Potential Revision（不修改 v0.1）

未来 Query 版本可考虑把 `spectroscopic input` 与 `stellar spectral type / morphology output`
写得更显式，并把 `photometric light curve`、`star-galaxy classification` 作为可审计的
negative context。是否修改由后续统一任务决定，本 PR 不改冻结配置。

## 4. RQ02（`rq02_stellar_parameters`）：从恒星光谱估计物理或大气参数

### Scope In

- 输入是恒星光谱；训练监督标签可以来自高分辨率巡天或既有 Pipeline；
- 模型对新的光谱执行推断，主要输出包括 Teff、log g、metallicity、元素丰度或其他恒星标签；
- 参数估计是论文主要产物，而非只把已有参数用于族群、银河系结构或分类研究。

真实正例锚点：

- `w4_rq02_008`：非线性回归从 SDSS/SEGUE 光谱估计 Teff、log g 和 [Fe/H]；
- `w4_rq02_012`：SLAM 用支持向量回归从 LAMOST 光谱推断多维恒星标签；
- `w4_rq02_018`：The Cannon 重分析 RAVE 光谱，产出大气参数和元素丰度目录。

### Scope Out

- 把已经测得的 abundance/parameter 当作输入，再做聚类、族群或银河系研究；
- 使用恒星光谱做碳星、双星或光谱类型分类，但不回归物理参数；
- 通过测光、星震或其他数据约束内部结构，且没有从光谱执行 ML 参数推断；
- 仅发布巡天或模板库，没有证据表明 ML 参数化是核心任务。

### 常见边界与 Hard Negatives

- **推断方向颠倒**：`w4_rq02_002` 用已有化学丰度作为 t-SNE 输入，输出丰度空间结构，
  并不从光谱估计丰度。
- **同模态、不同任务**：`w4_rq02_014` 使用 LAMOST 光谱和机器学习，但主要输出是碳星检出
  与亚型分类；少量大气参数只是附带识别依据。
- **恒星参数但数据模态错误**：`w4_rq02_020` 从亮度振荡讨论恒星内部结构，既非光谱输入，
  也没有 ML 光谱回归。

`stellar`、`spectra`、`abundance` 和 `parameter` 的共现无法表达输入到输出的方向。后续方法应
区分“参数作为训练监督”“参数作为待预测输出”和“参数作为下游分析输入”。

### Potential Revision（不修改 v0.1）

未来可在 Query 描述中显式加入 `infer/predict labels from observed stellar spectra`，并把
`using catalogued parameters`、`abundance-space analysis` 作为 negative context。该建议只记录，
不改变当前冻结 Query。

## 5. RQ03（`rq03_spectral_preprocessing`）：恒星光谱预处理与质量改进

### Scope In

- 输入是观测恒星光谱或与观测质量恢复直接对应的恒星光谱；
- ML 直接执行去噪、归一化、校准、伪影/天空线处理、缺失通量修复或质量恢复；
- 主要输出是质量改善后的光谱，预处理不是下游分类或参数估计的普通前置步骤。

真实正例锚点：

- `w4_rq03_014`：深度贝叶斯模型对 SDSS 恒星光谱去噪并恢复缺失通量，质量恢复是核心输出。

### Scope Out

- 测光光曲线、星系 SED、X 射线图像或矿井水光谱的去噪与校准；
- 自编码器名称含 denoising，但最终任务是特征学习而非恢复恒星光谱；
- 从恒星光谱估计参数或分类，正则化、CWT、PCA 等只是模型或特征步骤；
- 生成合成恒星光谱，但没有改善观测光谱质量的目标。

### 常见边界与 Hard Negatives

- **处理动作正确、模态错误**：`w4_rq03_006` 去除 Kepler 光曲线系统误差。
- **模型名误导**：`w4_rq03_011` 使用 denoising autoencoder 学习星系 SED 表示；denoising
  是训练机制，不是最终质量恢复产物。
- **恒星光谱正确、核心任务错误**：`w4_rq03_012` 和 `w4_rq03_019` 从光谱估计参数；
  `w4_rq03_013` 用 CWT 和神经网络做光谱分类。
- **天文领域正确、对象/产品错误**：`w4_rq03_015` 重建 SN1006 的 X 射线时空-能谱图像。
- **跨领域处理词完全重合**：`w4_rq03_018` 对矿井水 UV–Vis 光谱执行 preprocessing、
  denoising 和 normalization。
- **生成与恢复的边界**：`w4_rq03_009` 用神经网络从参数生成归一化合成光谱；它与重建相邻，
  但摘要没有把观测光谱质量改进作为目标，因此保留为边界案例而非 RQ03 正例锚点。

RQ03 暴露了最强的词法歧义：`spectral`、`denoising`、`normalization` 和 `regularized` 可在不同
对象、数据产品和方法角色中出现。后续方法需要先识别数据产品，再判断处理动作是否直接改变
该产品的质量。

### Potential Revision（不修改 v0.1）

未来可考虑加入 `observed stellar spectrum as input`、`restored/calibrated spectrum as output`，
并区分 `data restoration`、`synthetic spectrum generation` 与 `downstream prediction`。当前配置保持
冻结。

## 6. Hard Negative Taxonomy

| 类型 | 定义 | Candidate Pool 示例 | 词法误检原因 | 后续可能改善 |
| --- | --- | --- | --- | --- |
| 研究对象/领域错位 | 方法与任务词相似，但对象不是恒星光谱 | `w4_rq01_014`、`w4_rq03_018` | spectrum、classification、denoising 是跨领域通用词 | 加入天文实体和对象约束；保留跨领域 negative slice |
| 数据模态错位 | 研究恒星且任务相似，但输入是测光或其他产品 | `w4_rq01_010`、`w4_rq01_015`、`w4_rq03_006` | stellar 与任务词命中，掩盖 light curve/photometry | 抽取 input modality；对 photometry/light curve 建显式负特征 |
| 核心任务错位 | 数据是恒星光谱，但输出属于另一个 RQ | `w4_rq02_014`、`w4_rq03_012`、`w4_rq03_019` | 同一论文同时出现 spectra、parameter、classification 等词 | 抽取主要输出；按 query-dependent task 判定 |
| 输入/输出方向颠倒 | 目标变量作为已有输入，而非待预测输出 | `w4_rq02_002` | abundance/parameter 与 RQ 词项高度重合 | 建模 infer-from 关系，不只做实体共现 |
| 方法名或邻近任务误导 | 名称含 denoising/regularized/reconstruct，但最终输出不对应 | `w4_rq03_009`、`w4_rq03_011` | 方法名称比任务描述更容易被 TF-IDF 捕获 | 联合摘要中的 input、method role、output；保留人工边界复核 |
| 天文子领域/数据产品错位 | 同属天文但对象是星系、SNR 或图像 | `w4_rq03_011`、`w4_rq03_015` | astronomy 与 spectral 语境不足以区分具体数据产品 | 细分 object type 与 spectrum/SED/image 产品类型 |

这些类型是本 Candidate Pool 中的观察性 taxonomy，不等于已经训练或验证了一个 hard-negative
模型，也不提前声称加入这些特征会提升指标。

## 7. 对 retrieval、ranking 与 benchmark 的启示

1. **Acquisition 保持高召回，ranking 负责边界判断**：候选获取允许出现 hard negatives，但不能
   把 acquisition query 命中解释为人工相关。
2. **至少表达对象、模态、方法角色和输出任务**：当前 TF-IDF baseline 对单词共现敏感，无法可靠
   表达 input → task → output。
3. **按 RQ 保存 query-dependent label**：同一论文可能对 RQ02 相关、对 RQ03 不相关，不能把论文
   压成单一全局标签。
4. **benchmark 应保留 error slices**：未来 agreement 和 adjudication 可按 wrong-domain、
   wrong-modality、wrong-task、direction-reversal 等类型报告，而不只汇总一个总分。
5. **不使用标签反向修改本次 Candidate Pool**：本报告分析错误模式，但不改变 v0.1 选样、排名权重
   或冻结 Query，避免评价数据泄漏到当前 baseline。

## 8. 陈星妤人工复核记录

以下 15 条最初均为 AI label suggestion，现已由陈星妤本人审核确认。“重点复核”保留为当时
用于突出旧 PR 判断变化、摘要边界或容易混淆任务的历史审查提示。当前没有 label=`1`/`?`，
也没有 Evidence B/C；这来自本 assignment 的实际构成，不是人为平衡标签分布。

| pair_id | 论文短标题 | RQ | 当前 label | confidence | 一句话核心依据 | 历史重点复核 | 与旧 PR 比较 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `w4_rq01_004` | Galah t-SNE classification | RQ01 | 2 | high | GALAH 恒星光谱经 t-SNE 形成特殊光谱类别，分类是核心输出 | 否 | 2 → 2 |
| `w4_rq01_010` | ROOSTER rotation periods | RQ01 | 0 | high | 输入是 Kepler 测光光曲线，输出自转周期，不是恒星光谱类型 | **是** | **1 → 0** |
| `w4_rq01_014` | Wireless modulation survey | RQ01 | 0 | high | 无线通信射频调制识别，领域完全错位 | 否 | 旧 PR 未提交 |
| `w4_rq01_015` | Star–Galaxy–QSO + Teff | RQ01 | 0 | high | 宽带测光做对象分类和温度回归，不输入恒星光谱 | **是** | 旧 PR 未提交 |
| `w4_rq01_016` | Experimental stellar classification | RQ01 | 0 | medium | 摘要输出 Galaxy/Star 类别且模态不清，标题与核心任务冲突 | **是** | **2 → 0** |
| `w4_rq02_002` | Abundance-space t-SNE | RQ02 | 0 | high | 已有丰度是输入，输出族群结构，不是从光谱推断参数 | **是** | **1 → 0** |
| `w4_rq02_008` | SDSS/SEGUE parameters | RQ02 | 2 | high | 非线性回归从恒星光谱直接输出 Teff、log g、[Fe/H] | 否 | 2 → 2 |
| `w4_rq02_012` | SLAM labels | RQ02 | 2 | high | SVR 从 LAMOST 光谱推断多维恒星标签 | 否 | 旧 PR 未提交 |
| `w4_rq02_014` | Carbon stars from LAMOST | RQ02 | 0 | high | 核心是碳星检出和亚型分类，大气参数不是 ML 主要输出 | **是** | 旧 PR 未提交 |
| `w4_rq02_020` | Asteroseismology review | RQ02 | 0 | high | 测光振荡约束内部结构，无光谱 ML 参数回归 | 否 | 0 → 0 |
| `w4_rq03_006` | Kepler systematics removal | RQ03 | 0 | high | 去噪对象是测光光曲线而非恒星光谱 | **是** | **1 → 0** |
| `w4_rq03_011` | Galaxy SED denoising AE | RQ03 | 0 | high | 去噪自编码器学习星系 SED 表示，不输出恢复后的恒星光谱 | **是** | 旧 PR 未提交 |
| `w4_rq03_012` | deep-REMAP parameters | RQ03 | 0 | high | 模型输出恒星参数；regularized 不等于光谱预处理 | **是** | **1 → 0** |
| `w4_rq03_015` | SN1006 X-ray imaging | RQ03 | 0 | high | 重建的是超新星遗迹 X 射线图像，不是恒星光谱 | 否 | 旧 PR 未提交 |
| `w4_rq03_018` | Mine water XGBoost | RQ03 | 0 | high | 矿井水光谱虽做去噪归一化，但对象领域错误 | 否 | 0 → 0 |

## 9. 人工确认状态

陈星妤已完成本人审核确认。`chenxingyu.csv` 继续保留每行
`ai_assistance=label_suggestion`，如实表示 AI 曾明确给出建议；本次只更新报告状态，不修改她的
任何 label、confidence、evidence 或 reason。该文件可以描述为“本人确认的 AI-assisted human
annotation”，仍不能称为 gold 或 ground truth。
