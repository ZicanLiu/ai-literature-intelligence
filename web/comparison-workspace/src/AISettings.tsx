import { useState } from 'react'
import type { AIProvider, Capabilities } from './types'

export default function AISettings({caps,onChange}:{caps:Capabilities;onChange:(caps:Capabilities)=>void}) {
  const [provider,setProvider]=useState<AIProvider>(caps.selected_provider)
  const [model,setModel]=useState(caps.providers[provider].model||'')
  const [key,setKey]=useState('')
  const [effort,setEffort]=useState(caps.providers[provider].reasoning_effort||'')
  const [consent,setConsent]=useState(caps.providers[provider].consent_acknowledged)
  const [live,setLive]=useState(caps.live_enabled)
  const [busy,setBusy]=useState(false)
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  const name=provider==='openai'?'OpenAI':'DeepSeek'
  const settings=caps.providers[provider]
  async function request(path:string,method:string,body?:unknown) {
    const result=await fetch('/api/ai-settings'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
    const data=await result.json()
    if(!result.ok)throw new Error(typeof data.detail==='string'?data.detail:'设置无效，请检查输入。')
    return data
  }
  async function act(action:()=>Promise<void>) {
    setBusy(true);setError('');setMessage('')
    try{await action()}catch(e){setLive(caps.live_enabled);setError((e as Error).message)}finally{setKey('');setBusy(false)}
  }
  async function save(live_enabled?:boolean) {
    const updated:Capabilities=await request('','PATCH',{provider,...(key?{api_key:key}:{}),...(model?{model}:{}),...(provider==='deepseek'?{reasoning_effort:effort||null}:{}),...(live_enabled===undefined?{}:{live_enabled}),acknowledge:consent})
    onChange(updated)
    setLive(updated.live_enabled)
    return updated
  }
  return <div className="editor-form ai-settings">
    <label>AI 服务<select aria-label="AI 服务" value={provider} disabled={busy} onChange={e=>{
      const next=e.target.value as AIProvider
      setKey('');setMessage('');setError('')
      void act(async()=>{
        const updated:Capabilities=await request('','PATCH',{provider:next})
        onChange(updated);setLive(updated.live_enabled);setProvider(next);setModel(updated.providers[next].model||'');setEffort(updated.providers[next].reasoning_effort||'');setConsent(updated.providers[next].consent_acknowledged)
      })
    }}><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option></select></label>
    <p className="credential-status">{name} · {({none:'未配置',environment:'环境变量已配置',session:'本次会话已配置'})[settings.credential_source]}</p>
    <label>API Key<input type="password" aria-label="API Key" value={key} onChange={e=>setKey(e.target.value)} autoComplete="off" placeholder="粘贴本次会话 Key（留空保留已有配置）" disabled={busy}/></label>
    <p className="form-note">API Key 仅保存在当前本地工作台进程内存中。关闭工作台后自动清除。不会写入项目、数据库、导出文件或 Git。</p>
    <label>模型 ID{provider==='openai'?<input aria-label="模型 ID" value={model} onChange={e=>setModel(e.target.value)} placeholder="明确填写支持 Responses structured output 的模型 ID" disabled={busy}/>:<select aria-label="模型 ID" value={model} onChange={e=>setModel(e.target.value)} disabled={busy}><option value="">选择模型…</option>{settings.suggested_models.map(id=><option key={id} value={id}>{id}</option>)}</select>}</label>
    {provider==='deepseek'&&<><p className="form-note">{model==='deepseek-flash'?'deepseek-flash 支持文本与图像理解。':model==='deepseek-v4-pro'?'deepseek-v4-pro 支持文本，不支持图像理解。':'请选择当前支持的 DeepSeek 模型。'}当前工作台论文分析仍使用 PDF 提取文本。PDF 页图 / 表格视觉输入尚未启用。</p><label>思考强度（可选）<select aria-label="思考强度" value={effort} onChange={e=>setEffort(e.target.value)} disabled={busy}><option value="">服务默认</option>{['none','low','high','max'].map(value=><option key={value} value={value}>{value}</option>)}</select></label></>}
    {provider==='openai'&&<p className="form-note">模型能力取决于所选 ID；当前论文分析仅使用提取文本。OpenAI 请求设置 store=false 关闭 Responses 应用存储，这不代表服务零留存。</p>}
    {provider==='deepseek'&&<p className="form-note">DeepSeek Responses API 为无状态接口；本工作台不发送 store 参数。不据此承诺服务零留存，请查阅服务商数据政策。</p>}
    <div className="ai-actions"><button className="button" disabled={busy} onClick={()=>void act(async()=>{await save();setMessage('会话配置已保存。')})}>保存 AI 配置</button><button className="button" disabled={busy||caps.hard_offline} onClick={()=>void act(async()=>{await save();const result=await request('/test-connection','POST');setMessage(result.notice)})}>测试连接</button><button className="text-button" disabled={busy} onClick={()=>void act(async()=>{const updated=await request('/'+provider+'/key','DELETE');onChange(updated);setLive(updated.live_enabled);setConsent(false);setMessage('本次会话 Key 已清除；如有环境变量配置，将回退到环境 Key。')})}>清除本次会话 Key</button></div>
    <p className="form-note">测试连接仅显式请求认证模型列表，不发送论文、不生成内容；不能保证模型实际调用或余额可用。API 使用单独计费，与 ChatGPT / Codex 订阅分开。</p>
    <label className="check-label"><input type="checkbox" aria-label="确认数据发送" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/>我确认可将参与分析的论文提取文本、比较问题和相关结构化记录发送给 {name}。API 使用可能单独计费；请勿上传无权发送的机密、未发表或受限制材料。</label>
    <label className="check-label"><input type="checkbox" aria-label="启用本次会话 Live" checked={live} disabled={busy||caps.hard_offline||(!live&&!consent)} onChange={e=>{const enabled=e.target.checked;setLive(enabled);void act(async()=>{await save(enabled);setMessage(enabled?'Live 已启用；只有显式开始提取或分析才会发送论文。':'Live 已关闭。')})}}/>启用本次会话 Live（默认关闭）</label>
    {caps.hard_offline&&<p className="parse-error">硬离线已启用（DISABLE_LIVE_API=true），两个服务均不能请求。</p>}
    {error&&<p role="alert" className="parse-error">{error}</p>}{message&&<p role="status" className="form-note">{message}</p>}
  </div>
}
