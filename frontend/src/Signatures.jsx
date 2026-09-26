import { useEffect, useMemo, useState } from 'react'
import { api, getRole } from './api.js'

const STATUS_TEXT = { pending: '待处理', running: '领取中', done: '已出结论' }

function fmtTime(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { hour12: false })
}

export default function Signatures() {
  const isWriter = getRole() === 'writer'
  const [jobs, setJobs] = useState([])
  const [history, setHistory] = useState([])
  const [claimants, setClaimants] = useState([])
  const [claimFilter, setClaimFilter] = useState('')
  const [drafts, setDrafts] = useState({})
  const [feedback, setFeedback] = useState({})

  async function load() {
    const [jobRows, logRows, names] = await Promise.all([
      api('/api/jobs'),
      api('/api/reassignments'),
      api('/api/claimants'),
    ])
    setJobs(jobRows)
    setHistory(logRows)
    setClaimants(names)
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [])

  const running = useMemo(() => jobs.filter((j) => j.status === 'running'), [jobs])
  const waiting = useMemo(
    () => jobs.filter((j) => j.status === 'pending' && j.assign_to),
    [jobs],
  )
  const done = useMemo(() => jobs.filter((j) => j.status === 'done'), [jobs])

  function matchClaim(name) {
    return !claimFilter || name === claimFilter
  }

  const runningShown = running.filter((j) => matchClaim(j.claimed_by))
  // 改派后等待新进程领取的任务，按新领取名参与筛选。
  const waitingShown = waiting.filter((j) => matchClaim(j.assign_to))
  const doneShown = done.filter((j) => matchClaim(j.claimed_by))

  function draftFor(id) {
    return drafts[id] || { new_claim: '', note: '' }
  }

  function setDraft(id, patch) {
    setDrafts((prev) => ({ ...prev, [id]: { ...draftFor(id), ...patch } }))
  }

  async function reassign(job) {
    const draft = draftFor(job.id)
    setFeedback((prev) => ({ ...prev, [job.id]: { kind: 'info', text: '提交中…' } }))
    try {
      await api(`/api/jobs/${job.id}/reassign`, {
        method: 'POST',
        body: JSON.stringify(draft),
      })
      setDraft(job.id, { new_claim: '', note: '' })
      setFeedback((prev) => ({
        ...prev,
        [job.id]: { kind: 'ok', text: `已改派给「${draft.new_claim.trim()}」，待其领取后落款` },
      }))
      await load()
    } catch (err) {
      setFeedback((prev) => ({ ...prev, [job.id]: { kind: 'err', text: err.message } }))
    }
  }

  return (
    <main className="page">
      <h1>领取落款</h1>

      <section className="card">
        <h2>落款说明</h2>
        <p>
          领取进程把任务从「待处理」改为「领取中」时写入自己的领取进程名；算出套准结论写回后，
          该进程名作为落款保留在任务上。印刷员可把仍在领取中的任务改派给另一个领取名，系统记录改派履历；
          已出结论的任务不可改派。改派后任务回到待处理并指名由新进程领取，再出结论时落款为新名。
        </p>
        <p className={isWriter ? 'muted' : 'notice'}>
          {isWriter
            ? '当前为印刷员账号：可改派领取中的任务。'
            : '当前为只读账号：只能查看落款与改派履历，不能改派。'}
        </p>
      </section>

      <section className="card">
        <div className="section-head">
          <h2>在途改派区</h2>
          <label className="filter">
            按领取人筛选：
            <select value={claimFilter} onChange={(e) => setClaimFilter(e.target.value)}>
              <option value="">全部</option>
              {claimants.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
        </div>

        {runningShown.length === 0 && waitingShown.length === 0 && (
          <p className="muted">当前没有符合条件的在途任务。</p>
        )}

        <table>
          <thead>
            <tr>
              <th>印张</th><th>状态</th><th>领取进程名（落款）</th><th>{isWriter ? '改派' : ''}</th>
            </tr>
          </thead>
          <tbody>
            {waitingShown.map((j) => (
              <tr key={`w${j.id}`} className="row-wait">
                <td>{j.sheet}</td>
                <td>待处理（待新进程领取）</td>
                <td>改派给：{j.assign_to}</td>
                <td className="muted">—</td>
              </tr>
            ))}
            {runningShown.map((j) => (
              <tr key={j.id}>
                <td>{j.sheet}</td>
                <td>{STATUS_TEXT[j.status] || j.status}</td>
                <td>{j.claimed_by}</td>
                <td>
                  {isWriter ? (
                    <div className="reassign">
                      <input
                        list="claimant-list"
                        placeholder="新领取名"
                        value={draftFor(j.id).new_claim}
                        onChange={(e) => setDraft(j.id, { new_claim: e.target.value })}
                      />
                      <input
                        placeholder="改派说明（可选）"
                        value={draftFor(j.id).note}
                        onChange={(e) => setDraft(j.id, { note: e.target.value })}
                      />
                      <button
                        disabled={!draftFor(j.id).new_claim.trim()}
                        onClick={() => reassign(j)}
                      >
                        改派
                      </button>
                      {feedback[j.id] && (
                        <span className={`fb fb-${feedback[j.id].kind}`}>{feedback[j.id].text}</span>
                      )}
                    </div>
                  ) : (
                    <span className="muted">只读</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <datalist id="claimant-list">
          {claimants.map((name) => <option key={name} value={name} />)}
        </datalist>
      </section>

      <section className="card">
        <h2>已落款列表</h2>
        {doneShown.length === 0 ? (
          <p className="muted">没有符合条件的已落款任务。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>印张</th><th>状态</th><th>结论</th><th>落款（领取进程名）</th>
              </tr>
            </thead>
            <tbody>
              {doneShown.map((j) => (
                <tr key={j.id}>
                  <td>{j.sheet}</td>
                  <td>{STATUS_TEXT[j.status] || j.status}</td>
                  <td>{j.verdict || '等待'}</td>
                  <td>{j.claimed_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>改派履历</h2>
        {history.length === 0 ? (
          <p className="muted">暂无改派记录。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>时间</th><th>印张</th><th>原领取名</th><th>新领取名</th><th>改派人</th><th>说明</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td>{fmtTime(r.created_at)}</td>
                  <td>{r.sheet}（#{r.job_id}）</td>
                  <td>{r.old_claim}</td>
                  <td>{r.new_claim}</td>
                  <td>{r.reassigned_by}</td>
                  <td>{r.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  )
}
