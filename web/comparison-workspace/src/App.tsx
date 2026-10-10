import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronDown, CircleHelp, Clock3, Download, FileText, FolderOpen, GitCompareArrows, History, Layers3, LoaderCircle, LockKeyhole, Maximize2, PencilLine, Pin, Plus, RefreshCw, Search, ShieldCheck, Sparkles, TriangleAlert, Upload, X } from 'lucide-react'
import type { Capabilities, Correction, Evidence, Finding, Observation, Paper, Project, Result, Run, Summary } from './types'
import AISettings from './AISettings'
import EvidenceQuote from './EvidenceQuote'
import { CandidateDetails, CandidateOverview, candidateLabel } from './ResultCandidates'
import AnalysisReview, { analysisOptions, type AnalysisCheck } from './AnalysisReview'
const PdfCanvas = lazy(()=>import('./PdfPage'))
function PdfPage(props:{url:string;page:number}) { return <Suspense fallback={<p className="muted">正在加载 PDF 查看器…</p>}><PdfCanvas {...props}/></Suspense> }

const questions = [
  ['reported','报告数字','哪篇论文报告的 Accuracy 最高？'],
  ['protocol','相同协议','在相同评估协议下，A 是否优于 B？'],
  ['efficiency','资源效率','哪种方法的资源效率更高？'],
]
const categories = [
  ['SUPPORTED_PREREQUISITE','已支持前提',CheckCircle2,'supported','原文中已定位的相关前提'],
  ['BLOCKER','阻断',TriangleAlert,'blocker','与当前问题要求冲突的条件'],
  ['UNRESOLVED','未决',CircleHelp,'unresolved','证据缺口或待复核的解释'],
  ['ALLOWED_HETEROGENEITY','允许差异',GitCompareArrows,'allowed','当前问题下可保留的背景差异'],
] as const
const states:Record<string,string> = {PRESENT:'已报告',NOT_LOCATED:'未定位',AMBIGUOUS:'有歧义',NOT_APPLICABLE:'不适用'}
const modeLabels:Record<string,string> = {demo:'合成演示',api:'AI 草稿',import:'导入草稿',manual:'手工记录'}
const runLabels:Record<string,string> = {QUEUED:'排队中',RUNNING:'运行中',COMPLETED:'已完成',STALE:'STALE · 输入已变更',FAILED:'失败',INTERRUPTED:'重启已中断'}
type Editor = { kind:string; paper?:Paper; obs?:Observation; finding?:Finding; targetId?:string }
type Selection = { evidenceIds:string[]; observation?:Observation; finding?:Finding; paper?:Paper }

async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const res = await fetch('/api'+path,{...options,headers: options.body instanceof FormData ? {} : {'Content-Type':'application/json',...options.headers}})
  if(!res.ok) {
    const data = await res.json().catch(()=>({detail:'请求失败，请稍后重试。'}))
    throw new Error(res.status===409 ? '项目已更新或文件已上传。已刷新数据，请检查后重试。' : typeof data.detail==='string' ? data.detail : '字段无效，请检查输入。')
  }
  return res.json()
}
const post = (body:unknown):RequestInit => ({method:'POST',body:JSON.stringify(body)})
const short = (value:string, count=52) => value.length>count ? value.slice(0,count)+'…' : value
const paperTitle = (paper:Paper) => paper.identity.title?.value || paper.source.original_filename

function handleIssueText(run:Run) {
  const d=run.validation_diagnostic
  if(d?.rule!=='evidence_handle_identity')return ''
  return d.handle_issue==='UNKNOWN_HANDLE'?'UNKNOWN_HANDLE · 引用未在本次请求声明'
    :d.handle_issue==='DUPLICATE_HANDLE'?'DUPLICATE_HANDLE · 同一候选重复引用'
    :'UNKNOWN · 旧记录未区分未知或重复 handle'
}
function parseIssueText(run:Run) {
  const d=run.validation_diagnostic
  if(d?.rule!=='structured_output_schema')return ''
  const labels={JSON_SYNTAX:'JSON 语法解析失败',SCHEMA_VALIDATION:'结构或字段约束校验失败',PARSER_INPUT:'解析输入不是可用的 JSON 文本类型',PARSER_FAILURE:'解析入口异常'}
  return d.parse_issue?`${d.parse_issue} · ${labels[d.parse_issue]}`:'UNKNOWN · 旧记录未保存解析分类；不能由 $ 推断 JSON 错误或截断'
}
function completedFailureContext(run:Run) {
  if(run.status!=='FAILED'||run.provider_status!=='completed')return ''
  const token=(name:string)=>typeof run.token_usage?.[name]==='number'?run.token_usage[name]:'未知'
  return `请求已发送；服务报告输入 ${token('input_tokens')} / 输出 ${token('output_tokens')} tokens，费用以服务方账单为准。本次${run.stage==='extraction'?'候选':'分析'}未入库，原项目已保留。先核对研究问题、论文与版本，可手工整理；不要仅因本地失败重复付费调用。`
}
function runFailureText(run:Run) {
  const reason=run.failure_reason||'运行失败，输入已保留。'
  return `${run.provider_status==='completed'?'提供方已完成，本地校验失败。':''}${reason} ${completedFailureContext(run)} ${handleIssueText(run)} ${parseIssueText(run)}${run.validation_diagnostic?' 校验位置：'+run.validation_diagnostic.field_path:''}`
}

function RunDiagnostics({run}:{run:Run}) {
  const diagnostic=run.validation_diagnostic
  const identity=(value:{paper_id:string|null;source_snapshot_id:string|null})=>`paper ${value.paper_id||'未知'} · source ${value.source_snapshot_id||'未知'}`
  return <>
    <small>提供方状态 {run.provider_status||'未知'}{run.incomplete_details?.reason?' · 未完成原因 '+run.incomplete_details.reason:''}</small>
    {completedFailureContext(run)&&<p>{completedFailureContext(run)}</p>}
    {handleIssueText(run)&&<p>{handleIssueText(run)}</p>}
    {parseIssueText(run)&&<p>{parseIssueText(run)}</p>}
    {diagnostic&&<div className="run-diagnostic"><p>本地校验失败 · {diagnostic.field_path} · 规则 {diagnostic.rule}</p>{diagnostic.expected.length>0&&<p>预期：{diagnostic.expected.map(identity).join('；')}</p>}{diagnostic.returned&&<p>返回：{identity(diagnostic.returned)}（未知表示未匹配项目身份，原始值未保存）</p>}</div>}
  </>
}

function Badge({mode, corrected=false}:{mode:string;corrected?:boolean}) {
  return <span className={`badge ${corrected?'manual':mode}`}>{corrected?<PencilLine size={11}/>:mode==='demo'?<Sparkles size={11}/>:<FileText size={11}/>} {corrected?'用户修订':modeLabels[mode]||mode}</span>
}
function Status({state}:{state:string}) {
  return <span className={`state ${state==='PRESENT'?'present':''}`}>{state==='PRESENT'?<Check size={12}/>:<CircleHelp size={12}/>} {states[state]}</span>
}
function Modal({title,children,onClose,wide=false}:{title:string;children:React.ReactNode;onClose:()=>void;wide?:boolean}) {
  useEffect(()=>{const listener=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose()};document.addEventListener('keydown',listener);return()=>document.removeEventListener('keydown',listener)},[onClose])
  return <div className="modal-backdrop" onClick={onClose}><section role="dialog" aria-modal="true" aria-label={title} className={`modal ${wide?'wide':''}`} onClick={e=>e.stopPropagation()}><header><h2>{title}</h2><button className="icon-button" aria-label="关闭窗口" onClick={onClose}><X size={19}/></button></header>{children}</section></div>
}

export default function App() {
  const [project,setProject]=useState<Project|null>(null)
  const [summaries,setSummaries]=useState<Summary[]>([])
  const [caps,setCaps]=useState<Capabilities|null>(null)
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [runId,setRunId]=useState<string|null>(null)
  const [error,setError]=useState('')
  const [toast,setToast]=useState('')
  const [editor,setEditor]=useState<Editor|null>(null)
  const [selection,setSelection]=useState<Selection|null>(null)
  const [pinIds,setPinIds]=useState<string[]>([])
  const [showPins,setShowPins]=useState(false)
  const [showHistory,setShowHistory]=useState(false)
  const [showAISettings,setShowAISettings]=useState(false)
  const [filter,setFilter]=useState('')
  const [audit,setAudit]=useState('SUPPORTED_PREREQUISITE')
  const [runMode,setRunMode]=useState('manual')
  const [exportOpen,setExportOpen]=useState(false)
  const [candidate,setCandidate]=useState<{paperId:string;resultId:string}|null>(null)
  const [analysisCheck,setAnalysisCheck]=useState<AnalysisCheck|null>(null)
  const startingRun=useRef(false)
  const navigate=useCallback(async(id?:string, pushHistory=true)=>{
    setLoading(true);setError('');setSelection(null);setPinIds([]);setCandidate(null);setAnalysisCheck(null);setRunId(null)
    if(pushHistory)window.history.pushState({},'',id?`?project=${id}`:'/');setExportOpen(false)
    try {
      if(id) {const p=await api<Project>('/projects/'+id);setProject(p);setRunMode(p.demo_question?'demo':'manual')}
      else {setProject(null);setSummaries(await api<Summary[]>('/projects'))}
    } catch(e) {setError((e as Error).message)} finally {setLoading(false)}
  },[])
  useEffect(()=>{
    void api<Capabilities>('/capabilities').then(setCaps).catch(e=>setError(e.message))
    void navigate(new URLSearchParams(window.location.search).get('project')||undefined,false)
    const pop=()=>void navigate(new URLSearchParams(window.location.search).get('project')||undefined,false)
    window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop)
  },[navigate])
  useEffect(()=>{if(toast){const timer=setTimeout(()=>setToast(''),3500);return()=>clearTimeout(timer)}},[toast])
  useEffect(()=>{if(caps&&!caps.api_enabled&&runMode==='api')setRunMode('manual')},[caps,runMode])
  useEffect(()=>{
    if(!runId || !project) return
    let stop=false, timer:ReturnType<typeof setTimeout>
    const poll=async()=>{
      try {
        const r=await api<Run>('/runs/'+runId)
        if(stop)return
        if(['QUEUED','RUNNING'].includes(r.status)){timer=setTimeout(poll,600);return}
        const updated=await api<Project>('/projects/'+project.id)
        if(stop)return
        setProject(updated);setRunId(null);setSelection(null)
        if(r.status==='FAILED')setError(runFailureText(r))
        else setToast(r.status==='STALE'?'旧运行已保存，未覆盖新输入。':r.stage==='extraction'?'候选已保存，请查看结果候选并选择活动目标。':'对照记录已保存。')
      }catch(e){if(!stop){setError((e as Error).message);setRunId(null)}}
    }
    void poll();return()=>{stop=true;clearTimeout(timer)}
  },[runId,project?.id])

  const mutate=async(path:string,body:Record<string,unknown>,method='POST')=>{
    if(!project)return
    setBusy(true);setError('')
    try {
      const p=await api<Project>('/projects/'+project.id+path,{method,body:JSON.stringify({...body,expected_revision:project.revision})})
      setProject(p);setEditor(null);setSelection(null);setToast('已保存到本地')
      return p
    }catch(e){
      setError((e as Error).message)
      setProject(await api<Project>('/projects/'+project.id))
    }finally{setBusy(false)}
  }
  const openDemo=async(key='reported')=>{
    setBusy(true);setError('')
    try{const d=await api<{project_id:string;run_id:string}>('/demo',post({question_key:key,expected_revision:0}));await navigate(d.project_id);setRunId(d.run_id)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const startRun=async(stage='analyses',check?:AnalysisCheck)=>{
    if(!project||startingRun.current||runId)return
    if(check&&(!caps?.api_enabled||runMode!=='api'||check.project.id!==project.id||check.project.revision!==project.revision||JSON.stringify(check.options)!==JSON.stringify(analysisOptions(caps)))){
      setAnalysisCheck(null);setError('项目或 AI 配置已变化，请重新检查比较对象。');return
    }
    startingRun.current=true;setBusy(true);setError('');setAnalysisCheck(null)
    try{
      if(check){
        const current=await api<Capabilities>('/capabilities')
        setCaps(current)
        if(!current.api_enabled||JSON.stringify(check.options)!==JSON.stringify(analysisOptions(current))){setError('AI 配置已变化，请重新检查比较对象。');return}
      }
      const r=await api<{run_id:string}>('/projects/'+project.id+'/'+stage,post({expected_revision:check?.project.revision??project.revision,mode:runMode}));setRunId(r.run_id)
    }
    catch(e){
      setError((e as Error).message)
      const refreshed=await Promise.allSettled([api<Project>('/projects/'+project.id),api<Capabilities>('/capabilities')])
      if(refreshed[0].status==='fulfilled')setProject(refreshed[0].value)
      if(refreshed[1].status==='fulfilled')setCaps(refreshed[1].value)
    }finally{startingRun.current=false;setBusy(false)}
  }
  const previewCandidate=(paper:Paper,result:Result)=>{setAnalysisCheck(null);setCandidate({paperId:paper.id,resultId:result.id})}
  const upload=async(file:File)=>{
    if(!project)return
    const form=new FormData();form.append('file',file);form.append('expected_revision',String(project.revision))
    setBusy(true);setError('')
    try{setProject(await api<Project>('/projects/'+project.id+'/papers',{method:'POST',body:form}));setEditor(null);setToast('PDF 已上传；请选择或创建目标结果。')}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const openObservation=(o:Observation,paper:Paper)=>setSelection({evidenceIds:o.evidence_ids,observation:o,paper})
  const inspectFinding=(f:Finding)=>setSelection({evidenceIds:f.evidence_ids,finding:f})
  const download=(format:string)=>{
    if(!project)return
    const link=document.createElement('a');link.href=`/api/projects/${project.id}/exports/${format}`;link.download='comparison-report';link.click();setExportOpen(false);setToast('报告已导出，包含来源与修订记录。')
  }
  const activeIds=new Set(project?.papers.map(p=>p.active_target_result_id))
  const observations=project?.observations.filter(o=>activeIds.has(o.result_id))||[]
  const dimensions=Array.from(new Set(observations.map(o=>o.dimension)))
  const ready=project && project.papers.length>=2 && project.papers.every(p=>p.active_target_result_id)
  const pending=!!runId
  const corrected=(id:string)=>!!project?.corrections.some(c=>c.target_id===id)
  const currentFindings=project?.findings.filter(f=>!f.stale)||[]
  const staleFindings=project?.findings.filter(f=>f.stale)||[]
  const candidateCount=project?.papers.reduce((count,p)=>count+p.results.length,0)||0
  const candidatePaper=project?.papers.find(p=>p.id===candidate?.paperId)
  const candidateResult=candidatePaper?.results.find(r=>r.id===candidate?.resultId)

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={()=>void navigate()}><span className="brand-mark"><Layers3 size={24}/></span><span>SRTP<span className="brand-sub">科研比较工作台</span></span></button>
      <div className="side-label">WORKSPACE</div>
      <button className={`nav-item ${!project?'active':''}`} onClick={()=>void navigate()}><FolderOpen size={18}/>项目概览{!project&&<span className="nav-dot"/>}</button>
      {project&&<button className="nav-item active"><GitCompareArrows size={18}/>当前对照</button>}
      <button className="nav-item" onClick={()=>void openDemo()} disabled={busy}><Sparkles size={18}/>合成演示<ArrowUpRight size={14} className="push"/></button>
      <div className="side-note"><BookOpen size={20}/><strong>从问题出发，回到原文</strong><p>让每一次比较都有明确的目标、条件与证据。</p></div>
      <div className="sidebar-bottom"><span className="local-dot"/><strong>本地工作空间</strong><span>项目与源文件保存在此设备</span><small>v0.1.1 · 单用户</small></div>
    </aside>
    <main className={`main ${project?'workspace-main':''}`}>
      <header className="topbar"><div className="breadcrumb"><span>工作空间</span><span>/</span><strong>{project?'文献对照':'项目概览'}</strong></div><div className="topbar-right"><button className="button small" disabled={!caps} onClick={()=>setShowAISettings(true)}><LockKeyhole size={13}/>AI 设置</button><span className="pill">{caps?.api_enabled?(caps.selected_provider==='openai'?'OpenAI':'DeepSeek')+' Live':'Live 关闭'}</span><span className="avatar">研</span></div></header>
      {error&&<div className="notice error" role="alert"><TriangleAlert size={17}/><span>{error}</span><button aria-label="关闭错误" onClick={()=>setError('')}><X size={15}/></button></div>}
      {toast&&<div className="toast" role="status"><CheckCircle2 size={16}/>{toast}</div>}
      {loading?<div className="loading-screen"><LoaderCircle className="spin" size={26}/><p>正在载入本地工作空间…</p></div>:!project?<>
        <div className="dashboard-head"><div><div className="eyebrow"><span/> SCIENTIFIC COMPARISON WORKSPACE</div><h1>让文献比较，有据可循。</h1><p>围绕一个具体问题，整理实验条件、追溯原文，留下可复核的判断。</p></div><button className="button primary" onClick={()=>setEditor({kind:'create'})}><Plus size={17}/>新建比较项目</button></div>
        <section className="demo-hero">
          <div className="hero-copy"><span className="hero-label"><Sparkles size={14}/>3 分钟体验 · 无需配置</span><h2>三篇文献。<br/>一个问题。一张对照表。</h2><p>相同的指标，不一定来自相同的条件。<br/>从报告数字到评估协议，看看问题如何改变判断。</p><button className="button primary" onClick={()=>void openDemo()} disabled={busy}>体验合成演示<ArrowRight size={17}/></button><small>SYNTHETIC DEMO / NOT RESEARCH EVIDENCE</small></div>
          <div className="hero-visual" aria-hidden="true"><div className="mini-heading"><GitCompareArrows size={15}/> 条件与证据 <span>3 PAPERS</span></div><div className="mini-matrix"><div/><b>Aster</b><b>Birch</b><b>Cedar</b><span>Accuracy</span><strong>92<span>%</span></strong><strong>89<span>%</span></strong><strong>91<span>%</span></strong><span>评估划分</span><em>Random</em><em className="different">Temporal</em><em>Random</em><span>资源信息</span><i><Check size={15}/></i><i><CircleHelp size={15}/></i><i><CircleHelp size={15}/></i></div><div className="mini-evidence"><span className="paper-token">B</span><div><b>差异是否阻断，取决于问题</b><p>定位到原文 · PDF 第 2 页</p></div><ArrowUpRight size={17}/></div></div>
        </section>
        <div className="section-heading"><h2>最近项目 <span>{summaries.length.toString().padStart(2,'0')}</span></h2><label className="search"><Search size={15}/><input aria-label="搜索项目" placeholder="搜索项目或比较问题" value={filter} onChange={e=>setFilter(e.target.value)}/></label></div>
        <div className="project-list">{summaries.filter(p=>(p.title+p.question).toLowerCase().includes(filter.toLowerCase())).map(p=><button className="project-row" key={p.id} onClick={()=>void navigate(p.id)}><span className="project-icon"><GitCompareArrows size={22}/></span><div><h3>{p.title}{p.synthetic&&<Badge mode="demo"/>}</h3><p>{p.question}</p></div><span className="row-meta">{p.paper_count} 篇文献<span>{new Date(p.updated_at).toLocaleDateString('zh-CN')}</span></span><ArrowUpRight size={19}/></button>)}
        {!summaries.length&&<div className="empty-projects"><FolderOpen size={27}/><h3>从一个具体的比较问题开始</h3><p>添加 2–10 篇 PDF，选择目标结果。没有 API Key 也能手工整理、修订和导出。</p><button className="text-button" onClick={()=>setEditor({kind:'create'})}>创建第一个项目 <ArrowRight size={15}/></button></div>}</div>
        <div className="dashboard-footer"><ShieldCheck size={15}/><span>源文件保留原字节 · 每次修订留下记录 · 默认离线</span><span className="push">用于辅助阅读与复核</span></div>
      </>:<>
        <section className="project-head"><button className="text-button back" onClick={()=>void navigate()}><ArrowLeft size={14}/>全部项目</button><div className="project-title-line"><div><div className="eyebrow">COMPARISON PROJECT <span className="revision">REV {project.revision.toString().padStart(2,'0')}</span></div><h1>{project.title}</h1></div><div className="export-wrapper"><button className="button" onClick={()=>setExportOpen(!exportOpen)}><Download size={16}/>导出报告<ChevronDown size={13}/></button>{exportOpen&&<div className="dropdown">{['markdown','json','csv'].map(f=><button key={f} onClick={()=>download(f)}>{f==='markdown'?'Markdown 报告':f.toUpperCase()+' 数据'}<Download size={13}/></button>)}</div>}</div></div>
          <div className="question-box"><span className="question-icon"><CircleHelp size={20}/></span><div><span className="caption">当前比较问题</span><h2>{project.question}</h2><p>{project.scope || '未设置额外范围 / 规则'}</p></div><button className="icon-button" title="编辑问题与范围" aria-label="编辑问题与范围" onClick={()=>setEditor({kind:'project'})}><PencilLine size={16}/></button></div>
          {project.papers.some(p=>p.synthetic)&&<div className="demo-strip"><span><Sparkles size={13}/><strong>含合成演示材料</strong> · SYNTHETIC DEMO / NOT RESEARCH EVIDENCE</span>{project.demo_question&&<label>切换问题 <select aria-label="演示问题" value={project.demo_question} onChange={e=>{void mutate('',{demo_question:e.target.value},'PATCH');setSelection(null)}} disabled={busy||pending}>{questions.map(q=><option key={q[0]} value={q[0]}>{q[1]}</option>)}</select></label>}</div>}
        </section>
        {project.analysis_stale&&<div className="notice stale"><Clock3 size={17}/><span><b>STALE · 输入已变更</b>　旧分析或判断仅供追溯。请重新运行分析，并逐条复核过期的手工判断。</span></div>}
        <div className="workspace-toolbar"><div><h2>文献对照矩阵</h2><span>{project.papers.length} 篇文献 <span className="dot-separator">·</span> {project.papers.filter(p=>p.active_target_result_id).length}/{project.papers.length} 已选择目标</span></div><div className="toolbar-actions"><button className="button small" onClick={()=>setEditor({kind:'upload'})} disabled={busy||project.papers.length>=10}><Plus size={15}/>添加 PDF</button><select aria-label="分析模式" className="mode-select" value={runMode} onChange={e=>setRunMode(e.target.value)}><option value="manual">手工模式</option>{project.demo_question&&<option value="demo">合成演示</option>}{caps?.api_enabled&&<option value="api">{caps.selected_provider==='deepseek'?'DeepSeek':'OpenAI'} API</option>}</select>{runMode==='api'&&<button className="button small" disabled={pending||busy||project.papers.length<2} onClick={()=>void startRun('extractions')}><Sparkles size={14}/>提取候选结果</button>}<button className="button primary small" onClick={()=>runMode==='api'&&caps?setAnalysisCheck({project,options:analysisOptions(caps)}):void startRun()} disabled={!ready||pending||busy}>{pending?<LoaderCircle size={15} className="spin"/>:<RefreshCw size={15}/>} {pending?'正在整理…':runMode==='manual'?'保存手工对照':'运行分析'}</button></div></div>
        <p className="mode-hint">{runMode==='manual'?'手工模式：保存你填写的结果与观察，不调用模型。上传 PDF 不会自动产生候选；可在下方手工添加。':runMode==='demo'?'合成演示：使用内置自制材料，不调用外部模型，不代表真实科研验证。':'Live 模式：提取与分析是两次独立的显式请求，可能分别计费；不会自动连续运行。'}{caps?.hard_offline&&' 当前为硬离线启动，Live 和连接测试均被禁用；可完整体验演示与手工审查。'}</p>
        {runMode==='api'&&<div className="notice api-notice"><Sparkles size={15}/><span>运行将把本项目的问题、PDF 提取文本与相关结构化记录发送至 {caps?.selected_provider==='deepseek'?'DeepSeek':'OpenAI'} API。当前输入为提取文本，无 PDF 页图 / 表格视觉输入。费用未知；返回结果为待复核草稿。</span></div>}
        {project.papers.length>0&&<CandidateOverview project={project} onPreview={previewCandidate}/>}
        <div className={`workspace-grid ${selection?'has-inspector':''}`}><section className="comparison-area">
          <div className="matrix-card">{project.papers.length?<div className="matrix-scroll"><table className="comparison-table"><colgroup><col className="dimension-col"/>{project.papers.map(p=><col key={p.id}/>)}</colgroup><thead><tr><th><span className="caption">比较维度</span><p>每篇文献选择<br/>一个活动目标结果</p></th>{project.papers.map((p,i)=><th key={p.id}><div className="paper-heading"><span className={`paper-token tone-${i%3}`}>{String.fromCharCode(65+i)}</span><span className="caption">{p.synthetic?'SYNTHETIC PAPER':'USER PDF'}</span><button className="icon-button push" title="阅读源 PDF" aria-label={`阅读论文 ${i+1}`} onClick={()=>setSelection({paper:p,evidenceIds:[]})}><BookOpen size={14}/></button></div><h3 title={paperTitle(p)}>{paperTitle(p)}</h3><div className="source-state"><CheckCircle2 size={12}/>{p.source.parse_status==='TEXT_EXTRACTED'?'文本已提取':'文本提取受限'} · {p.source.page_count} 页</div><select aria-label={`论文 ${i+1} 活动结果`} value={p.active_target_result_id||''} onChange={e=>void mutate('/papers/'+p.id+'/active-result',{result_id:e.target.value||null},'PATCH')} disabled={busy}><option value="">选择目标结果…</option>{p.results.map((r,index)=><option key={r.id} value={r.id}>{candidateLabel(p,r,index)}</option>)}</select><div className="candidate-note"><span>{p.results.length} 个候选</span>{p.results.length>0&&<button aria-label={`查看论文 ${i+1} 候选详情`} onClick={()=>previewCandidate(p,p.results.find(r=>r.id===p.active_target_result_id)||p.results[0])}>候选详情</button>}{p.active_target_result_id&&<button aria-label={`修订论文 ${i+1} 目标结果`} onClick={()=>setEditor({kind:'correct-result',paper:p,targetId:p.active_target_result_id!})}><PencilLine size={11}/>修订</button>}<button onClick={()=>setEditor({kind:'result',paper:p})}><Plus size={11}/>手工添加</button></div></th>)}</tr></thead><tbody>
            {dimensions.map(d=><tr key={d}><th>{d}</th>{project.papers.map(p=>{const o=observations.find(o=>o.result_id===p.active_target_result_id&&o.dimension===d);return <td key={p.id}>{o?<button className={`matrix-cell ${selection?.observation?.id===o.id?'selected':''}`} onClick={()=>openObservation(o,p)}><Status state={o.state}/><div className={`cell-value ${d==='报告结果'?'result-number':''}`}>{o.state==='PRESENT'?(d==='报告结果'&&o.value.match(/\d+(\.\d+)?%/)?.[0]||o.value):o.value||'原文证据尚未定位'}</div><div className="cell-footer"><Badge mode={o.provenance.mode} corrected={corrected(o.id)}/><span>{o.evidence_ids.length>0&&o.evidence_ids.every(id=>project.evidence.find(e=>e.id===id)?.locator_status==='LOCATED')?<><FileText size={11}/>原文已定位</>:<><CircleHelp size={11}/>待复核</>}</span></div></button>:<button className="empty-cell" disabled={!p.active_target_result_id} onClick={()=>setEditor({kind:'observation',paper:p})}><Plus size={13}/>添加观察</button>}</td>})}</tr>)}
            {!dimensions.length&&<tr><td colSpan={project.papers.length+1}><div className="matrix-empty"><FileText size={25}/><h3>{candidateCount?'已有结果候选，尚未生成比较观察':'先定位目标结果，再整理比较条件'}</h3><p>{candidateCount?`上方已保存 ${candidateCount} 个候选和 ${project.evidence.length} 条 Evidence。先预览并选择活动目标，再手工添加观察或显式运行分析。`:'真实 PDF 的离线模式支持手工字段；不会生成未经分析的 AI 结果。'}</p>{ready&&<button className="button small" onClick={()=>setEditor({kind:'observation',paper:project.papers[0]})}><Plus size={14}/>添加第一个观察</button>}</div></td></tr>}
          </tbody></table></div>:<div className="matrix-empty"><Upload size={28}/><h3>添加用于比较的论文</h3><p>2–10 篇文本 PDF · 每篇最多 25 MiB / 100 页</p><button className="button primary" onClick={()=>setEditor({kind:'upload'})}>上传 PDF</button></div>}
          <footer className="matrix-footer"><span><FileText size={13}/>点击单元格查看原文与修订</span><button className="text-button" disabled={!ready} onClick={()=>setEditor({kind:'observation',paper:project.papers[0]})}><Plus size={13}/>添加比较维度</button></footer></div>
          <section className="audit-area"><div className="section-heading"><div><h2>问题相关的审查</h2><p>条件差异的意义，由当前问题与证据决定。</p></div><button className="text-button" disabled={!ready} onClick={()=>setEditor({kind:'finding'})}><Plus size={14}/>记录手工判断</button></div><div className="audit-tabs" role="tablist">{categories.map(([key,label,Icon,tone])=><button role="tab" aria-selected={audit===key} className={`audit-tab ${tone} ${audit===key?'active':''}`} key={key} onClick={()=>setAudit(key)}><Icon size={16}/><span>{label}</span><b>{currentFindings.filter(f=>f.category===key).length}</b></button>)}</div><div className="finding-list">{currentFindings.filter(f=>f.category===audit).map(f=><button className="finding-card" key={f.id} onClick={()=>inspectFinding(f)}><div><Badge mode={f.provenance.mode} corrected={corrected(f.id)}/><span className="caption">{f.affected_result_ids.length} 个目标结果</span></div><p>{f.explanation}</p><footer><span><FileText size={12}/>{f.evidence_ids.length} 条证据 · 点击复核</span><ArrowUpRight size={16}/></footer></button>)}{!currentFindings.some(f=>f.category===audit)&&<div className="empty-findings"><CircleHelp size={19}/><p>尚无{categories.find(c=>c[0]===audit)?.[1]}记录。空白不表示条件已通过。</p></div>}</div>{staleFindings.length>0&&<details className="stale-findings"><summary>STALE · 历史判断（{staleFindings.length}）</summary><p className="form-note">以下记录保留原有问题和目标，仅供追溯；复核后可通过修订确认。</p>{staleFindings.map(f=><button className="finding-card" key={f.id} onClick={()=>inspectFinding(f)}><div><Badge mode={f.provenance.mode} corrected={corrected(f.id)}/><span className="caption">STALE</span></div><p>{f.explanation}</p><footer>原范围：{f.scope}</footer></button>)}</details>}</section>
        </section>
        <aside className={`inspector ${selection?'is-open':''}`}>
          <header><div><span className="inspector-icon"><FileText size={16}/></span><h2>证据检查器</h2></div><button className="icon-button close-inspector" aria-label="关闭证据检查器" onClick={()=>setSelection(null)}><X size={17}/></button></header>
          {selection?<Inspector project={project} selection={selection} pinIds={pinIds} onPin={id=>{setPinIds(prev=>prev.includes(id)?prev.filter(x=>x!==id):[...prev.slice(-1),id]);setToast('已更新并排证据')}} onEdit={()=>setEditor(selection.observation?{kind:'correct-observation',obs:selection.observation}:{kind:'correct-finding',finding:selection.finding})} onEvidence={paper=>setEditor({kind:'evidence',paper})} onIdentity={paper=>setEditor({kind:'identity',paper})}/>:<div className="inspector-empty"><div className="evidence-illustration"><FileText size={31}/><Search size={19}/></div><h3>每个判断，都能回到原文</h3><p>点击矩阵单元格或审查记录，<br/>查看 PDF 页码、精确片段与来源。</p><div className="inspector-tips"><span><CheckCircle2 size={14}/>核对原文是否支持解释</span><span><Pin size={14}/>固定两条证据并排阅读</span><span><PencilLine size={14}/>修订保留原记录和理由</span></div></div>}
          {pinIds.length>0&&<div className="pinned-bar"><Pin size={14}/><span>已固定 {pinIds.length}/2 条</span><button className="text-button" disabled={pinIds.length!==2} onClick={()=>setShowPins(true)}>并排查看<Maximize2 size={13}/></button></div>}
        </aside></div>
        <footer className="workspace-footer"><span><ShieldCheck size={14}/>定位证明原文出现，解释需复核</span><button className="text-button" onClick={()=>setShowHistory(true)}><History size={14}/>运行与修订记录</button><button className="text-button" onClick={()=>setEditor({kind:'import'})}><Upload size={14}/>导入结构化分析</button><span className="push"><Check size={13}/>本地已保存 · Revision {project.revision}</span></footer>
      </>}
    </main>
    {showAISettings&&caps&&<Modal title="AI 设置" onClose={()=>setShowAISettings(false)}><AISettings caps={caps} onChange={setCaps}/></Modal>}
    {candidatePaper&&candidateResult&&project&&<Modal title="候选详情 · 只读预览" wide onClose={()=>setCandidate(null)}><CandidateDetails project={project} paper={candidatePaper} result={candidateResult} disabled={busy||pending} onChoose={()=>void mutate('/papers/'+candidatePaper.id+'/active-result',{result_id:candidateResult.id},'PATCH').then(p=>{if(p)setCandidate(null)})} renderEvidence={e=><EvidenceCard project={project} evidence={e} onPin={()=>setPinIds(prev=>prev.includes(e.id)?prev.filter(id=>id!==e.id):[...prev.slice(-1),e.id])} pinned={pinIds.includes(e.id)}/>}/></Modal>}
    {analysisCheck&&<Modal title="运行前检查比较对象" wide onClose={()=>setAnalysisCheck(null)}><AnalysisReview check={analysisCheck} disabled={busy||pending} onBack={()=>setAnalysisCheck(null)} onConfirm={()=>void startRun('analyses',analysisCheck)} onPreview={previewCandidate}/></Modal>}
    {editor&&<Modal title={({'create':'新建比较项目','project':'编辑问题与范围','upload':'添加论文 PDF','result':'手工创建目标结果','observation':'添加比较观察','finding':'记录问题相关判断','correct-result':'修订目标结果 · 保留原记录','correct-observation':'修订观察 · 保留原记录','correct-finding':'修订判断 · 保留原记录','evidence':'定位原文证据','identity':'修订论文身份','import':'导入预计算分析'} as Record<string,string>)[editor.kind]} onClose={()=>setEditor(null)}>
      {editor.kind==='upload'?<div className="modal-body"><div className="upload-area"><Upload size={28}/><h3>上传原始 PDF</h3><p>每篇最多 25 MiB / 100 页，不截断文件。</p><label className="button primary">选择 PDF<input aria-label="选择 PDF" type="file" accept=".pdf,application/pdf" hidden disabled={busy} onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0])}}/></label></div><p className="form-note">扫描件或提取受限的 PDF 可手工阅读和整理；v0.1 不提供 OCR。原始源文件保留原字节。</p>{busy&&<p className="muted">正在提取页面文本…</p>}</div>:<EditorForm editor={editor} project={project} busy={busy} onSave={async data=>{
        if(editor.kind==='create'){setBusy(true);try{const p=await api<Project>('/projects',post({...data,expected_revision:0}));setEditor(null);await navigate(p.id)}catch(e){setError((e as Error).message)}finally{setBusy(false)};return}
        if(!project)return
        if(editor.kind==='project')await mutate('',data,'PATCH')
        else if(editor.kind==='result')await mutate('/papers/'+editor.paper!.id+'/results',data)
        else if(editor.kind==='observation')await mutate('/observations',data)
        else if(editor.kind==='finding')await mutate('/findings',data)
        else if(editor.kind==='evidence')await mutate('/evidence',data)
        else if(editor.kind==='import'){
          try{const r=await api<{run_id:string}>('/projects/'+project.id+'/imports',post({...data,expected_revision:project.revision}));setRunId(r.run_id);setEditor(null)}
          catch(e){setError((e as Error).message)};return
        }else{
          const p=await mutate('/corrections',data)
          if(p&&selection){if(editor.obs){const o=p.observations.find(o=>o.id===editor.obs!.id);if(o)setSelection({...selection,observation:o,evidenceIds:o.evidence_ids})}else if(editor.finding){const f=p.findings.find(f=>f.id===editor.finding!.id);if(f)setSelection({...selection,finding:f,evidenceIds:f.evidence_ids})}}
        }
      }}/>}
    </Modal>}
    {showPins&&project&&<Modal title="并排阅读 · 两条原文证据" wide onClose={()=>setShowPins(false)}><div className="evidence-pair">{pinIds.map(id=><EvidenceCard key={id} project={project} evidence={project.evidence.find(e=>e.id===id)!} onPin={()=>{}} pinned/>)}</div></Modal>}
    {showHistory&&project&&<Modal title="运行与修订记录" wide onClose={()=>setShowHistory(false)}><div className="modal-body history-content"><h3>运行记录</h3><p className="form-note">每次尝试有独立运行 ID。服务重启将中断未完成任务，不会自动重试外部请求。</p>{project.runs.map(r=><div className="history-item" key={r.id}><span><Badge mode={r.mode}/> <b>{runLabels[r.status]}</b> · {r.stage==='analysis'?'比较分析':'结果提取'} · Revision {r.input_revision}</span><small>{r.provider} · 请求 {r.requested_model||'未知'} · {r.provider_reported_model?'返回 '+r.provider_reported_model:'未取得服务端返回模型'}{r.model&&!r.requested_model&&!r.provider_reported_model?' · 历史 model '+r.model+'（来源不明）':''} · reasoning {r.reasoning_effort??'服务默认'} · max_output_tokens {r.max_output_tokens??'未知'} · {r.input_modality||'—'} · {r.elapsed_seconds??'—'} s · request {r.request_id||'—'} · tokens {JSON.stringify(r.token_usage)}</small><RunDiagnostics run={r}/><code>{r.id}</code>{r.failure_reason&&<p>{r.failure_reason}</p>}</div>)}{!project.runs.length&&<p className="muted">尚无运行。手工输入已单独保存。</p>}<h3>追加修订</h3>{project.corrections.map(c=><CorrectionItem key={c.id} correction={c}/>)}{!project.corrections.length&&<p className="muted">尚无修订。</p>}</div></Modal>}
  </div>
}

function Inspector({project,selection,pinIds,onPin,onEdit,onEvidence,onIdentity}:{project:Project;selection:Selection;pinIds:string[];onPin:(id:string)=>void;onEdit:()=>void;onEvidence:(p:Paper)=>void;onIdentity:(p:Paper)=>void}) {
  const [selectedId,setSelectedId]=useState('')
  const [page,setPage]=useState(0)
  useEffect(()=>{setSelectedId(selection.evidenceIds[0]||'');setPage(0)},[selection])
  const ev=project.evidence.find(e=>e.id===selectedId)
  const paper=ev?project.papers.find(p=>p.id===ev.paper_id):selection.paper
  const changes=project.corrections.filter(c=>c.target_id===(selection.observation?.id||selection.finding?.id))
  return <div className="inspector-body">
    {(selection.observation||selection.finding)&&<div className="interpretation"><span className="caption">{selection.finding?.stale?'STALE · 历史判断':'当前记录 / 模型解释'}</span><h3>{selection.observation?.dimension||categories.find(c=>c[0]===selection.finding?.category)?.[1]}</h3><p>{selection.observation?.value||selection.finding?.explanation||'未定位原文信息；不能推断论文未报告。'}</p><div><Badge mode={(selection.observation||selection.finding)!.provenance.mode} corrected={changes.length>0}/><button className="text-button" onClick={onEdit}><PencilLine size={13}/>修订</button></div></div>}
    {selection.evidenceIds.length>1&&<label className="evidence-select">证据片段<select aria-label="选择证据片段" value={selectedId} onChange={e=>setSelectedId(e.target.value)}>{selection.evidenceIds.map((id,i)=>{const e=project.evidence.find(e=>e.id===id);const p=project.papers.find(p=>p.id===e?.paper_id);return <option key={id} value={id}>{i+1} · {p?short(paperTitle(p),24):'未知'} · 第 {(e?.page_index??0)+1} 页</option>})}</select></label>}
    {ev?<EvidenceCard key={ev.id} project={project} evidence={ev} onPin={()=>onPin(ev.id)} pinned={pinIds.includes(ev.id)}/>:<div className="no-evidence"><CircleHelp size={21}/><strong>{selection.paper?'原始论文阅读':'证据尚未定位'}</strong><p>{selection.paper?'选择页面，阅读 PDF 与提取文本，并手工创建精确引文。':'该记录没有有效定位。缺失不等于冲突，解释需要复核。'}</p></div>}
    {paper&&!ev&&<><div className="page-controls"><button className="icon-button" disabled={page===0} onClick={()=>setPage(page-1)} aria-label="上一页"><ArrowLeft size={15}/></button><span>PDF 第 {page+1} / {paper.source.page_count} 页</span><button className="icon-button" disabled={page===paper.source.page_count-1} onClick={()=>setPage(page+1)} aria-label="下一页"><ArrowRight size={15}/></button></div><PdfPage url={`/api/projects/${project.id}/papers/${paper.id}/source`} page={page}/><pre className="page-text">{paper.source.pages[page].text||'本页无可提取文本；请阅读原始 PDF。'}</pre></>}
    {paper&&<div className="source-identity"><span className="caption">论文 / 源身份</span><h3>{paperTitle(paper)}</h3>{paper.synthetic&&<span className="synthetic-text">SYNTHETIC DEMO / NOT RESEARCH EVIDENCE</span>}<dl><dt>源文件</dt><dd>{paper.source.original_filename}</dd><dt>SHA256</dt><dd title={paper.source.sha256}>{paper.source.sha256.slice(0,24)}…</dd><dt>解析工具</dt><dd>{paper.source.parser}</dd></dl>{paper.source.errors.map((e,i)=><p className="parse-error" key={i}>{e}</p>)}<div className="identity-actions"><button className="text-button" onClick={()=>onEvidence(paper)}><Plus size={13}/>定位证据</button><button className="text-button" onClick={()=>onIdentity(paper)}><PencilLine size={13}/>修订身份</button><a className="text-button" href={`/api/projects/${project.id}/papers/${paper.id}/source`} target="_blank" rel="noreferrer"><ArrowUpRight size={13}/>源 PDF</a></div></div>}
    {changes.length>0&&<div className="inspector-history"><h3><History size={14}/>修订历史</h3>{changes.map(c=><CorrectionItem key={c.id} correction={c}/>)}</div>}
    <p className="inspector-disclaimer">“原文已定位”只证明文字出现，<br/>不证明模型或用户解释正确。</p>
  </div>
}

function EvidenceCard({project,evidence:e,onPin,pinned}:{project:Project;evidence:Evidence;onPin:()=>void;pinned:boolean}) {
  const [pdf,setPdf]=useState(false)
  const paper=project.papers.find(p=>p.id===e.paper_id)!
  const page=paper.source.pages[e.page_index]
  const points=Array.from(page?.text||'')
  return <div className="evidence-card"><div className="evidence-card-top"><span className="located"><FileText size={13}/>{e.locator_status==='LOCATED'?'原文已定位':'定位无效 · 待复核'}</span><button className={`icon-button ${pinned?'pinned':''}`} title={pinned?'取消固定':'固定证据'} aria-label={pinned?'取消固定证据':'固定证据'} onClick={onPin}><Pin size={14}/></button></div><span className="caption">{short(paperTitle(paper),34)} · PDF 第 {e.page_index+1} 页</span><EvidenceQuote quote={e.quote}/>{e.review_reason&&<p className="parse-error">{e.review_reason}</p>}<details><summary>提取页面文本 · 精确片段</summary><pre className="page-text">{e.locator_status==='LOCATED'&&e.start!==null&&e.end!==null?<>{points.slice(0,e.start).join('')}<mark>{points.slice(e.start,e.end).join('')}</mark>{points.slice(e.end).join('')}</>:page?.text||'没有可用的页面文本'}</pre></details>{page&&<button className="pdf-toggle" onClick={()=>setPdf(!pdf)}><BookOpen size={14}/>{pdf?'收起 PDF 页':`查看 PDF 第 ${e.page_index+1} 页`}<ChevronDown size={14}/></button>}{pdf&&<PdfPage url={`/api/projects/${project.id}/papers/${paper.id}/source`} page={e.page_index}/>}</div>
}
function CorrectionItem({correction:c}:{correction:Correction}) {
  return <div className="correction-item"><span><PencilLine size={13}/>用户修订 · {new Date(c.timestamp).toLocaleString('zh-CN')}</span><p>{c.rationale}</p><details><summary>查看修订前 / 后原记录</summary><pre>{JSON.stringify({before:c.before,after:c.after,operator:c.operator,evidence_ids:c.evidence_ids},null,2)}</pre></details></div>
}

function EditorForm({editor:e,project:p,busy,onSave}:{editor:Editor;project:Project|null;busy:boolean;onSave:(d:Record<string,unknown>)=>Promise<void>}) {
  const [form,setForm]=useState<Record<string,string>>(():Record<string,string>=>{
    if(e.kind==='create')return {title:'',question:'',scope:''}
    if(e.kind==='project')return {title:p!.title,question:p!.question,scope:p!.scope}
    if(e.kind==='result')return {title:'',description:'',experiment_identity:''}
    if(e.kind==='correct-result'){const r=e.paper!.results.find(r=>r.id===e.targetId)!;return {title:r.title,description:r.description,experiment_identity:r.experiment_identity,rationale:''}}
    if(e.kind==='observation'||e.kind==='correct-observation')return {result_id:e.obs?.result_id||e.paper?.active_target_result_id||'',dimension:e.obs?.dimension||'',value:e.obs?.value||'',state:e.obs?.state||'PRESENT',rationale:''}
    if(e.kind==='finding'||e.kind==='correct-finding')return {category:e.finding?.category||'UNRESOLVED',scope:e.finding?.scope||p!.question,explanation:e.finding?.explanation||'',rationale:''}
    if(e.kind==='identity')return {title:e.paper!.identity.title?.value||'',doi:e.paper!.identity.doi?.value||'',rationale:''}
    if(e.kind==='evidence')return {page:'1',quote:''}
    return {document:''}
  })
  const [evidenceIds,setEvidenceIds]=useState<string[]>(e.obs?.evidence_ids||e.finding?.evidence_ids||e.paper?.results.find(r=>r.id===e.targetId)?.evidence_ids||[])
  const [affected,setAffected]=useState<string[]>(e.finding?.affected_result_ids||p?.papers.map(x=>x.active_target_result_id!).filter(Boolean)||[])
  const [localError,setLocalError]=useState('')
  const set=(key:string,value:string)=>setForm({...form,[key]:value})
  const text=(key:string,label:string,placeholder='',multiline=false,required=true)=><label>{label}{multiline?<textarea required={required} aria-label={label} rows={3} placeholder={placeholder} value={form[key]||''} onChange={x=>set(key,x.target.value)}/>:<input required={required} aria-label={label} placeholder={placeholder} value={form[key]||''} onChange={x=>set(key,x.target.value)}/>}</label>
  const paperId=e.paper?.id||p?.papers.find(x=>x.results.some(r=>r.id===(e.obs?.result_id||form.result_id)))?.id
  const evidenceOptions=p?.evidence.filter(x=>e.kind.includes('finding')?p.papers.some(paper=>affected.some(id=>paper.results.some(r=>r.id===id))&&paper.id===x.paper_id):x.paper_id===paperId)||[]
  const evidencePicker=<fieldset className="evidence-picker"><legend>关联原文证据（只显示受影响论文）</legend>{evidenceOptions.map(x=>{const index=p!.papers.findIndex(paper=>paper.id===x.paper_id);return <label key={x.id}><input type="checkbox" checked={evidenceIds.includes(x.id)} onChange={()=>setEvidenceIds(prev=>prev.includes(x.id)?prev.filter(id=>id!==x.id):[...prev,x.id])}/><span>文献 {String.fromCharCode(65+index)} · {short(paperTitle(p!.papers[index]),36)} · 第 {x.page_index+1} 页 · {short(x.quote,72)}{x.locator_status==='INVALID'&&' · 定位无效'}</span></label>})}{!evidenceOptions.length&&<p className="form-note">暂无证据。先在证据检查器中定位；无证据的判断可记录为“未决”。</p>}</fieldset>
  return <form className="editor-form" onSubmit={async event=>{
    event.preventDefault();setLocalError('')
    let data:Record<string,unknown>={}
    if(['create','project'].includes(e.kind))data={title:form.title,question:form.question,scope:form.scope}
    else if(e.kind==='result')data={title:form.title,description:form.description,experiment_identity:form.experiment_identity,evidence_ids:evidenceIds}
    else if(e.kind==='observation')data={result_id:form.result_id,dimension:form.dimension,value:form.value,state:form.state,evidence_ids:evidenceIds}
    else if(e.kind==='finding')data={category:form.category,scope:form.scope,explanation:form.explanation,affected_result_ids:affected,evidence_ids:evidenceIds}
    else if(e.kind==='evidence')data={candidate:{paper_id:e.paper!.id,source_snapshot_id:e.paper!.source.id,page_index:Number(form.page)-1,quote:form.quote}}
    else if(e.kind==='import'){try{data={document:JSON.parse(form.document)}}catch{setLocalError('JSON 无法解析，请检查格式。');return}}
    else{
      const observation=e.kind==='correct-observation'
      data={target_kind:e.kind==='identity'?'identity':e.kind==='correct-result'?'result':observation?'observation':'finding',
        target_id:e.targetId||e.paper?.id||e.obs?.id||e.finding?.id,rationale:form.rationale,evidence_ids:evidenceIds,
        after:e.kind==='identity'?{title:form.title,doi:form.doi}:e.kind==='correct-result'?{title:form.title,description:form.description,experiment_identity:form.experiment_identity,evidence_ids:evidenceIds}:observation?{dimension:form.dimension,value:form.value,state:form.state,evidence_ids:evidenceIds}:{category:form.category,scope:form.scope,explanation:form.explanation,evidence_ids:evidenceIds}}
    }
    await onSave(data)
  }}>
    {['create','project'].includes(e.kind)&&<>{text('title','项目名称','例如：光谱分类方法的评估条件对照')}{text('question','具体比较问题','例如：在相同测试集与指标定义下，哪个方法报告的结果更高？',true)}{text('scope','范围 / 规则','可选：数据集、实验范围、必须满足的条件',true,false)}<p className="form-note">一个项目围绕一个具体问题，每篇论文只激活一个结果。修改问题会使旧分析变为 STALE。</p></>}
    {(e.kind==='result'||e.kind==='correct-result')&&<>{text('title','结果名称','例如：主实验 / 表 2 第 3 行')}{text('experiment_identity','实验 / 结果身份','例如：Dataset X，random split，主模型')}{text('description','结果描述','保留结果的原始单位与含义',true,false)}{evidencePicker}</>}
    {e.kind.includes('observation')&&<>{e.kind==='observation'&&<label>目标结果<select value={form.result_id} onChange={x=>{set('result_id',x.target.value);setEvidenceIds([])}} aria-label="目标结果">{p?.papers.filter(paper=>paper.active_target_result_id).map(paper=><option key={paper.id} value={paper.active_target_result_id!}>{short(paperTitle(paper),48)} · {paper.results.find(r=>r.id===paper.active_target_result_id)?.title}</option>)}</select></label>}{text('dimension','比较维度','例如：指标定义 / 评估划分 / 资源预算')}<label>信息状态<select aria-label="信息状态" value={form.state} onChange={x=>set('state',x.target.value)}>{Object.entries(states).map(([key,val])=><option key={key} value={key}>{val}</option>)}</select></label>{text('value','字段值 / 说明','未定位不等于论文未报告',true,form.state==='PRESENT')}{evidencePicker}</>}
    {e.kind.includes('finding')&&<><label>审查类别<select aria-label="审查类别" value={form.category} onChange={x=>set('category',x.target.value)}>{categories.map(c=><option key={c[0]} value={c[0]}>{c[1]}</option>)}</select></label>{text('scope','问题相关范围','',true)}{text('explanation','解释与理由','明确说明条件如何影响当前问题',true)}{e.kind==='finding'&&<fieldset><legend>受影响的活动结果</legend>{p?.papers.filter(p=>p.active_target_result_id).map(paper=><label className="check-label" key={paper.id}><input type="checkbox" checked={affected.includes(paper.active_target_result_id!)} onChange={()=>{setAffected(prev=>prev.includes(paper.active_target_result_id!)?prev.filter(id=>id!==paper.active_target_result_id):[...prev,paper.active_target_result_id!]);setEvidenceIds([])}}/>{short(paperTitle(paper),54)}</label>)}</fieldset>}{evidencePicker}<p className="form-note">差异不能自动视为阻断。阻断、支持与允许差异须关联已定位的原文证据。</p></>}
    {e.kind==='evidence'&&<><p className="form-note">将精确引文复制自提取页面文本。页码按 PDF 第一页起算；重复或不存在的引文会标为待复核。</p><label>PDF 页码<input required type="number" min={1} max={e.paper!.source.page_count} aria-label="PDF 页码" value={form.page} onChange={x=>set('page',x.target.value)}/></label>{text('quote','精确引文','保留空格与标点',true)}<details><summary>查看当前页提取文本</summary><pre className="page-text">{e.paper!.source.pages[Number(form.page)-1]?.text||'此页文本不可用'}</pre></details></>}
    {e.kind==='identity'&&<>{text('title','论文标题','保留原始语言')}{text('doi','DOI','可选',false,false)}</>}
    {(e.kind.startsWith('correct')||e.kind==='identity')&&<>{text('rationale','修订理由','说明为何改动，以及依据',true)}<p className="form-note">原始模型记录不会覆盖。此次修订作为新的用户记录追加保存。</p></>}
    {e.kind==='import'&&<><p className="form-note">先下载当前身份模板，填写 analysis。导入将校验问题、Revision、源 SHA256 / ID 与活动结果；匹配后仍属于待复核草稿。</p><a className="text-button" href={`/api/projects/${p!.id}/import-template`} download="comparison-import-template.json"><Download size={14}/>下载当前身份模板</a><label className="button small">读取 JSON 文件<input hidden type="file" accept=".json" aria-label="读取 JSON 文件" onChange={async x=>{if(x.target.files?.[0])set('document',await x.target.files[0].text())}}/></label>{text('document','结构化 JSON','',true)}</>}
    {localError&&<p role="alert" className="parse-error">{localError}</p>}
    <footer><button type="submit" className="button primary" disabled={busy}>{busy?<LoaderCircle className="spin" size={16}/>:<Check size={16}/>}保存{e.kind.startsWith('correct')?'修订':e.kind==='import'?'并导入':''}</button></footer>
  </form>
}
