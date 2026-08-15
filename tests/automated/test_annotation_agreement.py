import pandas as pd
from src.annotation_agreement import AgreementAnalyzer

def test_agreement_analyzer_validates_correctly(tmp_path):
    assignments_path = tmp_path / "assignments_v0.1.csv"
    annotations_dir = tmp_path / "annotations"
    annotations_dir.mkdir()
    output_dir = tmp_path / "output"
    
    # 构建 assignment fixture，P1-P3为双标，P4仅单人。列名已改为 annotator_slug
    pd.DataFrame({
        "pair_id": ["P1", "P1", "P2", "P2", "P3", "P3", "P4"],
        "research_query_id": ["rq01", "rq01", "rq02", "rq02", "rq03", "rq03", "rq01"],
        "annotator_slug": ["huangbin", "liuzican", "huangbin", "liuzican", "huangbin", "liuzican", "huangbin"]
    }).to_csv(assignments_path, index=False)
    
    # 模拟 huangbin 的标准 CSV 结构
    pd.DataFrame({
        "pair_id": ["P1", "P2", "P3", "P4"],
        "research_query_id": ["rq01", "rq02", "rq03", "rq01"],
        "label": ["1", "0", "?", "2"],
        "confidence": ["high", "medium", "low", "high"],
        "reason": ["测试原因1", "测试原因2", "证据不足", "明确"]
    }).to_csv(annotations_dir / "huangbin.csv", index=False)
    
    # 模拟 liuzican 的对照数据：P1完全一致，P2冲突，P3含有问号
    pd.DataFrame({
        "pair_id": ["P1", "P2", "P3"],
        "research_query_id": ["rq01", "rq02", "rq03"],
        "label": ["1", "1", "0"], 
        "confidence": ["high", "high", "medium"],
        "reason": ["原因A", "原因B", "原因C"]
    }).to_csv(annotations_dir / "liuzican.csv", index=False)

    analyzer = AgreementAnalyzer(str(assignments_path), str(annotations_dir))
    analyzer.analyze(str(output_dir))
    
    # 断言产物存在
    assert (output_dir / "agreement_summary.json").exists()
    assert (output_dir / "disagreements.csv").exists()
    
    # 断言逻辑分流正确
    disagreements = pd.read_csv(output_dir / "disagreements.csv")
    assert len(disagreements) == 2  
    
    p2_row = disagreements[disagreements['pair_id'] == 'P2'].iloc[0]
    assert p2_row['disagreement_type'] == 'Label_Conflict'
    
    p3_row = disagreements[disagreements['pair_id'] == 'P3'].iloc[0]
    assert p3_row['disagreement_type'] == 'Needs_Discussion_Unknown'