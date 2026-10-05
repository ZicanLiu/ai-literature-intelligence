"""Wholly synthetic teaching content; never a research benchmark or gold."""
from pathlib import Path

DEMO_WARNING = "SYNTHETIC DEMO / NOT RESEARCH EVIDENCE"
DEMO_SCOPE = "合成分类实验 · Dataset X · 仅演示工作流，不作研究结论"
QUESTIONS = {
    "reported": "哪篇论文报告的 Accuracy 最高？",
    "protocol": "在相同评估协议下，A 是否优于 B？",
    "efficiency": "哪种方法的资源效率更高？",
}
PAPERS = [
    {"letter": "A", "title": "Aster: A Synthetic Classification Study",
     "split": "random split", "accuracy": "92%", "other": "88%",
     "training": "Dataset X training partition only",
     "resources": "Training used one GPU for 2 hours.",
     "preprocessing": "Inputs were standardized using training-only statistics."},
    {"letter": "B", "title": "Birch: A Synthetic Temporal Evaluation",
     "split": "temporal split", "accuracy": "89%", "other": "85%",
     "training": "Dataset X training partition only",
     "resources": "", "preprocessing": ""},
    {"letter": "C", "title": "Cedar: A Synthetic Augmented Training Study",
     "split": "random split", "accuracy": "91%", "other": "87%",
     "training": "Dataset X training partition plus Auxiliary Y",
     "resources": "", "preprocessing": "Inputs were standardized using training-only statistics."},
]


def pdf_path(letter: str) -> Path:
    return Path(__file__).parent / "fixtures" / f"paper_{letter}.pdf"


def statements(paper: dict, alternate=False) -> dict[str, str]:
    accuracy = paper["other"] if alternate else paper["accuracy"]
    title = "Ablation experiment" if alternate else "Primary experiment"
    return {
        "dataset": "Dataset: Dataset X.",
        "split": f"Evaluation split: {paper['split']}.",
        "metric": "Metric: Accuracy (correct predictions / all evaluation samples).",
        "training": f"Training data: {paper['training']}.",
        "result": f"{title}: Accuracy {accuracy}.",
        "resources": paper["resources"],
        "preprocessing": paper["preprocessing"],
    }
