import { apiRequest, API_BASE_URL } from './client'

/**
 * Загрузка сценария (pdf/docx).
 * Возвращает { docId, scenes }.
 */
export async function uploadScenario(file) {
  const formData = new FormData()
  formData.append('file', file)

  const data = await apiRequest('/api/scenario/upload', {
    method: 'POST',
    body: formData,
  })

  // Логируем ответ от бэкенда для отладки
  console.log('%c[scenarioApi] 📥 Ответ от /api/scenario/upload', 'color: #2196F3; font-weight: bold', {
    hasDocId: !!(data.doc_id || data.docId),
    hasScenes: Array.isArray(data.scenes),
    scenesCount: Array.isArray(data.scenes) ? data.scenes.length : 0,
    hasDetail: !!data.detail,
    detail: data.detail,
    keys: Object.keys(data),
    data: data
  })
  
  // Детальное логирование структуры первой сцены для анализа формата
  if (Array.isArray(data.scenes) && data.scenes.length > 0) {
    const firstScene = data.scenes[0]
    console.log('%c[scenarioApi] 🔍 Структура первой сцены от бэкенда', 'color: #9C27B0; font-weight: bold', {
      sceneKeys: Object.keys(firstScene),
      hasHeading: !!firstScene.heading,
      hasContent: !!firstScene.content,
      hasSentences: Array.isArray(firstScene.sentences),
      sentencesCount: Array.isArray(firstScene.sentences) ? firstScene.sentences.length : 0,
      hasBlocks: Array.isArray(firstScene.blocks),
      hasCastList: Array.isArray(firstScene.cast_list),
      hasMeta: !!firstScene.meta,
      hasNumber: !!firstScene.number,
      hasNumberSuffix: !!firstScene.number_suffix,
      hasIe: !!firstScene.ie,
      hasLocation: !!firstScene.location,
      hasTimeOfDay: !!firstScene.time_of_day,
      hasShootDay: !!firstScene.shoot_day,
      hasTimecode: !!firstScene.timecode,
      hasRemoved: typeof firstScene.removed !== 'undefined',
      
      // Детальная структура sentences
      firstSentence: Array.isArray(firstScene.sentences) && firstScene.sentences.length > 0
        ? {
            keys: Object.keys(firstScene.sentences[0]),
            hasText: !!firstScene.sentences[0].text,
            hasKind: !!firstScene.sentences[0].kind,
            hasSpeaker: !!firstScene.sentences[0].speaker,
            hasLineNo: typeof firstScene.sentences[0].line_no !== 'undefined',
            hasId: typeof firstScene.sentences[0].id !== 'undefined',
            value: firstScene.sentences[0]
          }
        : null,
      
      // Детальная структура blocks
      firstBlock: Array.isArray(firstScene.blocks) && firstScene.blocks.length > 0
        ? {
            keys: Object.keys(firstScene.blocks[0]),
            hasType: !!firstScene.blocks[0].type,
            hasText: !!firstScene.blocks[0].text,
            hasLineNo: typeof firstScene.blocks[0].line_no !== 'undefined',
            hasSpeaker: !!firstScene.blocks[0].speaker,
            value: firstScene.blocks[0]
          }
        : null,
      
      // Структура cast_list
      castList: Array.isArray(firstScene.cast_list)
        ? firstScene.cast_list.map(item => ({
            keys: Object.keys(item),
            hasText: !!item.text,
            hasLineNo: typeof item.line_no !== 'undefined',
            value: item
          }))
        : null,
      
      // Структура meta
      meta: firstScene.meta
        ? {
            keys: Object.keys(firstScene.meta),
            hasStartLine: typeof firstScene.meta.start_line !== 'undefined',
            hasCharCount: typeof firstScene.meta.char_count !== 'undefined',
            hasBlockCount: typeof firstScene.meta.block_count !== 'undefined',
            hasVerbose: typeof firstScene.meta.verbose !== 'undefined',
            value: firstScene.meta
          }
        : null,
      
      // Полная структура первой сцены для анализа
      fullScene: firstScene
    })

    // Логируем полный сценарий от бэкенда (первые 3 сцены для примера)
    const scenesToLog = data.scenes.slice(0, 3)
    console.log('%c[scenarioApi] 📄 Полный сценарий от бэкенда (первые 3 сцены)', 'color: #4CAF50; font-weight: bold', {
      totalScenes: data.scenes.length,
      scenesPreview: scenesToLog.map((scene, idx) => ({
        index: idx,
        heading: scene.heading,
        content: scene.content ? (typeof scene.content === 'string' ? scene.content.substring(0, 200) : 'Array') : null,
        sentencesCount: Array.isArray(scene.sentences) ? scene.sentences.length : 0,
        blocksCount: Array.isArray(scene.blocks) ? scene.blocks.length : 0,
        fullScene: scene // Полная структура сцены
      }))
    })

    // Логируем весь сценарий (для отладки форматирования)
    console.log('%c[scenarioApi] 📚 ВСЕ СЦЕНЫ ОТ БЭКЕНДА', 'color: #FF5722; font-weight: bold', {
      totalScenes: data.scenes.length,
      allScenes: data.scenes.map((scene, idx) => ({
        index: idx,
        sceneNumber: scene.sceneNumber ?? scene.number ?? idx + 1,
        heading: scene.heading,
        content: scene.content,
        sentences: scene.sentences,
        blocks: scene.blocks,
        cast_list: scene.cast_list,
        meta: scene.meta,
        fullScene: scene
      }))
    })
  }

  // Проверяем, не вернул ли бэкенд ошибку
  if (data.detail && !data.scenes) {
    console.error('%c[scenarioApi] ❌ Бэкенд вернул ошибку вместо сцен', 'color: #F44336; font-weight: bold', {
      detail: data.detail,
      message: 'Бэкенд не смог распарсить сцены, но вернул doc_id'
    })
    // Если есть doc_id, но нет сцен - это проблема, но продолжаем работу
    // Возможно, сцены можно получить через GET /api/scenario/{doc_id}
  }

  // Официальная схема: SceneUploadResponse { doc_id, scenes }
  const docId = data.doc_id ?? data.docId ?? null
  const scenes = Array.isArray(data.scenes) ? data.scenes : []

  if (!docId) {
    throw new Error('Бэкенд не вернул doc_id. Возможно, файл не был загружен.')
  }

  if (scenes.length === 0 && data.detail) {
    console.warn('%c[scenarioApi] ⚠️ Бэкенд вернул doc_id, но сцены пустые', 'color: #FF9800; font-weight: bold', {
      docId,
      detail: data.detail,
      suggestion: 'Попробуем получить сцены через GET /api/scenario/{doc_id}'
    })
    
    // Пробуем получить сцены через GET запрос
    if (docId) {
      try {
        const scenarioData = await getScenario(docId)
        if (Array.isArray(scenarioData) && scenarioData.length > 0) {
          console.log('%c[scenarioApi] ✅ Сцены получены через GET запрос', 'color: #4CAF50; font-weight: bold', {
            scenesCount: scenarioData.length
          })
          return { docId, scenes: scenarioData }
        }
      } catch (getError) {
        console.error('%c[scenarioApi] ❌ Не удалось получить сцены через GET', 'color: #F44336', getError)
      }
    }
  }

  return { docId, scenes }
}

/**
 * Получение сценария по doc_id.
 * Возвращает массив сцен в «сырую» структуру бэка.
 */
export async function getScenario(docId) {
  if (!docId) {
    throw new Error('docId is required')
  }
  const data = await apiRequest(`/api/scenario/${encodeURIComponent(docId)}`, {
    method: 'GET',
  })

  // Бэкенд может вернуть объект или обёртку — стараемся быть гибкими.
  if (Array.isArray(data)) {
    return data
  }
  if (Array.isArray(data.scenes)) {
    return data.scenes
  }
  return []
}

/**
 * Экспорт сценария (скачивание файла).
 * ⚠️ УСТАРЕЛО: Эта функция больше не используется.
 * Для просмотра сценария используйте openScenarioView() или getScenarioViewUrl().
 * 
 * @deprecated Используйте /api/scenario/view/{doc_id} для просмотра сценария
 * @param {string} docId - ID документа
 * @param {Array} scriptScenes - Массив сцен для экспорта
 * @param {Object} options - Опции экспорта
 * @param {string} options.format - Формат файла: 'docx' или 'pdf' (по умолчанию 'docx')
 * @param {boolean} options.inline - Открыть в браузере вместо скачивания (по умолчанию false)
 * @param {boolean} options.showLines - Добавлять номера строк [ln:N] (по умолчанию false)
 * @param {boolean} options.useBlocks - Использовать scene.blocks вместо originalSentences (по умолчанию false)
 * @param {boolean} options.uppercaseHeadings - Заголовки сцен в верхнем регистре (по умолчанию true)
 * @param {string} options.baseName - Базовое имя файла
 */
export async function exportScenario(docId, scriptScenes, options = {}) {
  if (!docId) {
    throw new Error('docId is required')
  }
  if (!Array.isArray(scriptScenes) || scriptScenes.length === 0) {
    throw new Error('scriptScenes is required and must be a non-empty array')
  }

  const {
    format = 'docx',
    inline = false,
    showLines = false,
    useBlocks = false,
    uppercaseHeadings = true,
    baseName = null
  } = options

  console.log('%c[scenarioApi] 📤 Экспорт сценария', 'color: #2196F3; font-weight: bold', {
    docId,
    scenesCount: scriptScenes.length,
    format,
    inline,
    showLines,
    useBlocks,
    uppercaseHeadings,
    baseName,
    firstSceneKeys: scriptScenes[0] ? Object.keys(scriptScenes[0]) : []
  })

  // Формируем query параметры
  const queryParams = new URLSearchParams()
  queryParams.append('format', format)
  queryParams.append('inline', inline.toString())
  queryParams.append('show_lines', showLines.toString())
  queryParams.append('use_blocks', useBlocks.toString())
  queryParams.append('uppercase_headings', uppercaseHeadings.toString())
  if (baseName) {
    queryParams.append('base_name', baseName)
  }

  // Body может быть либо массивом сцен, либо объектом {scriptScenes: [...]}
  // Согласно документации, можно отправлять просто массив или объект
  const body = JSON.stringify(scriptScenes)

  // Кодируем docId для URL - используем encodeURIComponent для безопасного кодирования
  const encodedDocId = encodeURIComponent(docId)
  const url = `${API_BASE_URL}/api/scenario/export/${encodedDocId}?${queryParams.toString()}`

  console.log('%c[scenarioApi] 🔗 URL для экспорта', 'color: #9C27B0; font-weight: bold', {
    originalDocId: docId,
    encodedDocId: encodedDocId,
    fullUrl: url,
    queryParams: queryParams.toString()
  })
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true'
    },
    body: body
  })

  if (!response.ok) {
    const errorText = await response.text()
    let errorData
    try {
      errorData = JSON.parse(errorText)
    } catch {
      errorData = { detail: errorText }
    }
    throw new Error(errorData.detail || `API request failed with status ${response.status}`)
  }

  // Получаем blob из ответа
  const blob = await response.blob()
  
  // Получаем имя файла из заголовка Content-Disposition, если есть
  const contentDisposition = response.headers.get('Content-Disposition')
  let filename = null
  if (contentDisposition) {
    const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
    if (filenameMatch && filenameMatch[1]) {
      filename = filenameMatch[1].replace(/['"]/g, '')
    }
  }

  console.log('%c[scenarioApi] ✅ Файл получен от бэкенда', 'color: #4CAF50; font-weight: bold', {
    blobSize: blob.size,
    blobType: blob.type,
    filename
  })

  return { blob, filename }
}

/**
 * Получение HTML отчета по doc_id.
 * GET /api/report/{doc_id}
 * Возвращает HTML строку отчета.
 * 
 * @param {string} docId - ID документа
 * @returns {Promise<string>} HTML содержимое отчета
 */
export async function getReport(docId) {
  if (!docId) {
    throw new Error('docId is required')
  }

  console.log('%c[scenarioApi] 📄 Запрос HTML отчета', 'color: #2196F3; font-weight: bold', {
    docId
  })

  // Используем прямой fetch, так как apiRequest пытается парсить JSON,
  // а нам нужен HTML как текст
  const url = `${API_BASE_URL}/api/report/${encodeURIComponent(docId)}`
  
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'ngrok-skip-browser-warning': 'true'
    }
  })

  if (!response.ok) {
    const errorText = await response.text()
    let errorData
    try {
      errorData = JSON.parse(errorText)
    } catch {
      errorData = { detail: errorText }
    }
    const error = new Error(errorData.detail || `API request failed with status ${response.status}`)
    error.status = response.status
    throw error
  }

  // Получаем HTML как текст
  const htmlContent = await response.text()

  console.log('%c[scenarioApi] ✅ HTML отчет получен', 'color: #4CAF50; font-weight: bold', {
    htmlLength: htmlContent.length,
    preview: htmlContent.substring(0, 200)
  })

  return htmlContent
}

/**
 * Открытие сценария для просмотра.
 * POST /api/scenario/view/{doc_id}
 * Отправляет POST запрос с данными сцен и открывает HTML в новом окне.
 * 
 * @param {string} docId - ID документа
 * @param {Array} scriptScenes - Массив сцен для отображения
 * @param {Object} options - Опции просмотра
 * @param {boolean} options.inline - Вернуть HTML (по умолчанию true)
 * @param {boolean} options.save - Сохранить HTML в /exports (по умолчанию true)
 * @param {boolean} options.showLines - Добавлять номера строк (по умолчанию false)
 * @param {boolean} options.useBlocks - Использовать scene.blocks (по умолчанию false)
 * @param {boolean} options.uppercaseHeadings - Заголовки в верхнем регистре (по умолчанию false)
 * @param {string} options.title - Заголовок страницы
 */
export async function openScenarioView(docId, scriptScenes, options = {}) {
  if (!docId) {
    throw new Error('docId is required')
  }
  if (!Array.isArray(scriptScenes) || scriptScenes.length === 0) {
    throw new Error('scriptScenes is required and must be a non-empty array')
  }

  const {
    inline = true,
    save = true,
    showLines = false,
    useBlocks = false,
    uppercaseHeadings = false,
    title = null
  } = options

  // Формируем query параметры
  const queryParams = new URLSearchParams()
  queryParams.append('inline', inline.toString())
  queryParams.append('save', save.toString())
  queryParams.append('show_lines', showLines.toString())
  queryParams.append('use_blocks', useBlocks.toString())
  queryParams.append('uppercase_headings', uppercaseHeadings.toString())
  if (title) {
    queryParams.append('title', title)
  }

  // Кодируем docId для URL
  const encodedDocId = encodeURIComponent(docId)
  const url = `${API_BASE_URL}/api/scenario/view/${encodedDocId}?${queryParams.toString()}`

  console.log('%c[scenarioApi] 📄 Открытие просмотра сценария', 'color: #2196F3; font-weight: bold', {
    docId,
    encodedDocId,
    scenesCount: scriptScenes.length,
    url,
    options
  })

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true'
      },
      body: JSON.stringify(scriptScenes)
    })

    if (!response.ok) {
      const errorText = await response.text()
      let errorData
      try {
        errorData = JSON.parse(errorText)
      } catch {
        errorData = { detail: errorText }
      }
      throw new Error(errorData.detail || `API request failed with status ${response.status}`)
    }

    // Получаем HTML из ответа
    const htmlContent = await response.text()

    // Создаем blob URL и открываем в новой вкладке
    const blob = new Blob([htmlContent], { type: 'text/html' })
    const blobUrl = URL.createObjectURL(blob)
    
    window.open(blobUrl, '_blank', 'noopener,noreferrer')

    // Очищаем blob URL через некоторое время (после того как окно загрузится)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)

    console.log('%c[scenarioApi] ✅ Сценарий открыт для просмотра', 'color: #4CAF50; font-weight: bold', {
      htmlLength: htmlContent.length
    })
  } catch (error) {
    console.error('%c[scenarioApi] ❌ Ошибка при открытии просмотра сценария', 'color: #F44336; font-weight: bold', error)
    throw error
  }
}


