import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs/promises'

// Credential requests must never be serialized into a Playwright trace/HAR.
test.use({baseURL:'http://127.0.0.1:8877',trace:'off',screenshot:'off'})
const keys={openai:'sk-test-'+'OPENAI'+'-'+'SUPER-SECRET',deepseek:'sk-test-'+'DEEPSEEK'+'-'+'SUPER-SECRET'}

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
