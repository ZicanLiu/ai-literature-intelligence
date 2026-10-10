import type { Capabilities, Paper, Project, Result } from './types'
import { ResultSummary } from './ResultCandidates'

export function analysisOptions(caps:Capabilities) {
  const settings=caps.providers[caps.selected_provider]
  return {provider:caps.selected_provider,model:settings.model,effort:settings.reasoning_effort||settings.reasoning_defaults?.analysis||'服务默认',budget:settings.output_budget_defaults?.analysis??12000}
}
export type AnalysisCheck={project:Project;options:ReturnType<typeof analysisOptions>}

export default function AnalysisReview({check,onBack,onConfirm,onPreview,disabled}:{check:AnalysisCheck;onBack:()=>void;onConfirm:()=>void;onPreview:(paper:Paper,result:Result)=>void;disabled:boolean}) {
  const {project,options}=check
  const activeIds=new Set(project.papers.map(p=>p.active_target_result_id))
  const unresolved=project.observations.filter(o=>activeIds.has(o.result_id)&&o.state!=='PRESENT')
  return <div className="modal-body analysis-review">
    <p className="caption">将使用 Revision {project.revision} · {options.provider} / {options.model||'未配置'} · reasoning {options.effort} · max_output_tokens {options.budget}</p>
    <h3>本次比较问题</h3><p className="review-question">{project.question}</p><p className="form-note">范围：{project.scope||'未设置额外范围'}</p>
    <div className="review-targets">{project.papers.map((paper,i)=>{
      const result=paper.results.find(r=>r.id===paper.active_target_result_id)
      return <article className="review-target" key={paper.id}><h4>论文 {i+1} · {paper.identity.title?.value||paper.source.original_filename}</h4>{result?<><h5>{result.title}</h5><ResultSummary project={project} result={result}/><button className="text-button" onClick={()=>onPreview(paper,result)}>查看该候选与原文</button></>:<p className="parse-error">活动目标缺失，请返回选择。</p>}</article>
    })}</div>
    <div className="review-cautions"><h3>需要人工注意的条件</h3><p>核对比较对象、指标与单位、数据集与划分、训练和检索/解码设置，以及表头、脚注和 caveat。性能实验与架构说明可能属于不同目标；名称或指标相同也不能证明可比。</p>
      {unresolved.length?<ul>{unresolved.map(o=><li key={o.id}>{o.dimension}：{o.value||'尚未确认'}</li>)}</ul>:<p>{project.observations.length?'已有观察也需逐条复核，不能由“已报告”推定科学支持。':'尚未生成比较观察；以上条件尚未由本次比较核查。'}</p>}
      <p>无法确认的条件应保留未决。SOURCE_LOCATED 仅表示原文出现；科学支持与独立人工确认仍需另行审阅。</p></div>
    <p className="parse-error">确认后会发送论文提取文本及项目记录，可能产生 API 费用。这里只检查对象，不调用额外模型；失败不自动重试，原项目保留。</p>
    <footer><button className="button" onClick={onBack} disabled={disabled}>返回修改目标</button><button className="button primary" onClick={onConfirm} disabled={disabled}>确认对象并运行一次分析</button></footer>
  </div>
}
