import axios from 'axios'
import { getAccessToken } from './authToken'

export const apiBaseURL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, '') || '/api/ingress'

export function createApiClient(timeout = 0) {
  const client = axios.create({ baseURL: apiBaseURL, timeout })

  client.interceptors.request.use((config) => {
    const token = getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  return client
}

export const api = createApiClient()
export const apiLong = createApiClient(180_000)
