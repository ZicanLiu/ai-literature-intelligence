import csv
import os

csv_path = os.path.join("data", "domain", "stellar_spectra_terms_w2.csv")

def load_domain_terms(filepath):
    positive_terms = []
    negative_terms = []
    weak_terms = []
    synonym_map = {}

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = row["term_text"].strip()
            syno = row["synonym"].strip()
            t_type = row["term_type"].strip()
            # 存入同义词
            if syno:
                synonym_map[term] = syno
            # 分类
            if t_type == "negative_term":
                negative_terms.append(term)
            elif t_type == "weak_term":
                weak_terms.append(term)
            else:
                positive_terms.append(term)
    return positive_terms, weak_terms, negative_terms, synonym_map

def build_openalex_query(pos, weak, neg):
    # 构造检索式：(核心术语 OR 弱相关术语) NOT 无关术语
    pos_part = " OR ".join([f'"{t}"' for t in pos])
    weak_part = " OR ".join([f'"{t}"' for t in weak])
    full_query = f"title_abstract:(({pos_part}) OR ({weak_part})) "
    if neg:
        neg_part = " OR ".join([f'"{t}"' for t in neg])
        full_query += f"NOT title_abstract:({neg_part})"
    return full_query

if __name__ == "__main__":
    pos, weak, neg, syn_map = load_domain_terms(csv_path)
    query = build_openalex_query(pos, weak, neg)
    print("=== OpenAlex 检索语句 ===")
    print(query)