import { randomUUID } from 'node:crypto'
import { writeFile } from 'node:fs/promises'

const api = 'http://127.0.0.1:8000'
const ui = 'http://127.0.0.1:5173/'
const debuggerUrl = 'http://127.0.0.1:9222'
const advance = process.argv.includes('--advance')
const screenshotPath = process.argv.find((value, index) => index > 1 && value.endsWith('.png')) ?? '/private/tmp/awt-module9-workspace.png'

async function post(path, body) {
  const response = await fetch(`${api}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`)
  return response.json()
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url)
    socket.addEventListener('open', () => resolve(socket), { once: true })
    socket.addEventListener('error', reject, { once: true })
  })
}

async function main() {
  const [studentId, taskId, sessionId] = [randomUUID(), randomUUID(), randomUUID()]
  await post('/students', { id: studentId, grade: 8, learning_goal: 'Describe an experience clearly' })
  await post('/tasks', {
    id: taskId, prompt: 'Write about a memorable school day.', genre: 'narrative',
    grade: 8, required_points: ['event', 'feeling'],
  })
  await post('/sessions', { id: sessionId, student_id: studentId, task_id: taskId })

  const tabResponse = await fetch(`${debuggerUrl}/json/new?${encodeURIComponent(ui)}`, { method: 'PUT' })
  if (!tabResponse.ok) throw new Error(`Chrome debugging endpoint: ${tabResponse.status}`)
  const tab = await tabResponse.json()
  const socket = await connect(tab.webSocketDebuggerUrl)
  const pending = new Map()
  let nextId = 0
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data)
    if (!message.id) return
    const entry = pending.get(message.id)
    if (!entry) return
    pending.delete(message.id)
    if (message.error) entry.reject(new Error(message.error.message))
    else entry.resolve(message.result)
  })
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++nextId
      pending.set(id, { resolve, reject })
      socket.send(JSON.stringify({ id, method, params }))
    })
  }
  function waitForEvent(method) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        socket.removeEventListener('message', listener)
        reject(new Error(`Chrome event timed out: ${method}`))
      }, 10000)
      function listener(event) {
        const message = JSON.parse(event.data)
        if (message.method !== method) return
        clearTimeout(timer)
        socket.removeEventListener('message', listener)
        resolve(message)
      }
      socket.addEventListener('message', listener)
    })
  }
  async function reload() {
    const loaded = waitForEvent('Page.loadEventFired')
    await send('Page.reload', { ignoreCache: true })
    await loaded
  }
  async function evaluate(expression) {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
    return result.result.value
  }
  const pause = duration => new Promise(resolve => setTimeout(resolve, duration))
  async function until(expression) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        if (await evaluate(expression)) return
      } catch (error) {
        if (!/navigated|Execution context/i.test(String(error))) throw error
      }
      await pause(150)
    }
    throw new Error(`Browser condition timed out: ${expression}`)
  }

  try {
    await send('Page.enable')
    await send('Runtime.enable')
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
    await until('document.readyState === "complete"')
    await evaluate(`localStorage.setItem('awt.activeSession', ${JSON.stringify(JSON.stringify({ studentId, sessionId }))})`)
    await reload()
    await until('document.readyState === "complete" && document.querySelector(".workspace-heading h1")?.textContent === "审题" && Boolean(document.querySelector("[aria-label=\\"审题卡\\"]"))')
    await pause(100)
    const before = await evaluate('document.querySelector(".workspace-heading h1")?.textContent')
    if (before !== '审题') throw new Error(`Unexpected first stage: ${before}`)
    await reload()
    await until('document.readyState === "complete" && document.querySelector(".workspace-heading h1")?.textContent === "审题" && Boolean(document.querySelector("[aria-label=\\"学习状态面板\\"]"))')
    await pause(100)
    const after = await evaluate('document.querySelector(".workspace-heading h1")?.textContent')
    if (after !== '审题') throw new Error(`Unexpected restored stage: ${after}`)
    const restored = await evaluate('Boolean(document.querySelector("[aria-label=\\"审题卡\\"]")) && Boolean(document.querySelector("[aria-label=\\"学习状态面板\\"]"))')
    if (!restored) {
      const labels = await evaluate('Array.from(document.querySelectorAll("[aria-label]")).map(element => element.getAttribute("aria-label"))')
      throw new Error(`Stage components did not restore after refresh: ${JSON.stringify(labels)}`)
    }
    const capture = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
    await writeFile(screenshotPath, Buffer.from(capture.data, 'base64'))
    const result = { before, after, restored, screenshotPath, sessionId, studentId }
    if (advance) {
      const start = await post(`/sessions/${sessionId}/turn`, {
        student_id: studentId, submission: { kind: 'start', request_id: randomUUID() },
      })
      if (start.stage !== 'prompt_analysis') throw new Error(`Unexpected start stage: ${start.stage}`)
      const turn = await post(`/sessions/${sessionId}/turn`, {
        student_id: studentId,
        submission: {
          kind: 'response', request_id: randomUUID(),
          prompt_analysis: {
            audience: 'classmates', purpose: 'describe a memory', genre: 'narrative',
            required_points: ['event', 'feeling'], tense: 'past', person: 'first',
            constraints: 'describe my own experience',
          },
        },
      })
      if (turn.stage !== 'first_draft') throw new Error(`Unexpected next stage: ${turn.stage}`)
      await reload()
      await until('document.readyState === "complete" && document.querySelector(".workspace-heading h1")?.textContent === "初稿" && Boolean(document.querySelector("[aria-label=\\"作文编辑器\\"]"))')
      const nextStage = await evaluate('document.querySelector(".workspace-heading h1")?.textContent')
      const nextCapture = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
      const nextScreenshotPath = screenshotPath.replace(/\.png$/, '-first-draft.png')
      await writeFile(nextScreenshotPath, Buffer.from(nextCapture.data, 'base64'))
      Object.assign(result, { nextStage, nextScreenshotPath, evaluationVerdict: turn.evaluation_verdict })
    }
    console.log(JSON.stringify(result))
  } finally {
    socket.close()
  }
}

await main()
