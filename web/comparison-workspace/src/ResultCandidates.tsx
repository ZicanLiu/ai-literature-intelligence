import type { ReactNode } from 'react'
import type { Evidence, Paper, Project, Result } from './types'

const clip=(text:string,length=90)=>text.length>length?text.slice(0,length)+'…':text
const paperName=(paper:Paper)=>paper.identity.title?.value||paper.source.original_filename

// Display existing fields only; do not infer a scientific category or rewrite stored titles.
export function candidateLabel(paper:Paper,result:Result,index:number) {
  const repeated=paper.results.some(other=>other.id!==result.id&&other.title.trim()===result.title.trim())
  const name=repeated||result.title.trim()===paperName(paper).trim()
    ?result.experiment_identity||result.description||result.title:result.title
  return `${index+1} · ${clip(name)}`
}

export function ResultSummary({project,result,compact=false}:{project:Project;result:Result;compact?:boolean}) {
  const evidence=result.evidence_ids.map(id=>project.evidence.find(e=>e.id===id))
  const located=evidence.filter(e=>e?.locator_status==='LOCATED').length
  const revised=project.corrections.some(c=>c.target_kind==='result'&&c.target_id===result.id)
  const origin={api:'AI 提取草稿',import:'导入草稿',manual:'手工记录',demo:'合成演示'}[result.provenance.mode]
  return <div className={`result-summary ${compact?'compact':''}`}>
    <div className="result-badges"><span className={`badge ${result.provenance.mode}`}>{origin}</span>{revised&&<span className="badge manual">用户修订</span>}<span className="caption">独立人工确认未记录</span></div>
    <dl><dt>结果摘要</dt><dd>{result.description||'未填写摘要，请查看实验身份与来源。'}</dd><dt>实验身份</dt><dd>{result.experiment_identity||'未填写；请明确具体实验、配置或评价条件。'}</dd></dl>
    <p className="result-source-status">{located}/{evidence.length} 条关联原文已定位{located!==evidence.length?' · 含未定位或失效引用':''} · 科学支持待核查</p>
  </div>
}

export function CandidateOverview({project,onPreview}:{project:Project;onPreview:(paper:Paper,result:Result)=>void}) {
  const count=project.papers.reduce((total,p)=>total+p.results.length,0)
  return <section className="results-overview" aria-label="结果候选概览">
    <div className="section-heading"><div><h2>结果候选 <span>{count}</span></h2><p>已保存 {project.evidence.length} 条 Evidence · {project.observations.length} 条比较观察。候选摘要不等于比较矩阵或正式判断。</p></div></div>
    <div className="candidate-papers">{project.papers.map((paper,i)=>{
      const active=paper.results.find(r=>r.id===paper.active_target_result_id)
      return <article className="candidate-paper" key={paper.id}>
        <header><span className={`paper-token tone-${i%3}`}>{String.fromCharCode(65+i)}</span><h3>{paperName(paper)}</h3></header>
        <p className="active-result-label">当前活动目标：{active?candidateLabel(paper,active,paper.results.indexOf(active)):'尚未选择'}</p>
        <details open={!project.observations.length}><summary>查看 {paper.results.length} 个候选 · 点击预览后再选择</summary>
          <div className="candidate-list">{paper.results.map((result,index)=><button className={`candidate-card ${result.id===paper.active_target_result_id?'active':''}`} key={result.id} onClick={()=>onPreview(paper,result)} aria-label={`预览论文 ${i+1} 候选 ${index+1}`}>
            <div className="candidate-card-title"><strong>{candidateLabel(paper,result,index)}</strong><span>{result.id===paper.active_target_result_id?'活动目标':'只读预览'}</span></div>
            <ResultSummary project={project} result={result} compact/>
          </button>)}</div>
          {!paper.results.length&&<p className="form-note">尚无候选；可在下方手工添加，或显式启用 Live 后提取。</p>}
        </details>
      </article>
    })}</div>
  </section>
}

export function CandidateDetails({project,paper,result,onChoose,disabled,renderEvidence}:{project:Project;paper:Paper;result:Result;onChoose:()=>void;disabled:boolean;renderEvidence:(e:Evidence)=>ReactNode}) {
  return <div className="modal-body candidate-detail">
    <p className="caption">{paperName(paper)}</p><h3>{result.title}</h3>
    <ResultSummary project={project} result={result}/>
    <p className="form-note">只读预览不会改变活动目标，也不会调用模型。请区分性能实验、架构配置和数据评价条件；这里不自动判定科学可比性。</p>
    <details className="candidate-evidence"><summary>展开关联原文证据（{result.evidence_ids.length}）</summary>{result.evidence_ids.map(id=>{
      const e=project.evidence.find(e=>e.id===id)
      return e?<div key={id}>{renderEvidence(e)}</div>:<p key={id} className="parse-error">关联证据缺失，不能确认来源。</p>
    })}{!result.evidence_ids.length&&<p className="form-note">没有关联证据，需手工核查原 PDF。</p>}</details>
    <details className="result-provenance"><summary>查看来源记录</summary><dl><dt>记录者</dt><dd>{result.provenance.actor}</dd><dt>模型</dt><dd>{result.provenance.model||'无'}</dd><dt>Run</dt><dd>{result.provenance.run_id||'无'}</dd></dl><p className="form-note">用户修订不等于独立人工确认或 Human Gold；原始来源仍保留。</p></details>
    <footer><button className="button primary" disabled={disabled||paper.active_target_result_id===result.id} onClick={onChoose}>{paper.active_target_result_id===result.id?'当前活动目标':'设为活动目标'}</button></footer>
  </div>
}
