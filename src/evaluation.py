"""
排序评价模块说明：

这个文件负责用人工相关等级对排序结果做离线评价。
它位于两阶段排序之后，输入是排名列表和人工标签，输出是
judged Precision@K、judged NDCG@K、Top K 不相关数量和高相关样例平均排名等指标。

指标采用完整 judged（condensed）口径：先从整个排名中移除未标注论文，
再取压缩后已标注排名的前 K 篇计算 Precision 与 NDCG；
coverage_at_k 仍按原始 Top K 计算，说明标注覆盖程度；
标签文件中不在本次排名列表内的论文不参与任何指标。

重要边界：人工标签只用于离线评价，不进入任何线上评分公式；
未标注论文没有相关等级，不能自动算作不相关。
"""

import csv
import math
from pathlib import Path


# 第二周数据接口约定（docs/project/W2_DATA_CONTRACTS.md 第 3 节）允许的
# label 取值与数值等级的映射：高度相关 = 2，部分相关 = 1，不相关 = 0。
LABEL_TO_GRADE = {
    "高度相关": 2,
    "部分相关": 1,
    "不相关": 0,
}

# "待讨论" 是合法标签但还没有确定等级，评价时按未标注处理。
UNGRADED_LABELS = {"待讨论"}

HIGHLY_RELEVANT_GRADE = 2


def parse_relevance_label(label: object) -> int | None:
    """
    把单条人工标签解析成数值等级。

    参数：
        label：标签原文，可能是字符串、None 或其他类型。
    返回：2、1、0 或 None；None 表示该论文没有可用等级（未标注或待讨论）。
    异常或特殊情况：标签不在第二周允许的取值内时抛出 ValueError，
        非法标签必须报错，不能悄悄当成不相关或未标注。
    """
    if label is None:
        return None
    text = str(label).strip()
    if text == "" or text in UNGRADED_LABELS:
        return None
    if text in LABEL_TO_GRADE:
        return LABEL_TO_GRADE[text]
    raise ValueError(
        f"非法相关等级标签：{text!r}。允许的取值："
        f"{list(LABEL_TO_GRADE) + list(UNGRADED_LABELS)}"
    )


def build_grade_map(labels: dict[str, object]) -> dict[str, int]:
    """
    把 openalex_id 到标签的映射转成 openalex_id 到数值等级的映射。

    参数：
        labels：openalex_id 到标签原文的字典。
    返回：只包含已确定等级论文的字典；未标注和待讨论论文不出现。
    异常或特殊情况：包含非法标签时抛出 ValueError。
    """
    grade_map = {}
    for openalex_id, label in labels.items():
        grade = parse_relevance_label(label)
        if grade is not None:
            grade_map[openalex_id] = grade
    return grade_map


def load_label_csv(label_file: Path) -> dict[str, str]:
    """
    从 CSV 文件读取人工标签。

    参数：
        label_file：包含 openalex_id 和 label 两列的 CSV 路径。
    返回：openalex_id 到标签原文的字典；label 为空的行按未标注跳过。
    异常或特殊情况：文件不存在或缺少必需列时抛出 ValueError。
    """
    label_path = Path(label_file)
    if not label_path.is_file():
        raise ValueError(f"标签文件不存在：{label_path}")

    labels = {}
    with label_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"openalex_id", "label"} <= set(
            reader.fieldnames
        ):
            raise ValueError("标签 CSV 必须包含 openalex_id 和 label 两列。")
        for row in reader:
            openalex_id = (row.get("openalex_id") or "").strip()
            label = (row.get("label") or "").strip()
            if openalex_id and label:
                labels[openalex_id] = label
    return labels


def validate_k(k: int) -> int:
    """
    校验指标截断位置 K。

    参数：
        k：Top K 的 K。
    返回：原样的 k。
    异常或特殊情况：k 不是正整数时抛出 ValueError。
    """
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ValueError(f"K 必须是正整数，当前值：{k!r}")
    return k


def filter_grades_to_ranked(
    ranked_ids: list[str], grade_map: dict[str, int]
) -> dict[str, int]:
    """
    只保留出现在本次排名列表中的已标注论文。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典。
    返回：只包含 ranked_ids 中论文的等级字典；标签文件里不在本次排名中的
        论文不参与 IDCG、labeled_count 或任何指标。
    """
    ranked_set = set(ranked_ids)
    return {
        openalex_id: grade
        for openalex_id, grade in grade_map.items()
        if openalex_id in ranked_set
    }


def judged_count_at_k(ranked_ids: list[str], grade_map: dict[str, int], k: int) -> int:
    """
    统计原始 Top K 中有确定等级（已标注且非待讨论）的论文数量。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典，未标注论文不在其中。
        k：截断位置。
    返回：原始 Top K 中已标注论文数量。
    异常或特殊情况：该计数只用于 coverage_at_k（原始 Top K 的标注覆盖程度），
        与 judged 指标使用的完整压缩排名无关。
    """
    validate_k(k)
    return sum(1 for openalex_id in ranked_ids[:k] if openalex_id in grade_map)


def judged_precision_at_k(
    ranked_ids: list[str], grade_map: dict[str, int], k: int
) -> float | None:
    """
    计算 judged Precision@K：压缩后已标注排名前 K 篇中相关（等级 ≥ 1）的比例。

    采用完整 judged（condensed）口径：先从整个排名中移除未标注论文，
    再取压缩后已标注排名的前 K 篇，分母是这 K 篇的数量而不是固定的 K，
    因此未标注论文不占位置、不进分母，也不会拉低指标。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典，未标注论文不在其中。
        k：截断位置。
    返回：0 到 1 之间的比例；整个排名中没有任何已标注论文时返回 None，
        因为此时比例无定义。
    """
    validate_k(k)
    condensed_ids = [
        openalex_id for openalex_id in ranked_ids if openalex_id in grade_map
    ][:k]
    if not condensed_ids:
        return None
    relevant_count = sum(
        1 for openalex_id in condensed_ids if grade_map[openalex_id] >= 1
    )
    return relevant_count / len(condensed_ids)


def judged_dcg_at_k(ranked_ids: list[str], grade_map: dict[str, int], k: int) -> float:
    """
    计算 condensed DCG@K：压缩后已标注排名前 K 篇的折损累计增益。

    采用完整 condensed 口径：先从整个排名中移除未标注论文，
    再取压缩后已标注排名的前 K 篇，按压缩后位置折损。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典。
        k：截断位置。
    返回：DCG 值，增益为 2^等级 - 1，折损为 log2(压缩后位置 + 1)；
        未标注论文不占位置，不会以零增益压低指标。
    异常或特殊情况：排名列表为空或没有已标注论文时返回 0.0。
    """
    validate_k(k)
    condensed_ids = [
        openalex_id for openalex_id in ranked_ids if openalex_id in grade_map
    ][:k]
    dcg = 0.0
    for rank_index, openalex_id in enumerate(condensed_ids):
        grade = grade_map[openalex_id]
        dcg += (2**grade - 1) / math.log2(rank_index + 2)
    return dcg


def judged_ndcg_at_k(
    ranked_ids: list[str], grade_map: dict[str, int], k: int
) -> float | None:
    """
    计算 judged NDCG@K：condensed DCG@K 与理想排序 IDCG@K 的比值。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典，必须只包含本次排名中的论文
            （可先用 filter_grades_to_ranked 过滤）。
        k：截断位置。
    返回：0 到 1 之间的 NDCG 值；没有任何已确定等级的论文时返回 None，
        因为理想排序不存在，NDCG 无定义。
    异常或特殊情况：IDCG 由本次排名中全部已标注论文的等级降序排列计算，
        未标注论文不进入理想排序。
    """
    validate_k(k)
    ideal_grades = sorted(grade_map.values(), reverse=True)
    ideal_dcg = 0.0
    for rank_index, grade in enumerate(ideal_grades[:k]):
        ideal_dcg += (2**grade - 1) / math.log2(rank_index + 2)
    if ideal_dcg == 0.0:
        return None
    return judged_dcg_at_k(ranked_ids, grade_map, k) / ideal_dcg


def count_irrelevant_in_top_k(
    ranked_ids: list[str], grade_map: dict[str, int], k: int
) -> int:
    """
    统计 Top K 中被明确标注为不相关（等级 0）的论文数量。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典。
        k：截断位置。
    返回：不相关论文数量；未标注论文不算不相关。
    异常或特殊情况：排名列表为空时返回 0。
    """
    validate_k(k)
    return sum(
        1
        for openalex_id in ranked_ids[:k]
        if openalex_id in grade_map and grade_map[openalex_id] == 0
    )


def average_rank_of_highly_relevant(
    ranked_ids: list[str], grade_map: dict[str, int]
) -> float | None:
    """
    计算高度相关（等级 2）样例的平均排名。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        grade_map：openalex_id 到数值等级的字典。
    返回：从 1 开始计数的平均排名；排名列表中没有高度相关论文时返回 None。
    异常或特殊情况：只统计实际出现在排名列表中的高度相关论文。
    """
    ranks = [
        rank_index + 1
        for rank_index, openalex_id in enumerate(ranked_ids)
        if grade_map.get(openalex_id) == HIGHLY_RELEVANT_GRADE
    ]
    if not ranks:
        return None
    return sum(ranks) / len(ranks)


def evaluate_ranking(
    ranked_ids: list[str], labels: dict[str, object], k: int = 10
) -> dict[str, object]:
    """
    对一次排序结果计算全部离线评价指标。

    指标统一采用完整 judged（condensed）口径：先从整个排名中移除未标注
    论文，再取压缩后已标注排名的前 K 篇计算 Precision 与 NDCG，未标注
    论文不占位置、不进分母；coverage_at_k 与 judged_count_at_k 仍按原始
    Top K 计算；标签文件中不在本次排名列表内的论文不参与任何指标和
    labeled_count。

    参数：
        ranked_ids：按排名从高到低排列的 openalex_id 列表。
        labels：openalex_id 到标签原文的字典；可以只覆盖部分论文，
            也可以包含不在本次排名中的论文（会被忽略）。
        k：截断位置，默认 10。
    返回：包含 k、judged_precision_at_k、judged_ndcg_at_k、
        irrelevant_in_top_k、average_rank_of_highly_relevant、
        labeled_count、judged_count_at_k 和 coverage_at_k 的字典；
        指标无法定义时对应值为 None。
    异常或特殊情况：包含非法标签时抛出 ValueError。
    """
    validate_k(k)
    grade_map = filter_grades_to_ranked(ranked_ids, build_grade_map(labels))
    judged_count = judged_count_at_k(ranked_ids, grade_map, k)
    top_k_size = len(ranked_ids[:k])
    return {
        "k": k,
        "judged_precision_at_k": judged_precision_at_k(ranked_ids, grade_map, k),
        "judged_ndcg_at_k": judged_ndcg_at_k(ranked_ids, grade_map, k),
        "irrelevant_in_top_k": count_irrelevant_in_top_k(ranked_ids, grade_map, k),
        "average_rank_of_highly_relevant": average_rank_of_highly_relevant(
            ranked_ids, grade_map
        ),
        "labeled_count": len(grade_map),
        "judged_count_at_k": judged_count,
        "coverage_at_k": (judged_count / top_k_size) if top_k_size else None,
    }


if __name__ == "__main__":
    demo_ranked = ["A", "B", "C", "D", "E"]
    demo_labels = {"A": "高度相关", "B": "不相关", "C": "部分相关", "E": "高度相关"}
    demo_metrics = evaluate_ranking(demo_ranked, demo_labels, k=3)
    for metric_name, metric_value in demo_metrics.items():
        print(f"{metric_name}: {metric_value}")
