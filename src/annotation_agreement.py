import os
import glob
import json
import pandas as pd
from sklearn.metrics import cohen_kappa_score

class AgreementAnalyzer:
    def __init__(self, assignments_path, annotations_dir):
        self.assignments_path = assignments_path
        self.annotations_dir = annotations_dir
        
    def load_and_merge_data(self):
        """读取任务分配和成员标注文件，严格按 assignments 提取双标重合部分"""
        if not os.path.exists(self.assignments_path):
            raise FileNotFoundError(f"找不到分配文件：{self.assignments_path}")
            
        assignments_df = pd.read_csv(self.assignments_path)
        
        # 提取被分配给两个及以上成员的 pair_id，注意列名已改为 annotator_slug
        pair_counts = assignments_df.groupby('pair_id')['annotator_slug'].apply(list).reset_index()
        double_pairs = pair_counts[pair_counts['annotator_slug'].apply(len) >= 2]
        
        # 加载已存在的所有成员 CSV
        csv_files = glob.glob(os.path.join(self.annotations_dir, "*.csv"))
        annotator_data = {}
        for file in csv_files:
            annotator = os.path.basename(file).replace('.csv', '')
            annotator_data[annotator] = pd.read_csv(file)
            
        merged_records = []
        for _, row in double_pairs.iterrows():
            p_id = row['pair_id']
            # 取前两个分配作为双标对比对象
            ann_a, ann_b = row['annotator_slug'][0], row['annotator_slug'][1]
            
            # 若任意一方文件缺失，安全跳过
            if ann_a not in annotator_data or ann_b not in annotator_data:
                continue 
                
            df_a = annotator_data[ann_a]
            df_b = annotator_data[ann_b]
            
            record_a = df_a[df_a['pair_id'] == p_id]
            record_b = df_b[df_b['pair_id'] == p_id]
            
            if not record_a.empty and not record_b.empty:
                ra = record_a.iloc[0]
                rb = record_b.iloc[0]
                merged_records.append({
                    'pair_id': p_id,
                    'research_query_id': ra.get('research_query_id', 'unknown'),
                    'annotator_a': ann_a,
                    'label_a': str(ra['label']).strip(),
                    'confidence_a': ra.get('confidence', ''),
                    'reason_a': ra.get('reason', ''),
                    'annotator_b': ann_b,
                    'label_b': str(rb['label']).strip(),
                    'confidence_b': rb.get('confidence', ''),
                    'reason_b': rb.get('reason', '')
                })
                
        return pd.DataFrame(merged_records)

    def calculate_metrics(self, df):
        """计算 Exact Agreement 及 Kappa（? 标签将被排除在 Kappa 计算之外）"""
        if df.empty:
            return {}
            
        total_pairs = len(df)
        df_exact = df[df['label_a'] == df['label_b']]
        exact_agreement = len(df_exact) / total_pairs if total_pairs > 0 else 0
        
        # 隔离 '?' 标签
        question_mask = (df['label_a'] == '?') | (df['label_b'] == '?')
        question_count = question_mask.sum()
        
        valid_df = df[~question_mask].copy()
        kappa = None
        weighted_kappa = None
        
        if len(valid_df) > 1:
            try:
                y1 = valid_df['label_a'].astype(int)
                y2 = valid_df['label_b'].astype(int)
                kappa = cohen_kappa_score(y1, y2)
                weighted_kappa = cohen_kappa_score(y1, y2, weights='quadratic')
            except Exception:
                pass # 忽略因类别单一导致的 Kappa 计算警告
                
        return {
            "total_double_pairs": total_pairs,
            "pairs_with_question_mark": int(question_count),
            "exact_agreement_rate": round(float(exact_agreement), 4),
            "cohens_kappa": round(float(kappa), 4) if kappa is not None else None,
            "weighted_cohens_kappa_quadratic": round(float(weighted_kappa), 4) if weighted_kappa is not None else None
        }

    def generate_disagreements(self, df):
        """输出所有标签不一致的队列，供仲裁使用"""
        if df.empty:
            return df
            
        disagreements = df[df['label_a'] != df['label_b']].copy()
        
        def assign_type(row):
            if row['label_a'] == '?' or row['label_b'] == '?':
                return 'Needs_Discussion_Unknown'
            return 'Label_Conflict'
            
        if not disagreements.empty:
            disagreements['disagreement_type'] = disagreements.apply(assign_type, axis=1)
            
        return disagreements

    def analyze(self, output_dir):
        """执行全量一致性分析并输出报告"""
        os.makedirs(output_dir, exist_ok=True)
        df_double = self.load_and_merge_data()
        
        if df_double.empty:
            print("⚠️ 未发现可计算的双标结果。")
            return
            
        df_double.to_csv(os.path.join(output_dir, "double_annotations.csv"), index=False)
        
        summary = self.calculate_metrics(df_double)
        summary['rq_breakdown'] = {}
        for rq, group in df_double.groupby('research_query_id'):
            summary['rq_breakdown'][str(rq)] = self.calculate_metrics(group)
            
        with open(os.path.join(output_dir, "agreement_summary.json"), 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=4, ensure_ascii=False)
            
        df_disagreements = self.generate_disagreements(df_double)
        cols_order = [
            'pair_id', 'research_query_id', 
            'annotator_a', 'label_a', 'confidence_a', 'reason_a',
            'annotator_b', 'label_b', 'confidence_b', 'reason_b',
            'disagreement_type'
        ]
        df_disagreements = df_disagreements[[c for c in cols_order if c in df_disagreements.columns]]
        df_disagreements.to_csv(os.path.join(output_dir, "disagreements.csv"), index=False)