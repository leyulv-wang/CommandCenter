async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const detail = await response.text()
    let parsedDetail: unknown
    try {
      parsedDetail = (JSON.parse(detail) as { detail?: unknown }).detail
    } catch {
      parsedDetail = undefined
    }
    if (typeof parsedDetail === 'string') {
      throw new Error(parsedDetail)
    }
    throw new Error(detail || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export { request }
