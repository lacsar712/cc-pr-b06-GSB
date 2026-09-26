const TOKEN_KEY = 'print_token'
const ROLE_KEY = 'print_role'
const NAME_KEY = 'print_name'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY) || ''
}

export function getUserName() {
  return localStorage.getItem(NAME_KEY) || ''
}

export function saveAuth({ access_token, role, username }) {
  localStorage.setItem(TOKEN_KEY, access_token)
  localStorage.setItem(ROLE_KEY, role)
  localStorage.setItem(NAME_KEY, username)
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
  localStorage.removeItem(NAME_KEY)
}

export async function api(path, options = {}) {
  const token = getToken()
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || '请求失败')
  return data
}
