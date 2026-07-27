"""
TF-IDF 文本相关性模块说明：

这个文件负责计算论文标题、摘要与用户查询之间的词法相关性分数。
它位于初步排序（processor.py）之后，为两阶段排序提供第一阶段的相关性输入。
输入是论文列表和查询关键词，输出是追加了三个相关性分数字段的论文列表。

注意：TF-IDF 只是"词法相关性"基线，衡量的是词项重合程度，
不代表真正的语义理解，也不能替代人工阅读和判断。
"""

import math
import re


# 标题通常比摘要更能直接表达论文主题，组合分数中标题占 70%，摘要占 30%。
# 权重固定且写死在模块常量里，保证可解释、可复查，不随数据自动调整。
TITLE_WEIGHT = 0.7
ABSTRACT_WEIGHT = 0.3

# 英文数字词项按完整单词提取；中文按连续汉字片段提取后切成二字组。
# 二字组是词法层面的最小可解释单位：单字太容易误匹配（如"学"、"习"），
# 整段又太严格（"恒星光谱分析"和"恒星光谱"无法匹配）。
ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")

SCORE_FIELDS = [
    "title_relevance_score",
    "abstract_relevance_score",
    "combined_relevance_score",
]


def tokenize_text(text: str) -> list[str]:
    """
    把文本拆成用于词法匹配的词项列表。

    参数：
        text：标题、摘要或查询文本，可能为空或 None。
    返回：小写英文数字词项与中文二字组按序组成的列表。
    异常或特殊情况：空文本返回空列表；单个汉字保留为单字词项；
        不做词干还原、同义词扩展或语义理解。
    """
    if not text:
        return []

    lowered = str(text).lower()
    tokens = ENGLISH_TOKEN_PATTERN.findall(lowered)
    for cjk_run in CJK_RUN_PATTERN.findall(lowered):
        if len(cjk_run) == 1:
            tokens.append(cjk_run)
        else:
            for index in range(len(cjk_run) - 1):
                tokens.append(cjk_run[index : index + 2])
    return tokens


def build_idf(documents: list[list[str]]) -> dict[str, float]:
    """
    在一组文档上统计逆文档频率（IDF）。

    参数：
        documents：词项列表的列表，每个元素是一篇文档（如全部标题）。
    返回：词项到 IDF 值的字典。
    异常或特殊情况：空语料返回空字典。
        使用平滑公式 ln((N + 1) / (df + 1)) + 1，避免除以 0，
        也保证词项不在任何文档出现时 IDF 依然是有限正数。
    """
    document_count = len(documents)
    if document_count == 0:
        return {}

    document_frequency: dict[str, int] = {}
    for tokens in documents:
        # 同一词项在同一篇文档里出现多次，df 只记一次。
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    idf = {}
    for token, frequency in document_frequency.items():
        idf[token] = math.log((document_count + 1) / (frequency + 1)) + 1.0
    return idf


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """
    把词项列表转成 TF-IDF 稀疏向量。

    参数：
        tokens：单篇文档或查询的词项列表。
        idf：由 build_idf 统计的逆文档频率表。
    返回：词项到 TF-IDF 权重的字典（稀疏向量，只存非零项）。
    异常或特殊情况：词项不在 IDF 表中（例如查询词不在语料里）时，
        按 df = 0 的平滑 IDF 计算，避免查询向量丢失该词项。
    """
    if not tokens:
        return {}

    term_frequency: dict[str, int] = {}
    for token in tokens:
        term_frequency[token] = term_frequency.get(token, 0) + 1

    corpus_size = len(idf)
    fallback_idf = math.log((corpus_size + 1) / (0 + 1)) + 1.0

    vector = {}
    for token, frequency in term_frequency.items():
        vector[token] = frequency * idf.get(token, fallback_idf)
    return vector


def cosine_similarity(vector_a: dict[str, float], vector_b: dict[str, float]) -> float:
    """
    计算两个稀疏向量的余弦相似度。

    参数：
        vector_a：第一个 TF-IDF 稀疏向量。
        vector_b：第二个 TF-IDF 稀疏向量。
    返回：0 到 1 之间的相似度；TF-IDF 权重非负，所以余弦值不会小于 0。
    异常或特殊情况：任一向量为空（范数为 0）时返回 0.0，避免除以 0。
    """
    if not vector_a or not vector_b:
        return 0.0

    # 只遍历较小的向量，稀疏点积更快。
    if len(vector_a) > len(vector_b):
        vector_a, vector_b = vector_b, vector_a
    dot_product = 0.0
    for token, weight in vector_a.items():
        dot_product += weight * vector_b.get(token, 0.0)

    norm_a = math.sqrt(sum(weight * weight for weight in vector_a.values()))
    norm_b = math.sqrt(sum(weight * weight for weight in vector_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class TextRelevanceScorer:
    """
    基于 TF-IDF 的词法相关性打分器。

    构造时在一批论文上分别统计标题语料和摘要语料的 IDF，
    之后对每篇论文计算标题、摘要与查询的余弦相似度，
    再按固定权重组合成 combined_relevance_score。
    """

    def __init__(self, papers: list[dict], query: str) -> None:
        """
        参数：
            papers：参与打分的论文列表，语料规模 N 由它决定。
            query：用户查询关键词；空查询会让所有分数为 0。
        异常或特殊情况：论文列表为空时 IDF 表为空，分数全部为 0。
        """
        # 空语料意味着不存在可比较的文档集合，此时任何论文的分数都记为 0，
        # 避免回退 IDF 把"查询与单篇文档的自相似"误当作相关性。
        self.corpus_is_empty = not papers
        title_documents = [tokenize_text(paper.get("title") or "") for paper in papers]
        abstract_documents = [
            tokenize_text(paper.get("abstract") or "") for paper in papers
        ]
        self.title_idf = build_idf(title_documents)
        self.abstract_idf = build_idf(abstract_documents)
        query_tokens = tokenize_text(query)
        # 查询同时投影到标题向量空间和摘要向量空间：
        # 标题分数在标题语料 IDF 下计算，摘要分数在摘要语料 IDF 下计算，
        # 两类分数各自在论文之间可比。
        self.title_query_vector = tfidf_vector(query_tokens, self.title_idf)
        self.abstract_query_vector = tfidf_vector(query_tokens, self.abstract_idf)

    def score_paper(self, paper: dict) -> dict[str, float]:
        """
        计算单篇论文的三个词法相关性分数。

        参数：
            paper：单篇论文，标题或摘要缺失时对应子分为 0。
        返回：包含 title_relevance_score、abstract_relevance_score、
            combined_relevance_score 的字典，取值都在 0 到 1 之间。
        异常或特殊情况：不抛出异常；缺标题、缺摘要、空文本都得到 0 子分，
            组合分仍由存在的部分按固定权重算出。
        """
        zero_scores = {
            "title_relevance_score": 0.0,
            "abstract_relevance_score": 0.0,
            "combined_relevance_score": 0.0,
        }
        if self.corpus_is_empty:
            return zero_scores

        title_vector = tfidf_vector(
            tokenize_text(paper.get("title") or ""), self.title_idf
        )
        abstract_vector = tfidf_vector(
            tokenize_text(paper.get("abstract") or ""), self.abstract_idf
        )

        title_score = cosine_similarity(self.title_query_vector, title_vector)
        abstract_score = cosine_similarity(self.abstract_query_vector, abstract_vector)
        combined_score = (
            TITLE_WEIGHT * title_score + ABSTRACT_WEIGHT * abstract_score
        )
        return {
            "title_relevance_score": round(title_score, 4),
            "abstract_relevance_score": round(abstract_score, 4),
            "combined_relevance_score": round(combined_score, 4),
        }

    def score_papers(self, papers: list[dict]) -> list[dict]:
        """
        为一批论文追加三个词法相关性分数字段。

        参数：
            papers：论文列表，元素不会被原地修改。
        返回：追加了 SCORE_FIELDS 三个字段的新论文列表。
        异常或特殊情况：空列表返回空列表。
        """
        scored_papers = []
        for paper in papers:
            scored_paper = dict(paper)
            scored_paper.update(self.score_paper(paper))
            scored_papers.append(scored_paper)
        return scored_papers


def add_text_relevance_scores(papers: list[dict], query: str) -> list[dict]:
    """
    为论文列表计算并追加 TF-IDF 词法相关性分数。

    参数：
        papers：论文列表，通常已经完成清洗和初步排序。
        query：用户查询关键词。
    返回：追加了 title_relevance_score、abstract_relevance_score、
        combined_relevance_score 的新论文列表，顺序与输入一致。
    异常或特殊情况：空列表或空查询时仍返回列表，对应分数为 0。
        该分数只是词法相关性基线，不代表语义层面的相关。
    """
    scorer = TextRelevanceScorer(papers, query)
    return scorer.score_papers(papers)


if __name__ == "__main__":
    demo_papers = [
        {
            "title": "Machine Learning for Stellar Spectra",
            "abstract": "We estimate stellar parameters from spectra with machine learning.",
        },
        {
            "title": "Deep Sea Fish Tracking",
            "abstract": "A camera system for tracking fish in the deep sea.",
        },
    ]
    demo_query = "machine learning stellar parameter estimation spectra"
    for demo_paper in add_text_relevance_scores(demo_papers, demo_query):
        print(
            demo_paper["title"],
            demo_paper["combined_relevance_score"],
        )
