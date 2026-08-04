import json
from pathlib import Path
import csv


def load_domain_terms(csv_path: Path):
    term_dict = {
        "object_term": [],
        "spectrum_term": [],
        "method_term": [],
        "task_term": [],
        "weak_term": [],
        "negative_term": []
    }
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 分类列名 term_type，术语文本列 term_text
            cat = row["term_type"].strip()
            term = row["term_text"].strip()
            if cat in term_dict and term:
                term_dict[cat].append(term)
    return term_dict


def generate_queries(term_dict):
    obj_group = " OR ".join(term_dict["object_term"])
    spec_group = " OR ".join(term_dict["spectrum_term"])
    method_group = " OR ".join(term_dict["method_term"])
    task_group = " OR ".join(term_dict["task_term"])
    weak_group = " OR ".join(term_dict["weak_term"])

    queries = [
        {
            "query_id": "q1",
            "name": "宽泛检索",
            "search_str": f'title_abstract:(({obj_group}) AND ({spec_group}))'
        },
        {
            "query_id": "q2",
            "name": "方法导向检索",
            "search_str": f'title_abstract:(({obj_group}) AND ({spec_group}) AND ({method_group}))'
        },
        {
            "query_id": "q3",
            "name": "任务应用检索",
            "search_str": f'title_abstract:(({obj_group}) AND ({spec_group}) AND ({task_group}))'
        },
        {
            "query_id": "q4",
            "name": "弱关键词扩充检索",
            "search_str": f'title_abstract:(({obj_group}) AND (({spec_group}) OR ({weak_group})))'
        },
        {
            "query_id": "q5",
            "name": "精准窄检索",
            "search_str": f'title_abstract:(({obj_group}) AND ({spec_group}) AND ({method_group}) AND ({task_group}))'
        },
        {
            "query_id": "q6",
            "name": "基础通用检索",
            "search_str": f'title_abstract:(({spec_group}) AND ({obj_group}))'
        }
    ]
    return queries


def main():
    terms_csv = Path("data/domain/stellar_spectra_terms_w2.csv")
    output_json = Path("configs/w2/domain_query_set.json")

    term_dictionary = load_domain_terms(terms_csv)
    query_result = generate_queries(term_dictionary)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump({"queries": query_result}, f, ensure_ascii=False, indent=2)

    print(f"✅ 文件生成成功! 路径: {output_json}")


if __name__ == "__main__":
    main()