import { useEffect, useState } from 'react'
import { api, clearAuth, getRole, getToken, getUserName, saveAuth } from './api.js'
import Signatures from './Signatures.jsx'

const STATUS_TEXT = { pending: '待处理', running: '领取中', done: '已出结论' }

function Login() {
  const [username, setUsername] = useState('printer')
  const [password, setPassword] = useState('print123456')
  const [error, setError] = useState('')

  async function enter() {
    setError('')
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      saveAuth(data)
      window.location.reload()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <h1>印刷套准复核台</h1>
      <p>提交后接口只入队。另一进程领走偏差并写结论，页面轮询到结论出现。</p>
      <p><input value={username} onChange={(e) => setUsername(e.target.value)} /></p>
      <p><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></p>
      <button onClick={enter}>登录</button>
      {error && <p className="fb-err">{error}</p>}
      <p className="muted">printer / print123456 可送复核与改派；checker / check123456 只读</p>
    </main>
  )
}

function Review() {
  const isWriter = getRole() === 'writer'
  const [rows, setRows] = useState([])
  const [sheet, setSheet] = useState('插页-02')
  const [cyan, setCyan] = useState('0.08')
  const [magenta, setMagenta] = useState('0.02')
  const [error, setError] = useState('')

  async function load() {
    setRows(await api('/api/jobs'))
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [])

  async function send() {
    setError('')
    try {
      await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({ sheet, cyan_mm: Number(cyan), magenta_mm: Number(magenta) }),
      })
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <h1>套准复核</h1>
      {isWriter && (
        <section className="card">
          <h2>送复核</h2>
          <p>
            <input value={sheet} onChange={(e) => setSheet(e.target.value)} />
            <input value={cyan} onChange={(e) => setCyan(e.target.value)} />
            <input value={magenta} onChange={(e) => setMagenta(e.target.value)} />
            <button onClick={send}>送复核</button>
          </p>
          {error && <p className="fb-err">{error}</p>}
        </section>
      )}
      <section className="card">
        <h2>任务队列</h2>
        <table>
          <thead>
            <tr><th>印张</th><th>青</th><th>品</th><th>状态</th><th>领取进程名</th><th>结论</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.sheet}</td>
                <td>{row.cyan_mm}</td>
                <td>{row.magenta_mm}</td>
                <td>{STATUS_TEXT[row.status] || row.status}</td>
                <td>{row.claimed_by || (row.assign_to ? `待领取：${row.assign_to}` : '—')}</td>
                <td>{row.verdict || '等待'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  )
}

export default function App() {
  const token = getToken()
  const [page, setPage] = useState('review')

  if (!token) return <Login />

  function leave() {
    clearAuth()
    window.location.reload()
  }

  return (
    <div>
      <nav className="topnav">
        <span className="brand">印刷套准复核台</span>
        <button className={page === 'review' ? 'active' : ''} onClick={() => setPage('review')}>
          套准复核
        </button>
        <button className={page === 'signatures' ? 'active' : ''} onClick={() => setPage('signatures')}>
          领取落款
        </button>
        <span className="spacer" />
        <span className="muted">{getUserName()}（{getRole() === 'writer' ? '印刷员' : '只读'}）</span>
        <button onClick={leave}>退出</button>
      </nav>
      {page === 'signatures' ? <Signatures /> : <Review />}
    </div>
  )
}
