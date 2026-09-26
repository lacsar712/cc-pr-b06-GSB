import { useEffect, useState } from 'react'

const STATUS_TEXT = { pending: '待处理', running: '领取中', done: '已出结论' }

function fmtTime(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export default function ClaimsPage({ api, role }) {
  const [claimants, setClaimants] = useState([])
  const [claimant, setClaimant] = useState('')
  const [jobs, setJobs] = useState([])
  const [history, setHistory] = useState([])
  const [targets, setTargets] = useState({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const writer = role === 'writer'

  async function loadClaimants() {
    const data = await api('/api/claimants')
    setClaimants(data.claimants || [])
  }

  async function loadClaims() {
    const query = claimant ? `?claimant=${encodeURIComponent(claimant)}` : ''
    setJobs(await api(`/api/claims${query}`))
  }

  async function loadHistory() {
    setHistory(await api('/api/reassignments'))
  }

  useEffect(() => {
    loadClaimants()
    loadHistory()
    const timer = setInterval(loadHistory, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    loadClaims()
    const timer = setInterval(loadClaims, 1000)
    return () => clearInterval(timer)
  }, [claimant])

  async function reassign(job) {
    const toName = (targets[job.id] || '').trim()
    if (!toName) {
      setError('请选择新的领取名')
      return
    }
    setError('')
    setMessage('')
    try {
      const record = await api(`/api/jobs/${job.id}/reassign`, {
        method: 'POST',
        body: JSON.stringify({ to_name: toName }),
      })
      setTargets((prev) => {
        const next = { ...prev }
        delete next[job.id]
        return next
      })
      setMessage(`任务 #${record.job_id} 已由「${record.from_name}」改派给「${record.to_name}」`)
      await Promise.all([loadClaims(), loadHistory(), loadClaimants()])
    } catch (err) {
      setError(err.message)
    }
  }

  const inTransit = jobs.filter((job) => job.status === 'running')
  const signed = jobs.filter((job) => job.status === 'done')

  return (
    <main>
      <h1>领取落款</h1>

      <section className="card">
        <h2>落款说明</h2>
        <p>
          任务由待处理变为<strong>领取中</strong>的瞬间，领取进程把自己的领取名写进落款；
          出结论后落款<strong>保留不变</strong>。领取中的任务可由印刷员改派给另一领取名，
          改派会记入履历，最终落款以改派后的新名为准；<strong>已出结论的任务不可改派</strong>。
        </p>
        {!writer && <p className="notice">当前为只读账号：只能查看落款与改派履历，不能改派。</p>}
      </section>

      <section className="card">
        <h2>按领取人筛选</h2>
        <p>
          <label>领取人：</label>
          <select value={claimant} onChange={(e) => setClaimant(e.target.value)}>
            <option value="">全部</option>
            {claimants.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <span className="hint">（同时筛在途与已落款）</span>
        </p>
      </section>

      <section className="card">
        <h2>在途改派区（领取中 {inTransit.length} 条）</h2>
        {inTransit.length === 0 ? (
          <p className="hint">暂无领取中的任务。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>编号</th><th>印张</th><th>当前领取人</th><th>状态</th>
                {writer && <th>改派</th>}
              </tr>
            </thead>
            <tbody>
              {inTransit.map((job) => (
                <tr key={job.id}>
                  <td>#{job.id}</td>
                  <td>{job.sheet}</td>
                  <td>{job.claim_name}</td>
                  <td>{STATUS_TEXT[job.status] || job.status}</td>
                  {writer && (
                    <td>
                      <select
                        value={targets[job.id] || ''}
                        onChange={(e) => setTargets((prev) => ({ ...prev, [job.id]: e.target.value }))}
                      >
                        <option value="">选择新领取名…</option>
                        {claimants
                          .filter((name) => name !== job.claim_name)
                          .map((name) => (
                            <option key={name} value={name}>{name}</option>
                          ))}
                      </select>
                      <button onClick={() => reassign(job)}>改派</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {message && <p className="ok">{message}</p>}
        {error && <p className="err">{error}</p>}
      </section>

      <section className="card">
        <h2>已落款列表（已出结论 {signed.length} 条）</h2>
        {signed.length === 0 ? (
          <p className="hint">暂无已落款的任务。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>编号</th><th>印张</th><th>落款领取人</th><th>结论</th><th>说明</th>
              </tr>
            </thead>
            <tbody>
              {signed.map((job) => (
                <tr key={job.id}>
                  <td>#{job.id}</td>
                  <td>{job.sheet}</td>
                  <td>{job.claim_name}</td>
                  <td>{job.verdict}</td>
                  <td>{job.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>改派履历（{history.length} 条）</h2>
        {history.length === 0 ? (
          <p className="hint">暂无改派记录。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>时间</th><th>任务</th><th>印张</th><th>原领取人</th><th>新领取人</th><th>操作人</th>
              </tr>
            </thead>
            <tbody>
              {history.map((record) => (
                <tr key={record.id}>
                  <td>{fmtTime(record.created_at)}</td>
                  <td>#{record.job_id}</td>
                  <td>{record.sheet}</td>
                  <td>{record.from_name}</td>
                  <td>{record.to_name}</td>
                  <td>{record.operator}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  )
}
