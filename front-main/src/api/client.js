export const API_BASE_URL = 'http://127.0.0.1:8000'

/**
 * Базовая функция для запросов к бэкенду.
 * Ничего не знает о дизайне и компонентах, только про HTTP.
 */
export async function apiRequest(path, options = {}) {
  const url = `${API_BASE_URL}${path}`

  const defaultHeaders = {
    'ngrok-skip-browser-warning': 'true' // Обход ngrok warning для всех запросов
  }

  // Если передаём JSON — добавляем Content-Type, но не трогаем FormData
  if (!(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json'
  }

  try {
    const response = await fetch(url, {
      ...options,
      method: options.method || 'GET', // Используем метод из options, или GET по умолчанию
      headers: {
        ...defaultHeaders,
        ...(options.headers || {})
      },
    })

    if (!response.ok) {
      const text = await response.text().catch(() => '')
      const error = new Error(`API request failed with status ${response.status}`)
      error.status = response.status
      error.body = text
      
      // Специальная обработка для ngrok ошибок
      if (response.status === 503 || text.includes('ngrok') || text.includes('ERR_NGROK')) {
        error.isNgrokError = true
        error.message = 'Бэкенд недоступен. Возможно, ngrok туннель упал. Проверьте, что бэкенд запущен и ngrok туннель активен.'
      }
      
      throw error
    }

    // Пытаемся распарсить JSON, если есть тело
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return response.json()
    }

    return response.text()
  } catch (fetchError) {
    // Обработка CORS и сетевых ошибок
    if (fetchError.name === 'TypeError' && fetchError.message.includes('Failed to fetch')) {
      const error = new Error('Не удалось подключиться к бэкенду. Проверьте, что бэкенд запущен и ngrok туннель активен.')
      error.isNetworkError = true
      error.originalError = fetchError
      throw error
    }
    
    // Если это уже наша ошибка, пробрасываем дальше
    if (fetchError.isNgrokError || fetchError.isNetworkError) {
      throw fetchError
    }
    
    // Для остальных ошибок
    throw fetchError
  }
}


