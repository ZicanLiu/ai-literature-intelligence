import { useId, useState } from 'react'

/** Presentation only: source text and canonical offsets are never rewritten. */
export default function EvidenceQuote({quote}:{quote:string}) {
  const [expanded,setExpanded] = useState(false)
  const id = useId()
  const points = Array.from(quote)
  const long = points.length > 600
  return <div className="evidence-quote">
    {long&&<p className="quote-note">{expanded?'完整原文':'原文预览 · 请展开核查完整上下文'} · {points.length} 字符</p>}
    <blockquote id={id}>{long&&!expanded?points.slice(0,360).join('')+'…':quote}</blockquote>
    {long&&<button className="text-button quote-toggle" aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(!expanded)}>{expanded?'收起':'展开完整原文'}</button>}
  </div>
}
