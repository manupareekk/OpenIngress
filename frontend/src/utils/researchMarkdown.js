const CHART_RE = /<!--\s*chart:\s*([\w-]+)\s*-->/g

export function parseResearchMarkdown(raw) {
  const blocks = []
  let lastIndex = 0
  let match

  const chartPositions = []
  CHART_RE.lastIndex = 0
  while ((match = CHART_RE.exec(raw)) !== null) {
    chartPositions.push({ index: match.index, id: match[1], length: match[0].length })
  }

  if (!chartPositions.length) {
    appendSections(blocks, raw)
    return blocks
  }

  chartPositions.forEach((pos) => {
    const textBefore = raw.slice(lastIndex, pos.index).trim()
    if (textBefore) appendSections(blocks, textBefore)
    blocks.push({ type: 'chart', chartId: pos.id })
    lastIndex = pos.index + pos.length
  })

  const tail = raw.slice(lastIndex).trim()
  if (tail) appendSections(blocks, tail)

  return blocks
}

function appendSections(blocks, text) {
  const cleaned = text.replace(/^---\s*$/gm, '').trim()
  const parts = cleaned.split(/(?=^#{3,4}\s+)/m).filter((p) => p.trim())
  if (!parts.length) {
    blocks.push({ type: 'p', html: formatInline(text.trim()) })
    return
  }

  parts.forEach((part) => {
    const lines = part.trim().split('\n')
    const headingMatch = lines[0].match(/^#{3,4}\s+(.+)$/)
    if (headingMatch) {
      const heading = headingMatch[1].trim().replace(/^\*\*|\*\*$/g, '')
      const body = lines.slice(1).join('\n').trim()

      if (/^bibliography$/i.test(heading)) {
        blocks.push({ type: 'h2', text: 'Bibliography' })
        if (body) {
          blocks.push({ type: 'bibliography', sections: parseBibliographyBody(body) })
        }
        return
      }

      blocks.push({ type: 'h2', text: heading })
      if (body) appendBody(blocks, body)
    } else {
      appendBody(blocks, part.trim())
    }
  })
}

function parseBibliographyBody(body) {
  const sections = []
  let current = { title: '', entries: [] }

  const flush = () => {
    if (!current.title && !current.entries.length) return
    sections.push({ title: current.title, entries: [...current.entries] })
    current = { title: '', entries: [] }
  }

  const chunks = body.trim().split(/\n\n+/)
  for (const chunk of chunks) {
    const trimmed = chunk.trim()
    if (!trimmed) continue

    const h5 = trimmed.match(/^#####\s+(.+)$/m)
    const boldOnly = trimmed.match(/^\*\*(.+?)\*\*$/s)
    if (h5) {
      flush()
      current.title = h5[1].trim()
      continue
    }
    if (boldOnly && !trimmed.includes('\n-') && !trimmed.includes('\n*')) {
      flush()
      current.title = boldOnly[1].trim()
      continue
    }

    if (isBibliographyListChunk(trimmed)) {
      const entries = extractBibliographyEntries(trimmed)
      current.entries.push(...entries.map(formatInline))
      continue
    }
  }

  flush()

  if (!sections.length && body.trim()) {
    sections.push({
      title: '',
      entries: extractBibliographyEntries(body).map(formatInline)
    })
  }

  return sections
}

function isBibliographyListChunk(text) {
  return /^(?:[-*]\s+|\d+\.\s+)/m.test(text)
}

function extractBibliographyEntries(text) {
  return text
    .split(/\n/)
    .map((line) => line.replace(/^(?:[-*]|\d+\.)\s+/, '').trim())
    .filter(Boolean)
}

function appendBody(blocks, body) {
  const chunks = body.split(/\n\n+/)
  chunks.forEach((chunk) => {
    const trimmed = chunk.trim()
    if (!trimmed) return

    const firstLine = trimmed.split('\n')[0]
    const h3Line = firstLine.match(/^\*\*(.+?)\*\*$/)
    if (h3Line && trimmed === firstLine) {
      blocks.push({ type: 'h3', text: h3Line[1] })
      return
    }

    if (
      trimmed.startsWith('**Perception') ||
      trimmed.startsWith('**Cognitive') ||
      trimmed.startsWith('**Action')
    ) {
      blocks.push({ type: 'h3', text: trimmed.replace(/^\*\*|\*\*$/g, '') })
      return
    }

    if (trimmed.startsWith('*   **') || trimmed.startsWith('* ') || trimmed.startsWith('- ')) {
      const items = trimmed
        .split(/\n/)
        .map((line) => line.replace(/^(?:[-*]|\d+\.)\s+/, '').trim())
        .filter(Boolean)
      blocks.push({ type: 'ul', items: items.map(formatInline) })
      return
    }

    if (/^\d+\.\s+\*\*/.test(trimmed)) {
      const start = Number(trimmed.match(/^(\d+)\.\s+/)?.[1] || 1)
      const items = trimmed
        .split(/\n(?=\d+\.\s+)/)
        .map((line) => line.replace(/^\d+\.\s+/, '').trim())
        .filter(Boolean)
      blocks.push({ type: 'ol', start, items: items.map(formatInline) })
      return
    }

    if (trimmed.includes('|') && /^\|.+\|/m.test(trimmed) && trimmed.includes('---')) {
      blocks.push(parseMarkdownTable(trimmed))
      return
    }

    if (trimmed.startsWith('$$')) {
      const math = trimmed.replace(/^\$\$|\$\$$/g, '').trim()
      blocks.push({ type: 'math', text: math })
      return
    }

    blocks.push({ type: 'p', html: formatInline(trimmed) })
  })
}

function formatInline(text) {
  const codeSpans = []
  const withCodePlaceholders = text.replace(/\\?`([^`]+?)\\?`/g, (_match, code) => {
    const index = codeSpans.push(`<code>${escapeHtml(code)}</code>`) - 1
    return `\u0000CODE_${index}\u0000`
  })

  return withCodePlaceholders
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>')
    .replace(/\n/g, ' ')
    .replace(/\u0000CODE_(\d+)\u0000/g, (_match, index) => codeSpans[Number(index)] || '')
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function parseMarkdownTable(chunk) {
  const lines = chunk
    .trim()
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.startsWith('|'))
  const headers = lines[0]
    .split('|')
    .map((c) => c.trim())
    .filter(Boolean)
    .map(formatInline)
  const rows = lines.slice(2).map((line) =>
    line
      .split('|')
      .map((c) => c.trim())
      .filter(Boolean)
      .map(formatInline)
  )
  return { type: 'table', headers, rows }
}
