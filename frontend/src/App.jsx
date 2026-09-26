import { useEffect, useState } from 'react'
import ClaimsPage from './ClaimsPage.jsx'

const STATUS_TEXT = { pending: '待处理', running: '领取中', done: '已出结论' }

export default function App() {
  const [username, setUsername] = useState('printer')
  const [password, setPassword] = useState('print123456')
  const [token, setToken] = useState(localStorage.getItem('print_token') || '')
  const [role, setRole] = useState(localStorage.getItem('print_role') || '')
  const [page, setPage] = useState('queue')
  const [rows, setRows] = useState([])
  const [sheet, setSheet] = useState('插页-02')
  const [cyan, setCyan] = useState('0.08')
  const [magenta, setMagenta] = useState('0.02')
  const [error, setError] = useState('')

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function load() {
    setRows(await api('/api/jobs'))
  }

  useEffect(() => {
    if (!token) return
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [token])

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    localStorage.setItem('print_token', data.access_token)
    localStorage.setItem('print_role', data.role)
    setToken(data.access_token)
    setRole(data.role)
  }

  async function send() {
    setError('')
    try {
      await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({
          sheet,
          cyan_mm: Number(cyan),
          magenta_mm: Number(magenta),
        }),
      })
    } catch (err) {
      setError(err.message)
    }
  }

  function leave() {
    localStorage.clear()
    setToken('')
    setRole('')
  }

  if (!token) {
    return (
      <main>
        <h1>印刷套准复核台</h1>
        <p>提交后接口只入队。另一进程领走偏差并写结论，页面轮询到结论出现。</p>
        <input value={username} onChange={(e) => setUsername(e.target.value)} />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button onClick={enter}>登录</button>
        <p>printer / print123456 可送复核与改派；checker / check123456 只看落款与履历</p>
      </main>
    )
  }

  return (
    <main>
      <nav className="topnav">
        <strong>印刷套准复核台</strong>
        <button className={page === 'queue' ? 'active' : ''} onClick={() => setPage('queue')}>
          待处理队列
        </button>
        <button className={page === 'claims' ? 'active' : ''} onClick={() => setPage('claims')}>
          领取落款
        </button>
        <span className="spacer" />
        <span>{username}（{role === 'writer' ? '印刷员' : '只读'}）</span>
        <button onClick={leave}>退出</button>
      </nav>

      {page === 'claims' ? (
        <ClaimsPage api={api} role={role} />
      ) : (
        <>
          <h1>待处理队列</h1>
          {role === 'writer' && (
            <p>
              <input value={sheet} onChange={(e) => setSheet(e.target.value)} />
              <input value={cyan} onChange={(e) => setCyan(e.target.value)} />
              <input value={magenta} onChange={(e) => setMagenta(e.target.value)} />
              <button onClick={send}>送复核</button>
            </p>
          )}
          {error && <p>{error}</p>}
          <table>
            <thead>
              <tr>
                <th>印张</th><th>青</th><th>品</th><th>状态</th><th>领取人</th><th>结论</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.sheet}</td>
                  <td>{row.cyan_mm}</td>
                  <td>{row.magenta_mm}</td>
                  <td>{STATUS_TEXT[row.status] || row.status}</td>
                  <td>{row.claim_name || '—'}</td>
                  <td>{row.verdict || '等待'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  )
}
