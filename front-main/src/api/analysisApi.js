import { apiRequest, API_BASE_URL } from './client'

// Защита от повторных запусков анализа для одного docId
const activeAnalysisRequests = new Map() // docId -> { cancel: () => void, timestamp: number }

/**
 * SSE-запуск пайплайна анализа.
 * Использует fetch вместо EventSource для поддержки кастомных заголовков (обход ngrok warning).
 *
 * @param {string} docId
 * @param {{ onEvent?: (evt: any) => void, onError?: (err: any) => void, onComplete?: () => void }} callbacks
 * @returns {() => void} функция для остановки стрима
 */
export function runPipelineStream(docId, callbacks = {}) {
  const { onEvent, onError, onComplete } = callbacks

  if (!docId) {
    throw new Error('docId is required for runPipelineStream')
  }

  // Защита от повторных запусков: если для этого docId уже есть активный запрос, отменяем его
  if (activeAnalysisRequests.has(docId)) {
    const existing = activeAnalysisRequests.get(docId)
    console.warn('%c[SSE] ⚠️ Анализ уже запущен для этого docId, отменяем предыдущий запрос', 'color: #FF9800; font-weight: bold', {
      docId,
      existingTimestamp: existing.timestamp,
      age: Date.now() - existing.timestamp
    })
    // Отменяем предыдущий запрос
    if (existing.cancel) {
      existing.cancel()
    }
    activeAnalysisRequests.delete(docId)
  }

  let aborted = false
  let reader = null

  const params = new URLSearchParams({
    doc_id: docId
  })
  const url = `${API_BASE_URL}/api/analyze/run?${params.toString()}`

  console.log('%c[SSE] 🚀 Запуск SSE соединения', 'color: #4CAF50; font-weight: bold', { docId, url })
  
  // Создаём функцию отмены, которая будет удалять запись из Map
  const cancelFunction = () => {
    console.log('%c[SSE] 🛑 Отмена SSE соединения', 'color: #FF5722; font-weight: bold')
    aborted = true
    if (reader) {
      reader.cancel().catch(() => {})
    }
    // Удаляем запись из Map при отмене
    activeAnalysisRequests.delete(docId)
  }

  // Регистрируем активный запрос
  activeAnalysisRequests.set(docId, {
    cancel: cancelFunction,
    timestamp: Date.now()
  })

  // Используем fetch вместо EventSource, чтобы отправлять заголовки для обхода ngrok warning
  fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'text/event-stream',
      'ngrok-skip-browser-warning': 'true'
    }
  })
    .then(async (response) => {
      console.log('%c[SSE] 📡 Ответ получен', 'color: #2196F3; font-weight: bold', {
        status: response.status,
        statusText: response.statusText,
        contentType: response.headers.get('content-type'),
        headers: Object.fromEntries(response.headers.entries())
      })

      if (!response.ok) {
        throw new Error(`SSE request failed: ${response.status} ${response.statusText}`)
      }

      const contentType = response.headers.get('content-type') || ''
      if (!contentType.includes('text/event-stream') && !contentType.includes('text/plain')) {
        // Если ngrok вернул HTML, пробуем прочитать его и показать ошибку
        const text = await response.text()
        if (text.includes('ngrok') || text.includes('html')) {
          console.error('%c[SSE] ❌ ngrok warning page обнаружена!', 'color: #F44336; font-weight: bold', { text: text.substring(0, 500) })
          throw new Error('ngrok warning page detected. Please visit the ngrok URL directly and click "Continue" to set a cookie.')
        }
        throw new Error(`Unexpected content-type: ${contentType}`)
      }

      console.log('%c[SSE] ✅ Соединение установлено, начинаем чтение потока...', 'color: #4CAF50; font-weight: bold')
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let eventCount = 0
      let readCount = 0
      let lastDataTime = Date.now()

      // Таймаут для обнаружения зависших соединений (15 минут)
      // Бэкенд может долго обрабатывать, особенно на стадии 1
      let timeout = setTimeout(() => {
        if (!aborted) {
          console.error('%c[SSE] ⏱️ Таймаут: поток не получает данные более 15 минут', 'color: #F44336; font-weight: bold', {
            eventCount,
            readCount,
            lastDataTime: new Date(lastDataTime).toISOString()
          })
          aborted = true
          if (reader) {
            reader.cancel().catch(() => {})
          }
          onError?.(new Error('SSE stream timeout: no data for 15 minutes'))
        }
      }, 15 * 60 * 1000) // 15 минут вместо 5

      while (!aborted) {
        readCount++
        console.log(`%c[SSE] 🔄 Чтение потока #${readCount}`, 'color: #9E9E9E', {
          eventCount,
          bufferLength: buffer.length,
          waiting: 'Ожидание данных от бэкенда...'
        })
        
        const { done, value } = await reader.read()
        
        if (done) {
          clearTimeout(timeout)
          console.log('%c[SSE] 📭 Поток завершён (done=true)', 'color: #FF9800; font-weight: bold', {
            eventCount,
            readCount,
            totalReads: readCount,
            message: 'Бэкенд закрыл соединение. Это может быть нормально, если анализ завершён, или ошибка, если анализ ещё идёт.'
          })
          
          // Если поток закрылся слишком рано (до получения финальных данных), это может быть ошибка
          if (eventCount < 3) {
            console.warn('%c[SSE] ⚠️ Поток закрыт слишком рано!', 'color: #FF9800; font-weight: bold', {
              eventCount,
              expected: 'Должно быть больше событий (progress, output-update, final)',
              possibleCause: 'Бэкенд закрыл соединение до завершения анализа'
            })
          }
          
          break
        }

        if (value && value.length > 0) {
          lastDataTime = Date.now()
          // Сбрасываем таймаут при получении данных
          clearTimeout(timeout)
          timeout = setTimeout(() => {
            if (!aborted) {
              console.error('%c[SSE] ⏱️ Таймаут: поток не получает данные более 15 минут', 'color: #F44336; font-weight: bold', {
                eventCount,
                readCount,
                lastDataTime: new Date(lastDataTime).toISOString()
              })
              aborted = true
              if (reader) {
                reader.cancel().catch(() => {})
              }
              onError?.(new Error('SSE stream timeout: no data for 15 minutes'))
            }
          }, 15 * 60 * 1000)
          
          console.log(`%c[SSE] ✅ Получены данные в чтении #${readCount}`, 'color: #4CAF50', {
            bytesReceived: value.length,
            eventCount
          })
        }

        const decoded = decoder.decode(value, { stream: true })
        buffer += decoded
        
        // Логируем сырые данные для отладки (первые 500 символов)
        if (decoded.length > 0) {
          console.log('%c[SSE] 📥 Получены сырые данные', 'color: #00BCD4', {
            length: decoded.length,
            preview: decoded.substring(0, 200),
            bufferLength: buffer.length
          })
        }
        
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Оставляем неполную строку в буфере

        for (const line of lines) {
          if (aborted) break
          if (!line.trim()) continue

          // Логируем каждую строку для отладки
          console.log('%c[SSE] 📄 Обработка строки', 'color: #607D8B', {
            line: line.substring(0, 150),
            startsWithData: line.startsWith('data: '),
            length: line.length
          })

          // SSE формат: "data: {...}"
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.slice(6) // Убираем "data: "
              const data = JSON.parse(jsonStr)
              eventCount++
              
              console.log(`%c[SSE] 📨 Событие #${eventCount}`, 'color: #9C27B0; font-weight: bold', {
                event: data?.event,
                stage: data?.stage,
                progress: data?.progress ?? data?.percent,
                hasOutput: !!data?.output,
                outputKeys: data?.output ? Object.keys(data.output) : null,
                dataSize: JSON.stringify(data).length,
                data: data
              })
              
              onEvent?.(data)
              
              if (data?.event === 'complete' || data?.event === 'final') {
                console.log('%c[SSE] ✅ Пайплайн завершён', 'color: #4CAF50; font-weight: bold', { event: data.event, totalEvents: eventCount })
                clearTimeout(timeout)
                aborted = true
                // Удаляем запись из Map при успешном завершении
                activeAnalysisRequests.delete(docId)
                onComplete?.()
                return
              }
            } catch (err) {
              console.error('%c[SSE] ❌ Ошибка парсинга события', 'color: #F44336; font-weight: bold', { 
                err, 
                line: line.substring(0, 200),
                jsonStr: line.slice(6).substring(0, 200)
              })
            }
          } else {
            // Логируем не-SSE строки для отладки
            if (line.trim() && !line.startsWith('event:') && !line.startsWith('id:')) {
              console.log('%c[SSE] 📝 Не-SSE строка', 'color: #757575', { line: line.substring(0, 200) })
            }
          }
        }
      }

      clearTimeout(timeout)
      
      if (!aborted) {
        // Проверяем, получили ли мы хотя бы какие-то данные
        if (eventCount === 0) {
          console.error('%c[SSE] ❌ Поток закрыт без получения событий!', 'color: #F44336; font-weight: bold', {
            readCount,
            message: 'Бэкенд закрыл соединение сразу после установки. Возможно, проблема с бэкендом или doc_id.'
          })
          onError?.(new Error('SSE stream closed without any events'))
        } else if (eventCount < 3) {
          console.warn('%c[SSE] ⚠️ Поток завершён слишком рано', 'color: #FF9800; font-weight: bold', { 
            eventCount,
            readCount,
            message: 'Поток закрыт бэкендом после получения только служебных событий (preflight, log). Возможно, анализ ещё не начался или произошла ошибка на бэкенде.'
          })
          // Не вызываем onError сразу - возможно, бэкенд просто медленно стартует
          // Вызываем onComplete, чтобы фронтенд мог попробовать polling
          onComplete?.()
        } else {
          console.warn('%c[SSE] ⚠️ Поток завершён, но не было события final/complete', 'color: #FF9800; font-weight: bold', { 
            eventCount,
            readCount,
            message: 'Поток закрыт бэкендом, но финальное событие не получено. Возможно, соединение оборвалось.'
          })
          // Если поток завершился без final/complete, это может быть ошибка
          // Вызываем onError, чтобы фронтенд мог попробовать получить данные через REST
          onError?.(new Error('SSE stream closed without final event'))
          onComplete?.()
        }
        // Удаляем запись из Map при завершении
        activeAnalysisRequests.delete(docId)
      }
    })
    .catch((err) => {
      if (!aborted) {
        console.error('%c[SSE] ❌ Критическая ошибка SSE', 'color: #F44336; font-weight: bold', {
          error: err,
          message: err.message,
          stack: err.stack
        })
        onError?.(err)
      }
      // Удаляем запись из Map при ошибке
      activeAnalysisRequests.delete(docId)
    })

  return cancelFunction
}

/**
 * Резервные REST-эндпоинты стадий.
 */
export async function getStage(docId, stage) {
  if (!docId) throw new Error('docId is required')
  if (!stage) throw new Error('stage is required')
  return apiRequest(`/api/stage/${encodeURIComponent(docId)}/${stage}`, { method: 'GET' })
}

/**
 * Перерасчет рейтинга всего сценария.
 * GET запрос без параметров.
 */
export async function ratingRecalc(docId) {
  if (!docId) throw new Error('docId is required')
  return apiRequest(`/api/rating/recalc/${encodeURIComponent(docId)}`, {
    method: 'GET',
  })
}

/**
 * Перерасчет рейтинга для одной сцены.
 * POST /api/scene/recalc_one/{doc_id}
 * 
 * Принимает: { scene_index, heading, page, sentences: string[] }
 * Возвращает: полный output.json для всего сценария
 */
export async function ratingRecalcScene(docId, sceneData) {
  if (!docId) throw new Error('docId is required')
  if (!sceneData) throw new Error('sceneData is required')
  
  // Формируем payload в формате, который ожидает бэкенд
  // sceneData может быть либо объектом с all_scenes (старый формат), либо уже готовым объектом сцены
  let payload
  
  if (sceneData.all_scenes && Array.isArray(sceneData.all_scenes) && sceneData.all_scenes.length > 0) {
    // Старый формат: { all_scenes: [{ heading, sentences, ... }] }
    const scene = sceneData.all_scenes[0]
    payload = {
      scene_index: sceneData.scene_index ?? scene.scene_index ?? 0,
      heading: scene.heading ?? '',
      page: scene.page ?? null,
      sentences: Array.isArray(scene.sentences)
        ? scene.sentences.map(s => typeof s === 'string' ? s : (s.text ?? ''))
        : []
    }
  } else {
    // Новый формат: уже готовый объект сцены
    payload = {
      scene_index: sceneData.scene_index ?? 0,
      heading: sceneData.heading ?? '',
      page: sceneData.page ?? null,
      sentences: Array.isArray(sceneData.sentences)
        ? sceneData.sentences.map(s => typeof s === 'string' ? s : (s.text ?? ''))
        : []
    }
  }
  
  // Логируем запрос для отладки
  console.log('%c[analysisApi] 🔄 Перерасчет одной сцены', 'color: #2196F3; font-weight: bold', {
    docId,
    url: `/api/scene/recalc_one/${encodeURIComponent(docId)}`,
    payload
  })
  
  // Пробуем разные варианты пути, если первый не работает
  const paths = [
    `/api/scene/recalc_one/${encodeURIComponent(docId)}`,
    `/api/scene/recalc_one/${docId}`, // Без кодировки
    `/api/scene/recalc/${encodeURIComponent(docId)}`, // Альтернативный путь
  ]
  
  let lastError = null
  
  for (const path of paths) {
    try {
      const result = await apiRequest(path, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      
      console.log('%c[analysisApi] ✅ Перерасчет успешен', 'color: #4CAF50; font-weight: bold', {
        path,
        hasResult: !!result
      })
      
      return result
    } catch (error) {
      lastError = error
      console.warn('%c[analysisApi] ⚠️ Путь не работает', 'color: #FF9800', {
        path,
        status: error.status,
        message: error.message
      })
      
      // Если это не 404, прекращаем попытки
      if (error.status !== 404) {
        throw error
      }
    }
  }
  
  // Если все пути вернули 404, выбрасываем ошибку
  throw new Error(`Эндпоинт для перерасчета одной сцены не найден (404). Проверьте, что бэкенд поддерживает POST /api/scene/recalc_one/{doc_id}`)
}

/**
 * Замена фрагментов через AI.
 * Пробуем разные варианты эндпоинта и метода.
 * 
 * @param {string} docId
 * @param {Object} payload - { all_scenes: [{ heading, replace_sentences_id, age_rating, sentences }] }
 * @returns {Promise<Object>} - { results: [{ heading, replacements: [{ sentence_id, new_sentence }] }] }
 */
export async function aiReplace(docId, payload) {
  if (!docId) throw new Error('docId is required')
  if (!payload || !payload.all_scenes) throw new Error('payload with all_scenes is required')
  
  console.log('%c[analysisApi] 🤖 AI Replace запрос', 'color: #9C27B0; font-weight: bold', {
    docId,
    payloadKeys: Object.keys(payload),
    allScenesCount: payload.all_scenes?.length ?? 0,
    payload: payload,
    firstScene: payload.all_scenes?.[0] ? {
      heading: payload.all_scenes[0].heading,
      replace_sentences_id: payload.all_scenes[0].replace_sentences_id,
      age_rating: payload.all_scenes[0].age_rating,
      sentencesCount: payload.all_scenes[0].sentences?.length ?? 0,
      sentences: payload.all_scenes[0].sentences?.slice(0, 3)
    } : null
  })
  
  // Пробуем разные варианты пути и метода
  const paths = [
    { path: `/api/ai/replace/${encodeURIComponent(docId)}`, method: 'POST' },
    { path: `/api/ai/replace/${encodeURIComponent(docId)}`, method: 'PUT' },
    { path: `/api/scene/ai_replace/${encodeURIComponent(docId)}`, method: 'POST' },
    { path: `/api/scene/ai_replace/${encodeURIComponent(docId)}`, method: 'PUT' },
  ]
  
  let lastError = null
  
  for (const { path, method } of paths) {
    try {
      console.log('%c[analysisApi] 🔄 Пробуем путь', 'color: #FF9800', { 
        path, 
        method,
        payloadSize: JSON.stringify(payload).length,
        payloadPreview: {
          all_scenes_count: payload.all_scenes?.length ?? 0,
          first_scene: payload.all_scenes?.[0] ? {
            heading: payload.all_scenes[0].heading,
            replace_sentences_id: payload.all_scenes[0].replace_sentences_id,
            age_rating: payload.all_scenes[0].age_rating,
            sentences_count: payload.all_scenes[0].sentences?.length ?? 0,
            sentences_ids: payload.all_scenes[0].sentences?.map(s => s.id),
            first_sentences: payload.all_scenes[0].sentences?.slice(0, 3).map(s => ({ id: s.id, text: s.text?.substring(0, 50) }))
          } : null
        }
      })
      
      const result = await apiRequest(path, {
        method,
        body: JSON.stringify(payload),
      })
      
      console.log('%c[analysisApi] ✅ AI Replace успешен', 'color: #4CAF50; font-weight: bold', {
        path,
        method,
        hasResult: !!result,
        resultKeys: result ? Object.keys(result) : [],
        resultsCount: result?.results?.length ?? 0
      })
      
      return result
    } catch (error) {
      lastError = error
      console.warn('%c[analysisApi] ⚠️ Путь не работает', 'color: #FF9800', {
        path,
        method,
        status: error.status,
        message: error.message
      })
      
      // Если это не 405 (Method Not Allowed), прекращаем попытки
      if (error.status !== 405 && error.status !== 404) {
        throw error
      }
    }
  }
  
  // Если все пути вернули 405/404, выбрасываем ошибку
  throw new Error(`Эндпоинт для AI replace не найден (405/404). Проверьте, что бэкенд поддерживает AI replace.`)
}

/**
 * Редактирование предложения.
 * PATCH /api/edit/violation/sentence/{doc_id}
 * 
 * @param {string} docId
 * @param {Object} payload - { scene_index: number, sentence_index: number, text: string }
 * @returns {Promise<Object>} - обновленный output.json
 */
export async function editSentence(docId, payload) {
  if (!docId) throw new Error('docId is required')
  if (!payload || typeof payload.scene_index !== 'number' || typeof payload.sentence_index !== 'number') {
    throw new Error('payload with scene_index and sentence_index is required')
  }
  
  const requestPayload = {
    scene_index: payload.scene_index,
    sentence_index: payload.sentence_index,
    text: payload.text ?? ''
  }
  
  return apiRequest(`/api/edit/violation/sentence/${encodeURIComponent(docId)}`, {
    method: 'PATCH',
    body: JSON.stringify(requestPayload),
  })
}

/**
 * Добавление нарушения.
 * POST /api/edit/violation/add/{doc_id}
 * 
 * @param {string} docId
 * @param {Object} payload - { scene_index, sentence_index, text, fragment_severity, labels }
 * @returns {Promise<Object>} - обновленный output.json
 */
export async function addViolation(docId, payload) {
  if (!docId) throw new Error('docId is required')
  if (!payload || typeof payload.scene_index !== 'number' || typeof payload.sentence_index !== 'number') {
    throw new Error('payload with scene_index and sentence_index is required')
  }
  
  const requestPayload = {
    scene_index: payload.scene_index,
    sentence_index: payload.sentence_index,
    text: payload.text ?? '',
    fragment_severity: payload.fragment_severity ?? 'Moderate',
    labels: Array.isArray(payload.labels) ? payload.labels : []
  }
  
  return apiRequest(`/api/edit/violation/add/${encodeURIComponent(docId)}`, {
    method: 'POST',
    body: JSON.stringify(requestPayload),
  })
}

/**
 * Редактирование нарушения.
 * PUT /api/edit/violation/update/{doc_id}
 * 
 * @param {string} docId
 * @param {Object} payload - { scene_index, sentence_index, text, fragment_severity, labels }
 * @returns {Promise<Object>} - обновленный output.json
 */
export async function updateViolation(docId, payload) {
  if (!docId) throw new Error('docId is required')
  if (!payload || typeof payload.scene_index !== 'number' || typeof payload.sentence_index !== 'number') {
    throw new Error('payload with scene_index and sentence_index is required')
  }
  
  const requestPayload = {
    scene_index: payload.scene_index,
    sentence_index: payload.sentence_index,
    text: payload.text ?? '',
    fragment_severity: payload.fragment_severity ?? 'Moderate',
    labels: Array.isArray(payload.labels) ? payload.labels : []
  }
  
  return apiRequest(`/api/edit/violation/update/${encodeURIComponent(docId)}`, {
    method: 'PUT',
    body: JSON.stringify(requestPayload),
  })
}

/**
 * Отмена нарушения.
 * POST /api/edit/violation/cancel/{doc_id}
 * 
 * @param {string} docId
 * @param {Object} payload - { scene_index: number, sentence_index: number }
 * @returns {Promise<Object>} - обновленный output.json
 */
export async function cancelViolation(docId, payload) {
  if (!docId) throw new Error('docId is required')
  if (!payload || typeof payload.scene_index !== 'number' || typeof payload.sentence_index !== 'number') {
    throw new Error('payload with scene_index and sentence_index is required')
  }
  
  const requestPayload = {
    scene_index: payload.scene_index,
    sentence_index: payload.sentence_index
  }
  
  return apiRequest(`/api/edit/violation/cancel/${encodeURIComponent(docId)}`, {
    method: 'POST',
    body: JSON.stringify(requestPayload),
  })
}

/**
 * Запуск анализа без SSE (просто запускает анализ на бэкенде).
 * Используется когда SSE отключён, но нужно запустить анализ.
 */
export async function startAnalysis(docId) {
  if (!docId) throw new Error('docId is required')
  
  // Защита от повторных запусков: если для этого docId уже есть активный запрос, не запускаем снова
  if (activeAnalysisRequests.has(docId)) {
    const existing = activeAnalysisRequests.get(docId)
    console.warn('%c[analysisApi] ⚠️ Анализ уже запущен для этого docId, пропускаем повторный запуск', 'color: #FF9800; font-weight: bold', {
      docId,
      existingTimestamp: existing.timestamp,
      age: Date.now() - existing.timestamp
    })
    return Promise.resolve() // Возвращаем успешный промис, так как анализ уже запущен
  }
  
  const params = new URLSearchParams({
    doc_id: docId
  })
  const url = `${API_BASE_URL}/api/analyze/run?${params.toString()}`
  
  console.log('%c[analysisApi] 🚀 Запуск анализа (без SSE)', 'color: #4CAF50; font-weight: bold', { docId, url })
  
  // Регистрируем запрос (но без функции cancel, так как мы не читаем поток)
  activeAnalysisRequests.set(docId, {
    cancel: () => {}, // Пустая функция, так как мы не читаем поток
    timestamp: Date.now()
  })
  
  // Запускаем анализ, но не читаем SSE поток - просто запускаем и закрываем соединение
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'text/event-stream',
        'ngrok-skip-browser-warning': 'true'
      }
    })
    
    if (!response.ok) {
      // Удаляем запись из Map при ошибке
      activeAnalysisRequests.delete(docId)
      throw new Error(`Failed to start analysis: ${response.status} ${response.statusText}`)
    }
    
    // Сразу закрываем соединение - нам нужно только запустить анализ
    // НЕ удаляем запись из Map здесь, так как анализ запущен и может быть активен
    // Запись будет удалена при следующем запуске runPipelineStream или при явной отмене
    if (response.body) {
      const reader = response.body.getReader()
      reader.cancel().catch(() => {})
    }
    
    console.log('%c[analysisApi] ✅ Анализ запущен', 'color: #4CAF50; font-weight: bold')
    // НЕ удаляем запись из Map здесь, так как анализ запущен и может быть активен
    // Запись будет удалена при следующем запуске runPipelineStream или при явной отмене
    return true
  } catch (error) {
    // Удаляем запись из Map при ошибке
    activeAnalysisRequests.delete(docId)
    console.error('%c[analysisApi] ❌ Ошибка запуска анализа', 'color: #F44336; font-weight: bold', error)
    throw error
  }
}


