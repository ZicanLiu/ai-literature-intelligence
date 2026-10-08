import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs/promises'

// Credential requests must never be serialized into a Playwright trace/HAR.
test.use({baseURL:'http://127.0.0.1:8877',trace:'off',screenshot:'off'})
const keys={openai:'sk-test-'+'OPENAI'+'-'+'SUPER-SECRET',deepseek:'sk-test-'+'DEEPSEEK'+'-'+'SUPER-SECRET'}
const models={openai:'mock-openai',deepseek:'deepseek-flash'}

async function control(page:Page,action:string) {
  const response=await page.request.post('/_test/'+action)
  expect(response.ok()).toBe(true)
  return response.json()
}

async function enableProvider(page:Page,provider:keyof typeof keys) {
  await page.goto('/')
  await page.getByRole('button',{name:'AI 设置',exact:true}).click()
  await page.getByLabel('AI 服务',{exact:true}).selectOption(provider)
  await expect(page.getByLabel('AI 服务',{exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'清除本次会话 Key',exact:true}).click()
  await expect(page.getByLabel('确认数据发送',{exact:true})).not.toBeChecked()
  await page.getByLabel('API Key',{exact:true}).fill(keys[provider])
  if(provider==='openai')await page.getByLabel('模型 ID',{exact:true}).fill(models[provider])
  else await page.getByLabel('模型 ID',{exact:true}).selectOption(models[provider])
  await page.getByRole('button',{name:'保存 AI 配置',exact:true}).click()
  await expect(page.getByLabel('API Key',{exact:true})).toHaveValue('')
  await page.getByLabel('确认数据发送',{exact:true}).check()
  await page.getByLabel('启用本次会话 Live',{exact:true}).check()
  await expect(page.getByRole('status')).toContainText('Live 已启用')
}

async function demoProject(page:Page) {
  const response=await page.request.post('/api/demo',{data:{}})
  const created=await response.json()
  await expect.poll(async()=> (await (await page.request.get('/api/runs/'+created.run_id)).json()).status).toBe('COMPLETED')
  await page.goto('/?project='+created.project_id)
  await page.getByLabel('分析模式').selectOption('api')
  return created.project_id as string
}

test.afterEach(async({request})=>{
  expect((await request.post('/_test/release-worker')).ok()).toBe(true)
  expect((await request.post('/_test/scenario/success')).ok()).toBe(true)
  for(const provider of ['openai','deepseek'])await request.delete('/api/ai-settings/'+provider+'/key')
})

for(const provider of ['openai','deepseek'] as const) {
  test(`${provider} BYO setup → connection → explicit Live → PDF upload → extraction → targets → analysis → evidence → correction → export`,async({page})=>{
    const remote:string[]=[]
    const errors:string[]=[]
    page.on('pageerror',e=>errors.push(e.message))
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url())
      if(['http:','https:'].includes(url.protocol)&&url.hostname!=='127.0.0.1'){
        remote.push(url.origin);await route.abort()
      }else await route.continue()
    })
    await page.goto('/')
    await page.getByRole('button',{name:'AI 设置',exact:true}).click()
    await page.getByLabel('AI 服务',{exact:true}).selectOption(provider)
    await expect(page.getByLabel('AI 服务',{exact:true})).toBeEnabled()
    // Clear old test-process settings before this independent flow.
    await page.getByRole('button',{name:'清除本次会话 Key',exact:true}).click()
    await expect(page.getByText(provider==='openai'?'OpenAI · 未配置':'DeepSeek · 未配置',{exact:true})).toBeVisible()
    await page.getByLabel('API Key',{exact:true}).fill(keys[provider])
    if(provider==='openai')await page.getByLabel('模型 ID',{exact:true}).fill('mock-openai')
    else{
      await page.getByLabel('模型 ID',{exact:true}).selectOption('deepseek-flash')
      await page.getByLabel('思考强度',{exact:true}).selectOption('high')
      await expect(page.getByRole('dialog')).toContainText('支持文本与图像理解')
      await expect(page.getByRole('dialog')).toContainText('仍使用 PDF 提取文本')
      await expect(page.getByRole('dialog')).toContainText('视觉输入尚未启用')
    }
    await page.getByRole('button',{name:'测试连接',exact:true}).click()
    await expect(page.getByRole('dialog')).toContainText('认证与模型列表检查通过')
    await expect(page.getByLabel('API Key',{exact:true})).toHaveValue('')
    await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
    await page.getByLabel('确认数据发送',{exact:true}).check()
    await page.getByLabel('启用本次会话 Live',{exact:true}).check()
    await expect(page.getByRole('dialog')).toContainText('Live 已启用')
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    await page.getByRole('button',{name:'新建比较项目',exact:true}).click()
    await page.getByLabel('项目名称').fill(provider+' mock live workflow')
    await page.getByLabel('具体比较问题').fill('Compare reported results from extracted text')
    await page.getByRole('button',{name:'保存',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    for(const letter of ['A','B']){
      await page.getByRole('button',{name:'添加 PDF',exact:true}).click()
      await page.getByLabel('选择 PDF').setInputFiles(path.resolve(import.meta.dirname,'../../../src/comparison_workspace/demo/fixtures/paper_'+letter+'.pdf'))
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
    await page.getByLabel('分析模式').selectOption('api')
    await expect(page.locator('.api-notice')).toContainText('当前输入为提取文本')
    await page.getByRole('button',{name:'提取候选结果',exact:true}).click()
    await expect(page.getByLabel('论文 1 活动结果')).toContainText('Mock main experiment')
    for(const index of [1,2]){
      await page.getByLabel(`论文 ${index} 活动结果`).selectOption({index:1})
      await expect(page.getByLabel(`论文 ${index} 活动结果`)).toBeEnabled()
    }
    await page.getByRole('button',{name:'运行分析',exact:true}).click()
    await expect(page.locator('.matrix-cell')).toHaveCount(2)
    await expect(page.locator('.matrix-cell').first()).toContainText('原文已定位')
    await page.locator('.matrix-cell').first().click()
    await expect(page.locator('.evidence-card blockquote')).toBeVisible()
    await page.locator('.interpretation').getByRole('button',{name:'修订',exact:true}).click()
    await page.getByLabel('字段值 / 说明').fill('Reviewed mock text evidence')
    await page.getByLabel('修订理由').fill('Synthetic text inspected, original proposal retained')
    await page.getByRole('button',{name:'保存修订',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button',{name:'运行与修订记录',exact:true}).click()
    await expect(page.getByRole('dialog')).toContainText(provider)
    await expect(page.getByRole('dialog')).toContainText('EXTRACTED_TEXT')
    await expect(page.getByRole('dialog')).toContainText('req_mock_live')
    await expect(page.getByRole('dialog')).toContainText('请求 '+models[provider]+' · 返回 '+models[provider]+'-reported')
    if(provider==='deepseek')await expect(page.getByRole('dialog')).toContainText('reasoning high')
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    for(const label of ['Markdown 报告','JSON 数据','CSV 数据']){
      await page.getByRole('button',{name:'导出报告',exact:true}).click()
      const downloadPromise=page.waitForEvent('download')
      await page.getByRole('button',{name:label,exact:true}).click()
      const download=await downloadPromise
      const data=await fs.readFile((await download.path())!,'utf8')
      expect(data).toContain('Reviewed mock text evidence')
      expect(data).toContain('EXTRACTED_TEXT')
      for(const key of Object.values(keys))expect(data).not.toContain(key)
    }
    const storage=await page.evaluate(()=>({local:{...localStorage},session:{...sessionStorage},cookies:document.cookie}))
    for(const key of Object.values(keys))expect(JSON.stringify(storage)).not.toContain(key)
    expect(await page.evaluate(async()=> (await indexedDB.databases()).length)).toBe(0)
    const caps=await page.request.get('/api/capabilities')
    for(const key of Object.values(keys))expect(await caps.text()).not.toContain(key)
    await page.getByRole('button',{name:'AI 设置',exact:true}).click()
    await page.getByRole('button',{name:'清除本次会话 Key',exact:true}).click()
    await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
    await expect(page.getByLabel('API Key',{exact:true})).toHaveValue('')
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    expect(remote).toEqual([])
    expect(errors).toEqual([])
  })
}

test('legacy model value stays visible as ambiguous and never becomes a provider-reported model',async({page})=>{
  const response=await page.request.post('/api/demo',{data:{}})
  const created=await response.json()
  await expect.poll(async()=> (await (await page.request.get('/api/runs/'+created.run_id)).json()).status).toBe('COMPLETED')
  await page.route('**/api/projects/'+created.project_id,async route=>{
    const response=await route.fetch()
    const data=await response.json()
    data.runs=[{...data.runs[0],id:'run_legacy',mode:'api',provider:'openai',model:'ambiguous-legacy',requested_model:null,provider_reported_model:null}]
    await route.fulfill({response,json:data})
  })
  await page.goto('/?project='+created.project_id)
  await page.getByRole('button',{name:'运行与修订记录',exact:true}).click()
  await expect(page.getByRole('dialog')).toContainText('未取得服务端返回模型')
  await expect(page.getByRole('dialog')).toContainText('历史 model ambiguous-legacy（来源不明）')
  await expect(page.getByRole('dialog')).not.toContainText('返回 ambiguous-legacy')
})

test('switching providers isolates keys and consent; v4-pro is explicitly non-vision',async({page})=>{
  await page.goto('/')
  await page.getByRole('button',{name:'AI 设置',exact:true}).click()
  for(const provider of ['openai','deepseek'] as const){
    await page.getByLabel('AI 服务',{exact:true}).selectOption(provider)
    await expect(page.getByLabel('AI 服务',{exact:true})).toBeEnabled()
    await page.getByLabel('API Key',{exact:true}).fill(keys[provider])
    if(provider==='openai')await page.getByLabel('模型 ID',{exact:true}).fill('mock-openai')
    else await page.getByLabel('模型 ID',{exact:true}).selectOption('deepseek-v4-pro')
    await page.getByRole('button',{name:'保存 AI 配置',exact:true}).click()
    await expect(page.getByLabel('API Key',{exact:true})).toHaveValue('')
  }
  await expect(page.getByRole('dialog')).toContainText('不支持图像理解')
  await page.getByRole('button',{name:'清除本次会话 Key',exact:true}).click()
  await expect(page.getByText('DeepSeek · 未配置',{exact:true})).toBeVisible()
  await page.getByLabel('AI 服务',{exact:true}).selectOption('openai')
  await expect(page.getByText('OpenAI · 本次会话已配置',{exact:true})).toBeVisible()
  await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
  await page.getByRole('button',{name:'清除本次会话 Key',exact:true}).click()
})

for(const provider of ['openai','deepseek'] as const) {
  test(`${provider} withdrawal immediately disables authoritative UI; re-enable cannot revive queued run`,async({page})=>{
    await enableProvider(page,provider)
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    await demoProject(page)
    await control(page,'pause-worker')
    try {
      const response=page.waitForResponse(r=>r.url().endsWith('/analyses')&&r.request().method()==='POST')
      await page.getByRole('button',{name:'运行分析',exact:true}).click()
      const old=(await (await response).json()).run_id
      expect((await (await page.request.get('/api/runs/'+old)).json()).status).toBe('QUEUED')
      await page.getByRole('button',{name:'AI 设置',exact:true}).click()
      const revoke=page.waitForResponse(r=>r.url().endsWith('/ai-settings')&&r.request().postDataJSON()?.acknowledge===false)
      await page.getByLabel('确认数据发送',{exact:true}).uncheck()
      const revoked=await (await revoke).json()
      expect(revoked.providers[provider].consent_acknowledged).toBe(false)
      expect(revoked.live_enabled).toBe(false)
      expect(revoked.api_enabled).toBe(false)
      await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
      await expect(page.locator('.topbar .pill')).toHaveText('Live 关闭')
      await page.getByRole('button',{name:'保存 AI 配置',exact:true}).click()
      await expect(page.getByRole('status')).toContainText('配置已保存')
      await expect(page.getByLabel('确认数据发送',{exact:true})).not.toBeChecked()
      await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
      await page.getByLabel('确认数据发送',{exact:true}).check()
      await page.getByLabel('启用本次会话 Live',{exact:true}).check()
      await expect(page.getByRole('status')).toContainText('Live 已启用')
      await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
      await control(page,'release-worker')
      await expect.poll(async()=> (await (await page.request.get('/api/runs/'+old)).json()).status).toBe('FAILED')
      expect(await (await page.request.get('/_test/sdk-counts')).json()).toEqual({openai:0,deepseek:0,connection:0})
      await expect(page.getByRole('button',{name:'保存手工对照',exact:true})).toBeEnabled()
      await page.getByLabel('分析模式').selectOption('api')
      await page.getByRole('button',{name:'运行分析',exact:true}).click()
      await expect.poll(async()=> (await (await page.request.get('/_test/sdk-counts')).json())[provider]).toBe(1)
    } finally {await control(page,'release-worker')}
  })

  test(`${provider} failed withdrawal re-reads backend consent and Live without reporting success`,async({page})=>{
    await enableProvider(page,provider)
    await page.route('**/api/ai-settings',async route=>{
      if(route.request().postDataJSON()?.acknowledge===false)
        await route.fulfill({status:422,json:{detail:'模拟撤回失败'}})
      else await route.continue()
    })
    await page.getByLabel('确认数据发送',{exact:true}).uncheck()
    await expect(page.getByRole('alert')).toHaveText('模拟撤回失败')
    await expect(page.getByLabel('确认数据发送',{exact:true})).toBeChecked()
    await expect(page.getByLabel('启用本次会话 Live',{exact:true})).toBeChecked()
    await expect(page.getByRole('status')).toHaveCount(0)
    await page.unroute('**/api/ai-settings')
    await page.getByLabel('确认数据发送',{exact:true}).uncheck()
    await expect(page.getByRole('status')).toContainText('确认已撤回')
    await expect(page.getByLabel('启用本次会话 Live',{exact:true})).not.toBeChecked()
  })

  test(`${provider} incomplete and completed identity failures show specific safe diagnostics and retain project state`,async({page})=>{
    await enableProvider(page,provider)
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    const id=await demoProject(page)
    const before=await (await page.request.get('/api/projects/'+id)).json()
    for(const scenario of ['incomplete','identity']) {
      await control(page,'scenario/'+scenario)
      const response=page.waitForResponse(r=>r.url().endsWith('/analyses')&&r.request().method()==='POST')
      await page.getByRole('button',{name:'运行分析',exact:true}).click()
      const runId=(await (await response).json()).run_id
      await expect(page.getByRole('button',{name:'运行分析',exact:true})).toBeEnabled()
      if(scenario==='incomplete') {
        await expect(page.getByRole('alert')).toContainText('输出未完成')
        await expect(page.getByRole('alert')).toContainText('max_output_tokens')
      } else {
        await expect(page.getByRole('alert')).toContainText('提供方已完成，本地校验失败')
        await expect(page.getByRole('alert')).toContainText('$.observations[0].evidence[0].paper_id')
      }
      const run=await (await page.request.get('/api/runs/'+runId)).json()
      expect(run.status).toBe('FAILED')
      expect(run.output).toBeNull()
      expect(run.provider_status).toBe(scenario==='incomplete'?'incomplete':'completed')
      await page.getByRole('button',{name:'运行与修订记录',exact:true}).click()
      const item=page.locator('.history-item').filter({has:page.locator('code',{hasText:runId})})
      await expect(item).toContainText('提供方状态 '+run.provider_status)
      if(scenario==='incomplete') {
        expect(run.incomplete_details).toEqual({reason:'max_output_tokens'})
        await expect(item).toContainText('未完成原因 max_output_tokens')
      } else {
        expect(run.validation_diagnostic.rule).toBe('evidence_paper_ownership')
        await expect(item).toContainText('规则 evidence_paper_ownership')
        await expect(item).toContainText('预期：paper '+before.papers[0].id+' · source '+before.papers[0].source.id)
        await expect(item).toContainText('返回：paper '+before.papers[1].id+' · source '+before.papers[1].source.id)
      }
      await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
      const after=await (await page.request.get('/api/projects/'+id)).json()
      for(const field of ['revision','papers','evidence','observations','findings','corrections'])expect(after[field]).toEqual(before[field])
      const exported=await (await page.request.get('/api/projects/'+id+'/exports/json')).json()
      const saved=exported.runs.find((record:{id:string})=>record.id===runId)
      expect(saved.validation_diagnostic).toEqual(run.validation_diagnostic)
      expect(saved.incomplete_details).toEqual(run.incomplete_details)
      for(const key of Object.values(keys))expect(JSON.stringify(exported)).not.toContain(key)
    }
  })

  test(`${provider} success, pre-response failure and schema failure show and export requested/reported models separately`,async({page})=>{
    await enableProvider(page,provider)
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
    const id=await demoProject(page)
    for(const scenario of ['success','failure','schema']) {
      await control(page,'scenario/'+scenario)
      const response=page.waitForResponse(r=>r.url().endsWith('/analyses')&&r.request().method()==='POST')
      await page.getByRole('button',{name:'运行分析',exact:true}).click()
      const runId=(await (await response).json()).run_id
      await expect(page.getByRole('button',{name:'运行分析',exact:true})).toBeEnabled()
      await page.getByRole('button',{name:'运行与修订记录',exact:true}).click()
      const item=page.locator('.history-item').filter({has:page.locator('code',{hasText:runId})})
      await expect(item).toContainText('请求 '+models[provider])
      if(scenario==='failure') {
        await expect(item).toContainText('未取得服务端返回模型')
        await expect(item).not.toContainText('返回 '+models[provider])
      } else await expect(item).toContainText('返回 '+models[provider]+'-reported')
      if(scenario!=='success')await expect(item).toContainText('失败')
      await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
      const data=await (await page.request.get('/api/projects/'+id+'/exports/json')).json()
      const run=data.runs.find((r:{id:string})=>r.id===runId)
      expect(run.requested_model).toBe(models[provider])
      expect(run.provider_reported_model).toBe(scenario==='failure'?null:models[provider]+'-reported')
      const markdown=await (await page.request.get('/api/projects/'+id+'/exports/markdown')).text()
      expect(markdown).toContain('requested_model='+models[provider])
      expect(markdown).toContain(scenario==='failure'?'provider_reported_model=未取得服务端返回模型':'provider_reported_model='+models[provider]+'-reported')
      const csv=await (await page.request.get('/api/projects/'+id+'/exports/csv')).text()
      expect(csv).toContain('requested_model')
      expect(csv).toContain('provider_reported_model')
      for(const key of Object.values(keys)) {
        expect(JSON.stringify(data)+markdown+csv).not.toContain(key)
        expect(await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}))).not.toContain(key)
      }
    }
  })
}

test('DeepSeek operation defaults and explicit extraction override are visible and recorded',async({page})=>{
  await enableProvider(page,'deepseek')
  await page.getByLabel('思考强度',{exact:true}).selectOption('')
  await page.getByRole('button',{name:'保存 AI 配置',exact:true}).click()
  await expect(page.getByRole('dialog')).toContainText('结果提取 none，比较分析 high')
  await expect(page.getByRole('dialog')).toContainText('结果提取 12000，比较分析 32000')
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('配置已保存')
  await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
  await demoProject(page)
  for(const [stage,button,effort] of [['extractions','提取候选结果','none'],['analyses','运行分析','high']]) {
    const response=page.waitForResponse(r=>r.url().endsWith('/'+stage)&&r.request().method()==='POST')
    await page.getByRole('button',{name:button,exact:true}).click()
    const runId=(await (await response).json()).run_id
    await expect.poll(async()=> (await (await page.request.get('/api/runs/'+runId)).json()).status).toBe('COMPLETED')
    expect((await (await page.request.get('/api/runs/'+runId)).json()).reasoning_effort).toBe(effort)
    const budget=stage==='extractions'?12000:32000
    expect((await (await page.request.get('/api/runs/'+runId)).json()).max_output_tokens).toBe(budget)
    await expect(page.getByRole('button',{name:'运行分析',exact:true})).toBeEnabled()
    await page.getByRole('button',{name:'运行与修订记录',exact:true}).click()
    await expect(page.locator('.history-item').filter({has:page.locator('code',{hasText:runId})})).toContainText('reasoning '+effort)
    await expect(page.locator('.history-item').filter({has:page.locator('code',{hasText:runId})})).toContainText('max_output_tokens '+budget)
    await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
  }
  await page.getByRole('button',{name:'AI 设置',exact:true}).click()
  await page.getByLabel('思考强度',{exact:true}).selectOption('low')
  await page.getByRole('button',{name:'保存 AI 配置',exact:true}).click()
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('配置已保存')
  await page.getByRole('button',{name:'关闭窗口',exact:true}).click()
  const response=page.waitForResponse(r=>r.url().endsWith('/extractions')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'提取候选结果',exact:true}).click()
  const runId=(await (await response).json()).run_id
  await expect.poll(async()=> (await (await page.request.get('/api/runs/'+runId)).json()).status).toBe('COMPLETED')
  expect((await (await page.request.get('/api/runs/'+runId)).json()).reasoning_effort).toBe('low')
})
