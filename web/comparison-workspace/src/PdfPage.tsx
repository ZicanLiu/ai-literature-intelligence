import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfPage({url,page}:{url:string;page:number}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [error,setError] = useState('')
  const [loading,setLoading] = useState(true)
  useEffect(() => {
    let cancelled = false
    let render: {cancel:()=>void}|undefined
    setError('');setLoading(true)
    const task = getDocument({url})
    ;(async () => {
      const pdf = await task.promise
      const p = await pdf.getPage(page+1)
      if(cancelled || !canvas.current) return
      const viewport = p.getViewport({scale:1.25})
      const context = canvas.current.getContext('2d')!
      canvas.current.width=viewport.width;canvas.current.height=viewport.height
      render = p.render({canvas:canvas.current,canvasContext:context,viewport})
      await (render as unknown as {promise:Promise<void>}).promise
      if(!cancelled)setLoading(false)
    })().catch(()=>{if(!cancelled){setError('此页无法渲染，请下载原 PDF 阅读。');setLoading(false)}})
    return()=>{cancelled=true;render?.cancel();void task.destroy()}
  },[url,page])
  return <div className="pdf-page">{loading && <span className="muted">正在加载 PDF 页…</span>}{error && <p role="alert">{error}</p>}<canvas ref={canvas} aria-label={`PDF 第 ${page+1} 页`}/></div>
}
