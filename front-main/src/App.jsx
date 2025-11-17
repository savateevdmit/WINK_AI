import { useState, useCallback, useEffect, useRef } from 'react'
import UploadPage from './components/UploadPage'
import ResultsPage from './components/ResultsPage'
import Header from './components/Header'
import mockScriptData from './utils/mockScript.json'
import { buildAllScenesPayload } from './utils/sceneUtils'
import { uploadScenario, getScenario } from './api/scenarioApi'
import { runPipelineStream, getStage, startAnalysis, ratingRecalc, ratingRecalcScene, cancelViolation } from './api/analysisApi'
import { normaliseAnalysisFromRaw } from './utils/mockApi'

const DEFAULT_HEADER_CONFIG = {
  showLogo: true,
  leftExtras: null,
  rightContent: null,
  leftOrientation: 'row'
}

const normaliseScriptScenes = (rawScenes = []) => {
  // Логируем структуру rawScenes для анализа
  if (rawScenes.length > 0) {
    console.log('%c[App] 🔍 Анализ структуры сцен от бэкенда', 'color: #9C27B0; font-weight: bold', {
      totalScenes: rawScenes.length,
      firstSceneKeys: Object.keys(rawScenes[0]),
      firstSceneSample: {
        ...rawScenes[0],
        // Ограничиваем размер для читаемости
        sentences: Array.isArray(rawScenes[0].sentences)
          ? rawScenes[0].sentences.slice(0, 3).map(s => typeof s === 'string' ? s : { ...s })
          : rawScenes[0].sentences,
        blocks: Array.isArray(rawScenes[0].blocks)
          ? rawScenes[0].blocks.slice(0, 2)
          : rawScenes[0].blocks
      }
    })
  }

  return rawScenes.map((scene, index) => {
    const sceneNumber = scene.sceneNumber ?? scene.page ?? index + 1

    // Бэкенд может вернуть текст в разных полях:
    // - content: string | string[] (как в mockScript)
    // - sentences: { id, text, kind?, speaker?, line_no? }[] | string[] (ВАЖНО: сохраняем структуру для согласования с sentence_index!)
    // - lines: string[]
    // - blocks: [{ type, text, line_no, speaker? }]
    let content = ''
    let originalSentences = null // Сохраняем оригинальную структуру предложений для согласования

    // Извлекаем content из разных источников
    if (Array.isArray(scene.content)) {
      content = scene.content.join('\n\n')
    } else if (typeof scene.content === 'string') {
      content = scene.content
    } else if (Array.isArray(scene.sentences)) {
      // Сохраняем оригинальную структуру предложений для согласования с sentence_index
      // Бэкенд возвращает: { text, kind, speaker, line_no }
      originalSentences = scene.sentences.map((s, idx) => {
        if (typeof s === 'string') {
          return {
            id: idx,
            text: s,
            kind: 'action', // По умолчанию action
            speaker: null,
            line_no: null
          }
        }
        return {
          id: s?.id ?? idx,
          text: s?.text ?? '',
          kind: s?.kind ?? 'action', // action или dialogue
          speaker: s?.speaker ?? null, // Для dialogue - имя говорящего
          line_no: typeof s?.line_no === 'number' ? s.line_no : (s?.line_no ?? null) // Номер строки в исходном файле
        }
      }).filter(s => s.text)

      content = originalSentences
        .map((s) => s.text)
        .filter(Boolean)
        .join('\n\n')
    } else if (Array.isArray(scene.lines)) {
      content = scene.lines
        .map((line) => (typeof line === 'string' ? line : String(line ?? '')))
        .join('\n')
    }

    // Заголовок сцены: добавляем номер сцены в начало, если его ещё нет
    const rawHeading = scene.heading ?? `Сцена ${sceneNumber}`

    // Номер сцены для отображения:
    // 1) сначала пытаемся взять backend-поле `number` ("8-1" и т.п.)
    // 2) если его нет, пытаемся вытащить номер из начала heading ("8-1. ИНТ...")
    // 3) если и этого нет — используем числовой sceneNumber
    let displayNumber =
      (typeof scene.number === 'string' && scene.number.trim().length > 0)
        ? scene.number.trim()
        : ''

    if (!displayNumber && typeof rawHeading === 'string') {
      const match = rawHeading.trim().match(/^([0-9][0-9\-]*)[.\s]/)
      if (match) {
        displayNumber = match[1]
      }
    }

    if (!displayNumber) {
      displayNumber = String(scene.sceneNumber ?? sceneNumber)
    }

    let heading = rawHeading
    const trimmedHeading = rawHeading.trim()
    if (displayNumber && !trimmedHeading.startsWith(displayNumber)) {
      heading = `${displayNumber} ${trimmedHeading}`
    }

    return {
      id: scene.id ?? `scene_${sceneNumber}`,
      sceneNumber,
      page: scene.page ?? index + 1,
      heading,
      content,
      // Сохраняем оригинальную структуру предложений для согласования с бэкендом
      // Это критично для правильной работы sentence_index в problem_fragments
      originalSentences: originalSentences || (content ? [{ id: 0, text: content, kind: 'action', speaker: null, line_no: null }] : null),

      // Расширенная структура сцены (из sc.json формата)
      // Блоки сцены (action/dialogue)
      blocks: Array.isArray(scene.blocks)
        ? scene.blocks.map(block => ({
          type: block.type ?? 'action', // action или dialogue
          text: block.text ?? '',
          line_no: typeof block.line_no === 'number' ? block.line_no : (block.line_no ?? null),
          speaker: block.speaker ?? null // Для dialogue
        }))
        : null,

      // Список актёров в сцене
      cast_list: Array.isArray(scene.cast_list)
        ? scene.cast_list.map(cast => ({
          text: cast.text ?? '',
          line_no: typeof cast.line_no === 'number' ? cast.line_no : (cast.line_no ?? null)
        }))
        : [],

      // Метаданные сцены
      meta: scene.meta
        ? {
          start_line: typeof scene.meta.start_line === 'number' ? scene.meta.start_line : null,
          char_count: typeof scene.meta.char_count === 'number' ? scene.meta.char_count : 0,
          block_count: typeof scene.meta.block_count === 'number' ? scene.meta.block_count : 0,
          verbose: scene.meta.verbose ?? false
        }
        : null,

      // Дополнительные поля сцены
      number: scene.number ?? '',
      number_suffix: scene.number_suffix ?? '',
      ie: scene.ie ?? '', // ИНТ/НАТ
      location: scene.location ?? '',
      time_of_day: scene.time_of_day ?? '',
      shoot_day: scene.shoot_day ?? '',
      timecode: scene.timecode ?? '',
      removed: scene.removed ?? false,
      scene_index: typeof scene.scene_index === 'number' ? scene.scene_index : index
    }
  })
}

const mergeScenes = (existing = [], updates = []) => {
  if (!updates?.length) return existing
  if (!existing?.length || updates.length >= existing.length) {
    return updates
  }

  const map = new Map(existing.map(scene => [scene.sceneNumber, scene]))
  updates.forEach(scene => {
    if (scene?.sceneNumber !== undefined) {
      map.set(scene.sceneNumber, scene)
    }
  })

  return Array.from(map.values()).sort((a, b) => (a.sceneNumber ?? 0) - (b.sceneNumber ?? 0))
}

function App() {
  const [currentPage, setCurrentPage] = useState('upload') // 'upload' | 'results'
  const [analysisData, setAnalysisData] = useState(null)
  const [scriptScenes, setScriptScenes] = useState([])
  const [rawBackendScenes, setRawBackendScenes] = useState([]) // Сырые данные от бэка (input.json)
  const [history, setHistory] = useState([])
  const [docId, setDocId] = useState(null)
  const [headerConfig, setHeaderConfig] = useState(DEFAULT_HEADER_CONFIG)
  const [originalFileName, setOriginalFileName] = useState(null) // Оригинальное имя загруженного файла
  const pipelineCancelRef = useRef(null)
  const pollingIntervalRef = useRef(null)
  const isAnalysisRunningRef = useRef(false)
  const currentRunningDocIdRef = useRef(null)

  const updateHeaderConfig = useCallback((config = {}) => {
    setHeaderConfig({ ...DEFAULT_HEADER_CONFIG, ...config })
  }, [])

  useEffect(() => {
    if (currentPage === 'upload') {
      updateHeaderConfig({ showLogo: false, leftExtras: null })
    } else {
      updateHeaderConfig()
    }
  }, [currentPage, updateHeaderConfig])

  const stopPipeline = useCallback(() => {
    if (pipelineCancelRef.current) {
      console.log('%c[App] 🛑 Остановка пайплайна (stopPipeline вызван)', 'color: #FF5722; font-weight: bold', {
        stack: new Error().stack?.split('\n').slice(1, 4).join('\n')
      })
      pipelineCancelRef.current()
      pipelineCancelRef.current = null
    }
    // Останавливаем polling, если он запущен
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current)
      pollingIntervalRef.current = null
      console.log('%c[App] 🛑 Polling остановлен', 'color: #FF5722; font-weight: bold')
    }
    // Сбрасываем флаги запуска
    isAnalysisRunningRef.current = false
    currentRunningDocIdRef.current = null
  }, [])

  // Останавливаем все процессы при размонтировании компонента
  useEffect(() => {
    return () => {
      stopPipeline()
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
        pollingIntervalRef.current = null
        console.log('%c[App] 🛑 Polling остановлен при размонтировании', 'color: #FF5722; font-weight: bold')
      }
    }
  }, [stopPipeline])

  // Останавливаем все процессы при переходе на страницу загрузки (upload)
  // ВАЖНО: Закрытие панели аналитики в ResultsPage (isPanelOpen) НЕ меняет currentPage,
  // поэтому процессы продолжают работать - это правильно, так как пользователь остается на странице results
  useEffect(() => {
    if (currentPage === 'upload') {
      console.log('%c[App] 🔄 Переход на страницу загрузки, останавливаем все процессы', 'color: #FF9800; font-weight: bold')
      stopPipeline()
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
        pollingIntervalRef.current = null
        isAnalysisRunningRef.current = false
        currentRunningDocIdRef.current = null
        console.log('%c[App] 🛑 Polling остановлен при переходе на upload', 'color: #FF5722; font-weight: bold')
      }
    }
  }, [currentPage, stopPipeline])

  // Экспортируем функции в глобальную область для отладки и экспорта данных
  useEffect(() => {
    if (typeof window !== 'undefined') {
      // Функция остановки всего анализа (SSE + polling)
      window.stopAnalysis = () => {
        stopPipeline()
        console.log('%c[App] 🛑 Анализ остановлен через window.stopAnalysis()', 'color: #FF5722; font-weight: bold')
        return true
      }

      // Функция остановки polling
      window.stopPolling = () => {
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current)
          pollingIntervalRef.current = null
          console.log('%c[App] 🛑 Polling остановлен вручную через window.stopPolling()', 'color: #FF5722; font-weight: bold')
          return true
        }
        console.log('%c[App] ⚠️ Polling не запущен', 'color: #FF9800')
        return false
      }

      // Функция получения текущего сценария в JSON
      window.getScriptScenes = () => {
        console.log('%c[App] 📄 Текущий сценарий (scriptScenes)', 'color: #2196F3; font-weight: bold', scriptScenes)
        return scriptScenes
      }

      // Функция экспорта сценария в JSON (скачивание файла)
      window.exportScriptScenes = () => {
        if (!scriptScenes || scriptScenes.length === 0) {
          console.warn('%c[App] ⚠️ Нет сценария для экспорта', 'color: #FF9800')
          return null
        }

        const json = JSON.stringify(scriptScenes, null, 2)
        const blob = new Blob([json], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `scenario_${docId || Date.now()}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)

        console.log('%c[App] ✅ Сценарий экспортирован в JSON', 'color: #4CAF50; font-weight: bold', {
          scenesCount: scriptScenes.length,
          filename: a.download
        })

        return json
      }

      // Функция получения истории
      window.getHistory = () => {
        console.log('%c[App] 📚 История анализов', 'color: #2196F3; font-weight: bold', history)
        return history
      }

      // Функция экспорта истории в JSON
      window.exportHistory = () => {
        if (!history || history.length === 0) {
          console.warn('%c[App] ⚠️ История пуста', 'color: #FF9800')
          return null
        }

        const json = JSON.stringify(history, null, 2)
        const blob = new Blob([json], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `history_${Date.now()}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)

        console.log('%c[App] ✅ История экспортирована в JSON', 'color: #4CAF50; font-weight: bold', {
          itemsCount: history.length,
          filename: a.download
        })

        return json
      }
    }
    return () => {
      if (typeof window !== 'undefined') {
        delete window.stopAnalysis
        delete window.stopPolling
        delete window.getScriptScenes
        delete window.exportScriptScenes
        delete window.getHistory
        delete window.exportHistory
      }
    }
  }, [scriptScenes, history, docId, stopPipeline])

  // Функция для периодического опроса через REST API (fallback, если SSE не работает)
  const startPolling = useCallback((currentDocId) => {
    if (!currentDocId) return

    // Если polling уже запущен, не запускаем повторно
    if (pollingIntervalRef.current) {
      console.log('%c[App] ⚠️ Polling уже запущен, пропускаем', 'color: #FF9800')
      return
    }

    console.log('%c[App] 🔄 Запуск периодического опроса через REST API', 'color: #FF9800; font-weight: bold', { docId: currentDocId })

    let pollCount = 0
    let errorCount = 0
    const MAX_ERRORS = 5 // Максимум ошибок подряд перед остановкой

    pollingIntervalRef.current = setInterval(async () => {
      pollCount++
      console.log(`%c[App] 🔍 Polling #${pollCount} (проверка раз в 10 секунд)`, 'color: #9E9E9E', { docId: currentDocId })

      // Проверяем, есть ли уже финальные данные - если есть, останавливаем polling
      // Это важно для кэшированных результатов, когда SSE уже завершился с данными
      setAnalysisData(prev => {
        if (!prev) {
          return prev
        }

        // Проверяем наличие финальных данных
        // finalRating может быть даже если нет problemFragments (если анализ не нашёл проблем)
        const hasFinalData = prev.finalRating && (prev.problemFragments !== undefined || prev.categories !== undefined)

        // Проверяем, завершены ли все стадии (stage3 >= 100%)
        const stageProgress = prev.stageProgress ?? {}
        const isStage3Completed = (stageProgress.stage3 ?? 0) >= 100
        const areAllStagesCompleted = (stageProgress.stage1 ?? 0) >= 100 &&
          (stageProgress.stage2 ?? 0) >= 100 &&
          isStage3Completed

        // Останавливаем polling, если:
        // 1. Все стадии завершены (>= 100%) - это главный критерий
        // 2. ИЛИ есть финальные данные (finalRating) И stage3 завершена
        const shouldStop = areAllStagesCompleted ||
          (hasFinalData && isStage3Completed)

        if (shouldStop && pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current)
          pollingIntervalRef.current = null
          // Сбрасываем флаги запуска, так как анализ завершен
          isAnalysisRunningRef.current = false
          currentRunningDocIdRef.current = null
          console.log('%c[App] 🛑 Polling остановлен: финальные данные уже есть и все стадии завершены', 'color: #4CAF50; font-weight: bold', {
            finalRating: prev.finalRating,
            problemFragmentsCount: prev.problemFragments?.length,
            stageProgress,
            isStage3Completed,
            areAllStagesCompleted,
            pollCount
          })
        }

        return prev // Не меняем состояние здесь
      })

      // Если polling был остановлен выше, выходим
      if (!pollingIntervalRef.current) {
        return
      }

      // Дополнительная проверка: если все стадии по 100%, останавливаем polling
      // Это синхронная проверка перед запросом к API (используем актуальное состояние через setState)
      let shouldStopPolling = false
      setAnalysisData(prev => {
        if (!prev) {
          return prev
        }

        const stageProgress = prev.stageProgress ?? {}
        const areAllStagesCompleted = (stageProgress.stage1 ?? 0) >= 100 &&
          (stageProgress.stage2 ?? 0) >= 100 &&
          (stageProgress.stage3 ?? 0) >= 100

        // Если все стадии по 100%, останавливаем polling (анализ завершён)
        if (areAllStagesCompleted && pollingIntervalRef.current) {
          shouldStopPolling = true
        }

        return prev // Не меняем состояние
      })

      // Останавливаем polling после проверки состояния
      if (shouldStopPolling && pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
        pollingIntervalRef.current = null
        isAnalysisRunningRef.current = false
        currentRunningDocIdRef.current = null
        console.log('%c[App] 🛑 Polling остановлен: все стадии завершены (>= 100%)', 'color: #4CAF50; font-weight: bold', {
          pollCount
        })
        return
      }

      // Если polling был остановлен выше, выходим
      if (!pollingIntervalRef.current) {
        return
      }

      try {
        // Пробуем получить финальный отчёт
        const stageFinal = await getStage(currentDocId, 'final')

        // Сбрасываем счётчик ошибок при успешном запросе
        errorCount = 0

        // Проверяем, не вернул ли бэкенд ошибку "Final not ready" или 404
        if (stageFinal?.detail === 'Final not ready' || !stageFinal) {
          console.log(`%c[App] ⏳ Final ещё не готов (polling #${pollCount})`, 'color: #9E9E9E')
          return // Продолжаем polling
        }

        if (stageFinal && (stageFinal.output || (Object.keys(stageFinal).length > 0 && !stageFinal.detail))) {
          const rawOutput = stageFinal.output ?? stageFinal

          // Детальное логирование структуры данных
          console.log(`%c[App] ✅ Получены данные через polling #${pollCount}`, 'color: #4CAF50; font-weight: bold', {
            hasOutput: !!stageFinal.output,
            keys: Object.keys(stageFinal).slice(0, 20), // Первые 20 ключей
            totalKeys: Object.keys(stageFinal).length,
            hasFinalRating: !!rawOutput.final_rating,
            hasProblemFragments: !!rawOutput.problem_fragments,
            hasParentsGuide: !!rawOutput.parents_guide,
            sampleKeys: Object.keys(rawOutput).slice(0, 10),
            rawOutputType: typeof rawOutput,
            isArray: Array.isArray(rawOutput)
          })

          // Проверяем, что это действительно финальный отчёт
          const isFinalReport = rawOutput.final_rating || rawOutput.problem_fragments || rawOutput.parents_guide

          if (!isFinalReport) {
            console.warn(`%c[App] ⚠️ Данные не похожи на финальный отчёт (polling #${pollCount})`, 'color: #FF9800', {
              firstKeys: Object.keys(rawOutput).slice(0, 10),
              sampleData: JSON.stringify(rawOutput).substring(0, 500)
            })
            return // Продолжаем polling, не обновляем состояние
          }

          setAnalysisData(prev => {
            const normalised = normaliseAnalysisFromRaw(rawOutput, scriptScenes)

            console.log('🔍 Нормализованные данные:', {
              finalRating: normalised.finalRating,
              hasModelExplanation: !!normalised.model_explanation,
              modelExplanationPreview: normalised.model_explanation ? normalised.model_explanation.substring(0, 150) + '...' : null,
              problemFragmentsCount: normalised.problemFragments?.length,
              categoriesCount: normalised.categories?.length,
              hasStages: !!normalised.stages,
              normalisedKeys: Object.keys(normalised)
            })

            // ВАЖНО: Сохраняем текущий прогресс стадий из предыдущего состояния
            // Не устанавливаем все стадии на 100% - прогресс обновляется через события progress
            const stageProgress = prev?.stageProgress ?? { stage1: 0, stage2: 0, stage3: 0 }
            const stages = prev?.stages ?? normalised.stages

            console.log('✅ Состояние обновлено из polling', {
              finalRating: normalised.finalRating,
              problemFragmentsCount: normalised.problemFragments?.length,
              currentStageProgress: stageProgress
            })

            // Останавливаем polling, если получили финальные данные
            // Если финальная стадия (stage3) завершена, все предыдущие стадии тоже должны быть 100%
            if (normalised.finalRating && normalised.problemFragments?.length > 0) {
              // Проверяем, завершена ли финальная стадия
              const isStage3Completed = (stageProgress.stage3 ?? 0) >= 100

              // Если финальная стадия завершена, устанавливаем все стадии в 100%
              if (isStage3Completed) {
                stageProgress.stage1 = 100
                stageProgress.stage2 = 100
                stageProgress.stage3 = 100
              }

              const currentStages = stages.map(s => {
                // Если финальная стадия завершена, все стадии должны быть завершены
                if (isStage3Completed) {
                  return { ...s, progress: 100, status: 'completed' }
                }
                // Иначе обновляем статус только если стадия действительно завершена (progress >= 100)
                const isCompleted = (stageProgress[s.id] ?? 0) >= 100
                return {
                  ...s,
                  progress: stageProgress[s.id] ?? s.progress ?? 0,
                  status: isCompleted ? 'completed' : (s.status ?? 'pending')
                }
              })

              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current)
                pollingIntervalRef.current = null
                // Сбрасываем флаги запуска, так как анализ завершен
                isAnalysisRunningRef.current = false
                currentRunningDocIdRef.current = null
                console.log('%c[App] ✅ Polling остановлен: получены финальные данные', 'color: #4CAF50; font-weight: bold', {
                  finalRating: normalised.finalRating,
                  stagesProgress: stageProgress
                })
              }

              return {
                ...normalised,
                stageProgress, // Сохраняем текущий прогресс (не устанавливаем все на 100%)
                stages: currentStages // Сохраняем текущие стадии с их реальным прогрессом
              }
            }

            return {
              ...normalised,
              stageProgress, // Сохраняем текущий прогресс
              stages // Сохраняем текущие стадии с их прогрессом
            }
          })
        }
        // НЕ запрашиваем stage 1 и stage 2 - они не нужны:
        // - Данные обновляются через SSE события (output-update, partial_stage1, stage2_done)
        // - stage final - это уже последняя версия
        // - Если файл уже анализировался (кэш), сразу будет final
      } catch (pollError) {
        // 404 означает, что стадия ещё не готова - это нормально, не считаем ошибкой
        const is404 = pollError.status === 404 || pollError.message?.includes('404')

        if (is404) {
          console.log(`%c[App] ⏳ Final ещё не готов (404, polling #${pollCount})`, 'color: #9E9E9E')
          return // Продолжаем polling, не увеличиваем счётчик ошибок
        }

        // Для остальных ошибок увеличиваем счётчик
        errorCount++
        console.warn(`%c[App] ⚠️ Polling #${pollCount} failed (ошибок подряд: ${errorCount})`, 'color: #FF9800', pollError)

        // Останавливаем polling после нескольких ошибок подряд (не 404)
        if (errorCount >= MAX_ERRORS) {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
            pollingIntervalRef.current = null
            console.error(`%c[App] ❌ Polling остановлен: ${MAX_ERRORS} ошибок подряд`, 'color: #F44336; font-weight: bold', {
              totalPolls: pollCount,
              errors: errorCount
            })
          }
          return
        }

        // Также останавливаем, если слишком много попыток (24 часа при интервале 10 секунд = 8640 попыток)
        // Останавливаем после 12 часов (4320 попыток)
        if (pollCount > 4320) {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
            pollingIntervalRef.current = null
            console.error('%c[App] ❌ Polling остановлен: превышен лимит попыток (12 часов)', 'color: #F44336; font-weight: bold', {
              totalPolls: pollCount,
              hours: (pollCount * 10) / 3600
            })
          }
        }
      }
    }, 10 * 1000) // Опрашиваем каждые 10 секунд
  }, [])

  const startPipeline = useCallback((currentDocId, useSSE = true) => {
    if (!currentDocId) return

    // Защита от повторных запусков: если анализ уже запущен для этого docId, не запускаем снова
    if (isAnalysisRunningRef.current && currentRunningDocIdRef.current === currentDocId) {
      console.warn('%c[App] ⚠️ Анализ уже запущен для этого docId, пропускаем повторный запуск', 'color: #FF9800; font-weight: bold', {
        docId: currentDocId,
        currentRunning: currentRunningDocIdRef.current
      })
      return () => {
        stopPipeline()
      }
    }

    // ВАЖНО: Устанавливаем флаги ДО вызова stopPipeline(), чтобы защита сработала сразу
    // Это предотвращает race condition при быстрых повторных вызовах
    isAnalysisRunningRef.current = true
    currentRunningDocIdRef.current = currentDocId

    // Останавливаем предыдущий запуск, если он был (для другого docId)
    stopPipeline()

    // Восстанавливаем флаги после stopPipeline (он их сбросил)
    isAnalysisRunningRef.current = true
    currentRunningDocIdRef.current = currentDocId

    // Сбрасываем прогресс стадий перед новым запуском
    setAnalysisData(prev => {
      if (!prev) return prev
      const baseStages = [
        { id: 'stage1', label: 'Первичная классификация', progress: 0, status: 'pending' },
        { id: 'stage2', label: 'Обогащение метаданными', progress: 0, status: 'pending' },
        { id: 'stage3', label: 'Финальная интерпретация', progress: 0, status: 'pending' }
      ]
      return {
        ...prev,
        stageProgress: { stage1: 0, stage2: 0, stage3: 0 },
        stages: baseStages
      }
    })

    console.log('%c[App] 🎬 Запуск пайплайна анализа', 'color: #FF5722; font-weight: bold', {
      docId: currentDocId,
      mode: useSSE ? 'SSE' : 'REST polling only'
    })

    // Если SSE отключён, сначала запускаем анализ, потом polling
    if (!useSSE) {
      console.log('%c[App] ⚠️ SSE отключён, используем только REST polling', 'color: #FF9800; font-weight: bold')

      // Сначала запускаем анализ на бэкенде
      startAnalysis(currentDocId)
        .then(() => {
          console.log('%c[App] ✅ Анализ запущен, начинаем polling', 'color: #4CAF50; font-weight: bold')
          // Ждём немного, чтобы анализ начался, потом запускаем polling
          setTimeout(() => {
            startPolling(currentDocId)
          }, 2000) // Ждём 2 секунды перед началом polling
        })
        .catch((err) => {
          console.error('%c[App] ❌ Не удалось запустить анализ', 'color: #F44336; font-weight: bold', err)
          // Всё равно запускаем polling - возможно, анализ уже запущен
          startPolling(currentDocId)
        })

      return () => {
        stopPipeline()
      }
    }

    const cancel = runPipelineStream(currentDocId, {
      onEvent: (payload) => {
        if (!payload || !payload.event) {
          console.warn('%c[App] ⚠️ Пустое событие или без event', 'color: #FF9800', { payload })
          return
        }

        console.group(`%c[App] 📦 Обработка события: ${payload.event}`, 'color: #2196F3; font-weight: bold')

        // Универсальное вычисление ключа стадии под UI (stage1/stage2/stage3)
        const resolveStageKey = (stage) => {
          if (typeof stage === 'number') {
            // Если число: 0 -> stage1, 1 -> stage2, 2 -> stage3, 3 -> stage3
            if (stage === 0) return 'stage1'
            if (stage === 1) return 'stage2'
            if (stage === 2) return 'stage3'
            if (stage === 3) return 'stage3' // Stage 3 = финальная стадия
            return `stage${stage}`
          }
          if (typeof stage === 'string') {
            let key = stage.toLowerCase().trim()

            // Обрабатываем формат "Stage 0", "Stage 1", "Stage 2", "Stage 3"
            if (key.startsWith('stage ')) {
              const num = parseInt(key.replace('stage ', ''))
              if (!isNaN(num)) {
                if (num === 0) return 'stage1'
                if (num === 1) return 'stage2'
                if (num === 2) return 'stage3'
                if (num === 3) return 'stage3' // Stage 3 = финальная стадия
              }
            }

            // Обрабатываем формат "stage0", "stage1", "stage2", "stage3"
            if (!key.startsWith('stage')) {
              const num = key.replace(/[^0-9]/g, '')
              key = num ? `stage${num}` : key
            }

            // Карта: backend stage0/stage1/stage2/stage3 -> наши stage1/stage2/stage3
            if (key === 'stage0') return 'stage1'
            if (key === 'stage1') return 'stage2'
            if (key === 'stage2') return 'stage3'
            if (key === 'stage3') return 'stage3' // Stage 3 = финальная стадия
            return key
          }
          return 'stage1'
        }

        if (payload.event === 'stage-start') {
          const stageKey = resolveStageKey(payload.stage)
          console.log('%c[App] 🎯 stage-start', 'color: #4CAF50', {
            backendStage: payload.stage,
            frontendStage: stageKey,
            stepsTotal: payload.steps_total
          })
          setAnalysisData(prev => {
            if (!prev) return prev
            const nextStageProgress = {
              ...(prev.stageProgress ?? {}),
              [stageKey]: 0
            }
            const nextStages = (prev.stages ?? []).map(stage => (
              stage.id === stageKey
                ? { ...stage, progress: 0, status: 'in_progress' }
                : stage
            ))
            console.log('%c[App] ✅ Обновлено состояние (stage-start)', 'color: #4CAF50', {
              stageKey,
              stageProgress: nextStageProgress[stageKey],
              stageStatus: nextStages.find(s => s.id === stageKey)?.status
            })
            return {
              ...prev,
              stageProgress: nextStageProgress,
              stages: nextStages
            }
          })
          console.groupEnd()
          return
        }

        if (payload.event === 'progress') {
          // Игнорируем stage0 (prefilter) - это предфильтрация, не основная стадия
          if (payload.stage === 'stage0' || payload.stage === 'Stage 0' || payload.stage === 0) {
            console.log('%c[App] ⏭️ Пропускаем stage0 (prefilter)', 'color: #9E9E9E', { stage: payload.stage })
            console.groupEnd()
            return
          }

          const stageKey = resolveStageKey(payload.stage)

          // Бэкенд отправляет progress как число от 0.0 до 100.0 в поле "progress"
          // Но иногда progress = 0.0, а реальные проценты в raw строке
          // Приоритет: payload.progress (если > 0) > парсинг из raw > payload.percent > вычисление из steps
          let rawPercent = null

          // Если progress > 0, используем его
          if (typeof payload.progress === 'number' && payload.progress > 0) {
            rawPercent = payload.progress
          }
          // Иначе пробуем извлечь процент из raw строки (например: "Stage 1:  33%|###3      | 1/3")
          else if (payload.raw && typeof payload.raw === 'string') {
            // Ищем последний процент в raw строке (самый актуальный)
            // Паттерн: "Stage X:  YY%|" или "Stage X: YY%|"
            const percentMatches = payload.raw.matchAll(/Stage\s+\d+[^:]*:\s*(\d+)%/gi)
            const matches = Array.from(percentMatches)
            if (matches.length > 0) {
              // Берем последний найденный процент (самый актуальный)
              const lastMatch = matches[matches.length - 1]
              rawPercent = parseFloat(lastMatch[1])
              console.log('%c[App] 📊 Извлечен процент из raw строки', 'color: #9C27B0', {
                raw: payload.raw.substring(0, 150),
                extractedPercent: rawPercent,
                allMatches: matches.map(m => m[1])
              })
            }
          }

          // Если не нашли в raw, пробуем payload.percent
          if (rawPercent === null && typeof payload.percent === 'number') {
            rawPercent = payload.percent
          }

          // Если всё ещё null, вычисляем из steps
          const percent = rawPercent !== null
            ? rawPercent
            : (payload.steps_total ? (payload.steps_done / payload.steps_total) * 100 : 0)

          console.log('%c[App] 📊 progress', 'color: #FF9800', {
            backendStage: payload.stage,
            frontendStage: stageKey,
            rawPercent,
            percent: percent.toFixed(2) + '%',
            stepsDone: payload.steps_done,
            stepsTotal: payload.steps_total,
            eta: payload.eta_seconds
          })

          setAnalysisData(prev => {
            if (!prev) {
              console.warn('%c[App] ⚠️ analysisData пусто, пропускаем обновление', 'color: #FF9800')
              return prev
            }

            // Если стадия ещё не начата (status === 'pending'), автоматически запускаем её
            const currentStage = prev.stages?.find(s => s.id === stageKey)
            const needsStart = !currentStage || currentStage.status === 'pending'

            if (needsStart) {
              console.log('%c[App] 🚀 Автозапуск стадии', 'color: #4CAF50', { stageKey })
            }

            const nextStageProgress = {
              ...(prev.stageProgress ?? {}),
              [stageKey]: percent
            }

            // Если финальная стадия (stage3) достигла 100%, все предыдущие стадии тоже должны быть 100%
            if (stageKey === 'stage3' && percent >= 100) {
              nextStageProgress.stage1 = 100
              nextStageProgress.stage2 = 100
              nextStageProgress.stage3 = 100
            }

            const nextStages = (prev.stages ?? []).map(stage => {
              if (stage.id === stageKey) {
                const completed = percent >= 100
                return {
                  ...stage,
                  progress: percent,
                  status: completed ? 'completed' : 'in_progress'
                }
              }
              // Если stage3 завершена, все стадии должны быть завершены
              if (stageKey === 'stage3' && percent >= 100) {
                return {
                  ...stage,
                  progress: 100,
                  status: 'completed'
                }
              }
              return stage
            })

            console.log('%c[App] ✅ Обновлено состояние (progress)', 'color: #4CAF50', {
              stageKey,
              progress: percent.toFixed(2) + '%',
              status: nextStages.find(s => s.id === stageKey)?.status,
              allStages100: stageKey === 'stage3' && percent >= 100 ? 'Все стадии установлены в 100%' : null
            })

            return {
              ...prev,
              stageProgress: nextStageProgress,
              stages: nextStages
            }
          })
          console.groupEnd()
          return
        }

        if (payload.event === 'output-update' || payload.event === 'partial_stage1' || payload.event === 'stage2_done' || payload.event === 'stage-result' || payload.event === 'partial_report' || payload.event === 'final') {
          if (!payload.output) {
            console.warn('%c[App] ⚠️ Событие без output', 'color: #FF9800', { event: payload.event })
            console.groupEnd()
            return
          }

          console.log(`%c[App] 📄 ${payload.event}`, 'color: #9C27B0', {
            hasOutput: !!payload.output,
            outputKeys: payload.output ? Object.keys(payload.output) : [],
            finalRating: payload.output?.final_rating,
            modelFinalRating: payload.output?.model_final_rating,
            hasModelExplanation: !!payload.output?.model_explanation,
            modelExplanationPreview: payload.output?.model_explanation ? payload.output.model_explanation.substring(0, 100) + '...' : null,
            scenesTotal: payload.output?.scenes_total,
            problemFragmentsCount: payload.output?.problem_fragments?.length,
            stage: payload.stage,
            // Детальная проверка всех полей в payload.output
            fullOutputKeys: payload.output ? Object.keys(payload.output) : [],
            hasModelFinalRating: 'model_final_rating' in (payload.output || {}),
            hasModelExplanationField: 'model_explanation' in (payload.output || {})
          })

          setAnalysisData(prev => {
            const normalised = normaliseAnalysisFromRaw(payload.output, scriptScenes)

            // Логируем сразу после нормализации в SSE обработчике
            console.log(`%c[App] 🔄 SSE: Нормализовано после ${payload.event}`, 'color: #FF9800; font-weight: bold', {
              event: payload.event,
              hasModelExplanation: !!normalised.model_explanation,
              modelExplanationPreview: normalised.model_explanation ? normalised.model_explanation.substring(0, 150) + '...' : null,
              normalisedKeys: Object.keys(normalised)
            })
            // ВАЖНО: Сохраняем текущий прогресс стадий из предыдущего состояния
            // Не устанавливаем все стадии на 100% сразу - прогресс обновляется через события "progress"
            let stageProgress = prev?.stageProgress ?? normalised.stageProgress
            let stages = prev?.stages ?? normalised.stages

            // Если стадия завершена (partial_stage1, stage2_done, final), устанавливаем её прогресс на 100%
            if (payload.event === 'partial_stage1' || payload.event === 'stage2_done' || payload.event === 'final') {
              const completedStageKey = payload.event === 'partial_stage1'
                ? 'stage1'
                : payload.event === 'stage2_done'
                  ? 'stage2'
                  : (payload.stage ? resolveStageKey(payload.stage) : 'stage3')

              stageProgress = {
                ...stageProgress,
                [completedStageKey]: 100
              }

              // Если финальная стадия (stage3) завершена, все предыдущие стадии тоже должны быть 100%
              if (completedStageKey === 'stage3') {
                stageProgress.stage1 = 100
                stageProgress.stage2 = 100
                stageProgress.stage3 = 100
              }

              stages = stages.map(stage => {
                if (stage.id === completedStageKey) {
                  return { ...stage, progress: 100, status: 'completed' }
                }
                // Если stage3 завершена, все стадии должны быть завершены
                if (completedStageKey === 'stage3') {
                  return { ...stage, progress: 100, status: 'completed' }
                }
                return stage
              })

              console.log(`%c[App] ✅ Стадия ${completedStageKey} завершена (100%)`, 'color: #4CAF50', {
                event: payload.event,
                allStages100: completedStageKey === 'stage3' ? 'Все стадии установлены в 100%' : null
              })
            }

            console.log('%c[App] ✅ Обновлено состояние (output)', 'color: #4CAF50', {
              event: payload.event,
              finalRating: normalised.finalRating,
              hasModelExplanation: !!normalised.model_explanation,
              modelExplanationPreview: normalised.model_explanation ? normalised.model_explanation.substring(0, 100) + '...' : null,
              problemFragmentsCount: normalised.problemFragments?.length,
              categoriesCount: normalised.categories?.length,
              currentStageProgress: stageProgress
            })

            const updated = {
              ...normalised,
              stageProgress, // Сохраняем текущий прогресс, не перезаписываем на 100% (кроме завершённых стадий)
              stages // Сохраняем текущие стадии с их прогрессом
            }

            // Логируем перед возвратом в SSE обработчике
            console.log(`%c[App] 💾 SSE: Сохраняем в analysisData после ${payload.event}`, 'color: #9C27B0; font-weight: bold', {
              event: payload.event,
              hasModelExplanation: !!updated.model_explanation,
              modelExplanationPreview: updated.model_explanation ? updated.model_explanation.substring(0, 150) + '...' : null,
              updatedKeys: Object.keys(updated)
            })

            return updated
          })
          console.groupEnd()
          return
        }

        if (payload.event === 'complete' || payload.event === 'final') {
          console.log(`%c[App] ✅ Пайплайн завершён (событие: ${payload.event})`, 'color: #4CAF50; font-weight: bold', payload)

          // ВАЖНО: Останавливаем polling сразу при получении final/complete
          // Это особенно важно для кэшированных результатов, когда SSE завершается сразу
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
            pollingIntervalRef.current = null
            console.log('%c[App] 🛑 Polling остановлен: получено событие final/complete', 'color: #4CAF50; font-weight: bold', {
              event: payload.event,
              hasOutput: !!payload.output
            })
          }

          // Если есть output в событии final, обновляем данные
          if (payload.event === 'final' && payload.output) {
            setAnalysisData(prev => {
              const normalised = normaliseAnalysisFromRaw(payload.output, scriptScenes)
              let stageProgress = prev?.stageProgress ?? normalised.stageProgress
              let stages = prev?.stages ?? normalised.stages

              // Устанавливаем stage3 на 100% при событии final
              // Если финальная стадия завершена, все предыдущие стадии тоже должны быть 100%
              stageProgress = {
                ...stageProgress,
                stage1: 100,
                stage2: 100,
                stage3: 100
              }

              stages = stages.map(stage => {
                // Все стадии должны быть завершены, если финальная стадия завершена
                return { ...stage, progress: 100, status: 'completed' }
              })

              console.log('%c[App] ✅ Данные обновлены из события final', 'color: #4CAF50; font-weight: bold', {
                finalRating: normalised.finalRating,
                hasModelExplanation: !!normalised.model_explanation,
                modelExplanationPreview: normalised.model_explanation ? normalised.model_explanation.substring(0, 100) + '...' : null,
                problemFragmentsCount: normalised.problemFragments?.length,
                stagesProgress: stageProgress
              })

              return {
                ...normalised,
                stageProgress,
                stages
              }
            })
          }

          console.groupEnd()
          return
        }

        if (payload.event === 'error') {
          console.error('%c[App] ❌ Pipeline error event', 'color: #F44336; font-weight: bold', payload)
          console.groupEnd()
        }

        // Игнорируем служебные события (preflight, log), но логируем их для отладки
        if (payload.event === 'preflight' || payload.event === 'log') {
          if (payload.event === 'preflight' && payload.warnings) {
            console.warn('%c[App] ⚠️ Pipeline preflight warnings', 'color: #FF9800', payload.warnings)
          } else {
            console.log(`%c[App] 📝 ${payload.event}`, 'color: #757575', payload)
          }
          console.groupEnd()
          return
        }

        console.warn('%c[App] ⚠️ Необработанное событие', 'color: #FF9800', { event: payload.event, payload })
        console.groupEnd()
      },
      onError: async (err) => {
        console.group('%c[App] ❌ SSE Error Handler', 'color: #F44336; font-weight: bold')
        console.error('Ошибка:', err)
        console.log('Останавливаем SSE соединение...')
        stopPipeline() // Останавливаем SSE соединение

        // Fallback: запускаем периодический опрос через REST API (только если polling ещё не запущен)
        // И только если у нас ещё нет финальных данных
        if (currentDocId) {
          // Проверяем, есть ли уже финальные данные
          setAnalysisData(prev => {
            const hasFinalData = prev?.finalRating && prev?.problemFragments?.length > 0

            if (hasFinalData) {
              console.log('%c[App] ✅ Финальные данные уже есть, polling не нужен', 'color: #4CAF50; font-weight: bold')
              return prev // Не меняем состояние
            }

            // Если финальных данных нет и polling не запущен - запускаем
            if (!pollingIntervalRef.current) {
              console.log('%c[App] 🔄 SSE не работает, запускаем polling через REST API', 'color: #FF9800; font-weight: bold')
              startPolling(currentDocId)
            } else {
              console.log('%c[App] ⚠️ Polling уже запущен, пропускаем запуск из onError', 'color: #FF9800')
            }

            return prev // Не меняем состояние здесь
          })

          // Также пробуем сразу получить финальный результат
          console.log('Попытка получить финальный отчёт через REST API...', { docId: currentDocId })
          try {
            // Пробуем разные стадии, если final недоступен
            // Согласно API: /api/stage/{doc_id}/1 (Stage 1), /api/stage/{doc_id}/3 (Stage 2), /api/stage/{doc_id}/final (Stage 3)
            const stagesToTry = ['final', '3', '1']
            let stageFinal = null
            let lastError = null

            for (const stage of stagesToTry) {
              try {
                console.log(`Пробуем получить стадию: ${stage}...`)
                const result = await getStage(currentDocId, stage)
                if (result && (result.output?.final_rating || result.final_rating || result.problem_fragments)) {
                  stageFinal = result
                  console.log(`✅ Получены данные из стадии: ${stage}`)
                  break
                }
              } catch (err) {
                lastError = err
                const is404 = err.status === 404 || err.message?.includes('404')
                if (is404) {
                  console.log(`Стадия ${stage} ещё не готова (404), пробуем следующую...`)
                  continue
                } else {
                  console.warn(`Ошибка при получении стадии ${stage}:`, err)
                  // Если это не 404, прекращаем попытки
                  break
                }
              }
            }

            // 404 означает, что стадия ещё не готова - это нормально
            if (!stageFinal) {
              console.log('REST ответ: Финальные данные ещё не готовы (все стадии вернули 404)')
              return
            }

            console.log('REST ответ получен:', {
              hasOutput: !!stageFinal?.output,
              hasData: !!stageFinal,
              keys: stageFinal ? Object.keys(stageFinal) : []
            })

            const rawOutput = stageFinal?.output ?? stageFinal
            if (rawOutput) {
              console.log('Обновляем состояние из REST fallback (с output)...')
              setAnalysisData(prev => {
                const normalised = normaliseAnalysisFromRaw(rawOutput, scriptScenes)
                // Устанавливаем все стадии в 100% при получении финального отчета
                const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
                const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }
                console.log('✅ Состояние обновлено из REST fallback', {
                  finalRating: normalised.finalRating,
                  problemFragmentsCount: normalised.problemFragments?.length
                })
                return {
                  ...normalised,
                  stageProgress: completedStageProgress,
                  stages: completedStages
                }
              })
            } else if (stageFinal) {
              console.log('Обновляем состояние из REST fallback (без output, нормализуем целиком)...')
              // Если finalReport есть, но без output, пытаемся нормализовать его целиком
              setAnalysisData(prev => {
                const normalised = normaliseAnalysisFromRaw(stageFinal, scriptScenes)
                const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
                const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }
                console.log('✅ Состояние обновлено из REST fallback (нормализовано)', {
                  finalRating: normalised.finalRating,
                  problemFragmentsCount: normalised.problemFragments?.length
                })
                return {
                  ...normalised,
                  stageProgress: completedStageProgress,
                  stages: completedStages
                }
              })
            } else {
              console.warn('⚠️ REST ответ пустой или без данных')
            }
          } catch (fallbackError) {
            // 404 означает, что стадия ещё не готова - это нормально, не логируем как ошибку
            const is404 = fallbackError.status === 404 || fallbackError.message?.includes('404')
            if (is404) {
              console.log('REST ответ: Final ещё не готов (404)')
            } else {
              console.error('❌ Fallback final stage fetch failed:', fallbackError)
            }
          }
        } else {
          console.warn('⚠️ Нет docId для fallback запроса')
        }
        console.groupEnd()
      },
      onComplete: async () => {
        console.log('%c[App] ✅ Пайплайн завершён (onComplete)', 'color: #4CAF50; font-weight: bold')
        pipelineCancelRef.current = null
        // Сбрасываем флаг запуска SSE, но НЕ сбрасываем полностью, если polling еще работает
        // Флаги полностью сбросятся в stopPipeline, когда polling получит финальные данные

        // Проверяем, есть ли уже финальные данные ПЕРЕД остановкой polling
        // Если данных нет, значит анализ ещё идёт, и нужно запустить polling
        const currentData = analysisData
        const hasFinalData = currentData?.finalRating && currentData?.problemFragments?.length > 0

        // Останавливаем polling только если финальные данные уже есть
        if (hasFinalData && pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current)
          pollingIntervalRef.current = null
          console.log('%c[App] 🛑 Polling остановлен: финальные данные уже есть (onComplete)', 'color: #4CAF50; font-weight: bold')
        }

        // Если SSE завершился, но финального события не было, пробуем получить через REST один раз
        if (currentDocId) {
          // Если данных нет, сразу запускаем polling (не ждём 2 секунды)
          if (!hasFinalData) {
            console.log('%c[App] 🔄 SSE завершился без финальных данных, запускаем polling сразу', 'color: #FF9800; font-weight: bold', { docId: currentDocId })
            if (!pollingIntervalRef.current) {
              startPolling(currentDocId)
            }
          }

          // Также пробуем получить данные через REST один раз (параллельно с polling)
          setTimeout(async () => {
            try {
              // Проверяем текущее состояние перед запросом (может измениться после запуска polling)
              const currentDataAfterDelay = analysisData
              const hasDataAfterDelay = currentDataAfterDelay?.finalRating && currentDataAfterDelay?.problemFragments?.length > 0

              if (hasDataAfterDelay) {
                console.log('%c[App] ✅ Финальные данные уже получены (возможно, через polling), REST запрос не нужен', 'color: #4CAF50')
                return
              }

              // Если данных всё ещё нет, пробуем получить через REST
              console.log('%c[App] 🔄 SSE завершился без финальных данных, делаем один запрос через REST...', 'color: #FF9800; font-weight: bold', { docId: currentDocId })

              // Делаем ОДИН запрос к final (не запускаем polling)
              // Пробуем разные стадии, если final недоступен
              const stagesToTry = ['final', 'stage2', 'stage1', 'stage0']
              let stageFinal = null

              for (const stage of stagesToTry) {
                try {
                  const result = await getStage(currentDocId, stage)
                  if (result && (result.output?.final_rating || result.final_rating || result.problem_fragments)) {
                    stageFinal = result
                    console.log(`✅ Получены данные из стадии: ${stage}`)
                    break
                  }
                } catch (err) {
                  const is404 = err.status === 404 || err.message?.includes('404')
                  if (!is404) {
                    console.warn(`Ошибка при получении стадии ${stage}:`, err)
                    break
                  }
                }
              }

              if (stageFinal) {
                console.log('REST ответ получен (из onComplete):', {
                  hasOutput: !!stageFinal?.output,
                  hasData: !!stageFinal,
                  keys: stageFinal ? Object.keys(stageFinal) : []
                })

                const rawOutput = stageFinal?.output ?? stageFinal
                if (rawOutput && (rawOutput.final_rating || rawOutput.problem_fragments?.length > 0)) {
                  console.log('Обновляем состояние из REST (из onComplete)...')
                  setAnalysisData(prevState => {
                    const normalised = normaliseAnalysisFromRaw(rawOutput, scriptScenes)
                    // Сохраняем текущий прогресс стадий (не устанавливаем все на 100%)
                    const stageProgress = prevState?.stageProgress ?? normalised.stageProgress
                    const stages = prevState?.stages ?? normalised.stages

                    console.log('✅ Состояние обновлено из REST (из onComplete)', {
                      finalRating: normalised.finalRating,
                      problemFragmentsCount: normalised.problemFragments?.length,
                      stagesProgress: stageProgress
                    })
                    return {
                      ...normalised,
                      stageProgress, // Сохраняем текущий прогресс
                      stages // Сохраняем текущие стадии
                    }
                  })
                }
              } else {
                console.log('REST ответ: Финальные данные ещё не готовы (все стадии вернули 404). Polling уже запущен, продолжаем опрос.')
              }
            } catch (err) {
              console.error('❌ Ошибка в onComplete:', err)
              // Polling уже должен быть запущен выше, если данных нет
              if (!pollingIntervalRef.current) {
                console.log('%c[App] 🔄 Запускаем polling после ошибки в onComplete', 'color: #FF9800; font-weight: bold')
                startPolling(currentDocId)
              }
            }
          }, 2000) // Ждём 2 секунды перед запросом
        }
      }
    })

    pipelineCancelRef.current = cancel
  }, [stopPipeline, startPolling, analysisData, scriptScenes])

  const handleFileUpload = async (file) => {
    try {
      // 1. Отправляем файл на бэкенд, получаем doc_id и распаршенные сцены
      const uploadResult = await uploadScenario(file)
      const nextDocId = uploadResult.docId

      console.log('%c[App] 📊 Результат загрузки файла', 'color: #2196F3; font-weight: bold', {
        docId: nextDocId,
        scenesCount: uploadResult.scenes?.length ?? 0,
        hasScenes: Array.isArray(uploadResult.scenes) && uploadResult.scenes.length > 0
      })

      if (!uploadResult.scenes || uploadResult.scenes.length === 0) {
        console.error('%c[App] ❌ Бэкенд не вернул сцены!', 'color: #F44336; font-weight: bold', {
          docId: nextDocId,
          uploadResult
        })
        throw new Error('Бэкенд не вернул распарсенные сцены. Проверьте логи бэкенда.')
      }

      const backendScenes = normaliseScriptScenes(uploadResult.scenes)

      // Логируем нормализованные сцены для отладки
      console.log('%c[App] 📝 Нормализованные сцены', 'color: #9C27B0; font-weight: bold', {
        totalScenes: backendScenes.length,
        scenesPreview: backendScenes.slice(0, 3).map((scene, idx) => ({
          index: idx,
          sceneNumber: scene.sceneNumber,
          heading: scene.heading,
          contentLength: scene.content?.length ?? 0,
          hasBlocks: Array.isArray(scene.blocks) && scene.blocks.length > 0,
          blocksCount: Array.isArray(scene.blocks) ? scene.blocks.length : 0,
          hasOriginalSentences: Array.isArray(scene.originalSentences) && scene.originalSentences.length > 0,
          originalSentencesCount: Array.isArray(scene.originalSentences) ? scene.originalSentences.length : 0,
          fullScene: scene
        })),
        allScenes: backendScenes // Все нормализованные сцены
      })

      setDocId(nextDocId)
      setScriptScenes(backendScenes)
      // Сохраняем сырые данные от бэка для скачивания JSON
      setRawBackendScenes(uploadResult.scenes)
      // Сохраняем оригинальное имя файла для определения формата при скачивании
      setOriginalFileName(file.name)

      // 2. Инициализируем analysisData с нулевым прогрессом стадий
      // Прогресс будет обновляться через события progress от бэкенда
      const initialAnalysisData = {
        id: `analysis_${Date.now()}`,
        document: file.name,
        age_label: '',
        age_confidence: 0.65,
        scenes_total: backendScenes.length,
        parents_guide: {},
        reasons: [],
        evidence: [],
        problem_fragments: [],
        law_explanation: null,
        processing_seconds: 0,
        stageProgress: {
          stage1: 0,  // Начинаем с 0%
          stage2: 0,
          stage3: 0
        },
        stages: [
          { id: 'stage1', label: 'Первичная классификация', progress: 0, status: 'pending' },
          { id: 'stage2', label: 'Обогащение метаданными', progress: 0, status: 'pending' },
          { id: 'stage3', label: 'Финальная интерпретация', progress: 0, status: 'pending' }
        ],
        raw: {}
      }

      setAnalysisData(initialAnalysisData)
      setCurrentPage('results')

      // Добавляем в историю: сохраняем docId + снимок данных
      const historyItem = {
        id: initialAnalysisData.id,
        docId: nextDocId,
        fileName: file.name,
        date: new Date().toLocaleDateString('ru-RU'),
        ageRating: initialAnalysisData.age_label,
        ...initialAnalysisData,
        scriptScenes: backendScenes
      }
      setHistory(prev => [historyItem, ...prev])

      // 3. Запускаем реальный пайплайн анализа
      // Используем SSE для получения прогресса и данных в реальном времени
      if (nextDocId) {
        startPipeline(nextDocId, true) // true = использовать SSE
      }
    } catch (error) {
      console.error('Error analyzing script with backend, falling back to mocks:', error)

      // Показываем понятное сообщение пользователю, если бэкенд недоступен
      if (error.isNgrokError || error.isNetworkError) {
        alert(`⚠️ Бэкенд недоступен!\n\n${error.message}\n\nИспользуется демо-режим с моковыми данными.`)
      }

      try {
        // Fallback: полностью старое поведение
        const { mockAnalyzeScript } = await import('./utils/mockApi.js')
        const analysisResult = await mockAnalyzeScript(file)
        const mockScriptScenes = await loadMockScriptScenes()

        setDocId(null)
        setAnalysisData(analysisResult)
        setScriptScenes(mockScriptScenes)
        setCurrentPage('results')

        const historyItem = {
          id: analysisResult.id,
          docId: null,
          fileName: file.name,
          date: new Date().toLocaleDateString('ru-RU'),
          ageRating: analysisResult.age_label,
          ...analysisResult,
          scriptScenes: mockScriptScenes
        }
        setHistory(prev => [historyItem, ...prev])
      } catch (fallbackError) {
        console.error('Error in mock fallback:', fallbackError)
        alert('Ошибка при анализе файла. Попробуйте снова.')
      }
    }
  }

  // Функция для извлечения текста из файла (упрощенная версия)
  const loadMockScriptScenes = async () => {
    // В реальном приложении здесь будет парсинг файла
    // Пока возвращаем моковый набор сцен
    return normaliseScriptScenes(mockScriptData.scenes)
  }

  const handleBackToUpload = () => {
    setCurrentPage('upload')
    setAnalysisData(null)
    setScriptScenes([])
    setDocId(null)
  }

  const handleReanalyze = useCallback(async (payload) => {
    // Если есть docId — используем бэкенд API
    if (docId) {
      // Проверяем, это перерасчет одной сцены или всего сценария
      // Новый формат: { scene_index, heading, page, sentences }
      // Старый формат: { all_scenes: [...] }
      const isSingleScene = payload?.scene_index !== undefined || (payload?.all_scenes && payload.all_scenes.length === 1)

      if (isSingleScene) {
        // Перерасчет одной сцены: POST /api/scene/recalc_one/{doc_id}
        console.log('%c[App] 🔄 Перерасчет рейтинга одной сцены', 'color: #2196F3; font-weight: bold', {
          docId,
          sceneIndex: payload.scene_index,
          sceneHeading: payload.heading ?? payload.all_scenes?.[0]?.heading
        })

        try {
          const result = await ratingRecalcScene(docId, payload)

          // Бэкенд возвращает обновленный анализ
          if (result && (result.final_rating || result.problem_fragments || result.parents_guide)) {
            // ВАЖНО: Сохраняем существующий id при перерасчете одной сцены
            const existingId = analysisData?.id || null
            const normalised = normaliseAnalysisFromRaw(result, scriptScenes, existingId)
            const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
            const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }

            setAnalysisData({
              ...normalised,
              stageProgress: completedStageProgress,
              stages: completedStages
            })

            console.log('%c[App] ✅ Рейтинг одной сцены пересчитан', 'color: #4CAF50; font-weight: bold', {
              finalRating: normalised.finalRating,
              preservedId: existingId
            })
          } else {
            // Если бэкенд не вернул полный анализ, пробуем получить финальный отчёт
            const stageFinal = await getStage(docId, 'final')
            const rawOutput = stageFinal?.output ?? stageFinal
            if (rawOutput && (rawOutput.final_rating || rawOutput.problem_fragments)) {
              // ВАЖНО: Сохраняем существующий id при перерасчете одной сцены
              const existingId = analysisData?.id || null
              const normalised = normaliseAnalysisFromRaw(rawOutput, scriptScenes, existingId)
              const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
              const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }

              setAnalysisData({
                ...normalised,
                stageProgress: completedStageProgress,
                stages: completedStages
              })
            }
          }
        } catch (error) {
          console.error('%c[App] ❌ Ошибка при перерасчете рейтинга одной сцены', 'color: #F44336; font-weight: bold', error)
          alert('Ошибка при перерасчете рейтинга сцены. Попробуйте снова.')
        }
      } else {
        // Перерасчет всего сценария: GET запрос
        console.log('%c[App] 🔄 Перерасчет рейтинга всего сценария', 'color: #2196F3; font-weight: bold', { docId })

        try {
          const result = await ratingRecalc(docId)

          // Детальное логирование ответа от бэкенда
          console.log('%c[App] 📥 Ответ от ratingRecalc', 'color: #9C27B0; font-weight: bold', {
            hasResult: !!result,
            resultType: typeof result,
            isArray: Array.isArray(result),
            keys: result ? Object.keys(result).slice(0, 20) : [],
            totalKeys: result ? Object.keys(result).length : 0,
            hasFinalRating: !!(result?.final_rating),
            hasProblemFragments: !!(result?.problem_fragments),
            problemFragmentsCount: Array.isArray(result?.problem_fragments) ? result.problem_fragments.length : 0,
            hasParentsGuide: !!(result?.parents_guide),
            hasOutput: !!(result?.output),
            result: result
          })

          // Бэкенд может вернуть данные напрямую или обёрнутыми в output
          let rawOutput = result
          if (result?.output) {
            rawOutput = result.output
            console.log('%c[App] 📦 Данные обёрнуты в output', 'color: #FF9800', {
              outputKeys: Object.keys(rawOutput).slice(0, 20),
              hasFinalRating: !!rawOutput.final_rating,
              problemFragmentsCount: Array.isArray(rawOutput.problem_fragments) ? rawOutput.problem_fragments.length : 0
            })
          }

          // Проверяем, есть ли данные для анализа
          const hasAnalysisData = rawOutput && (
            rawOutput.final_rating ||
            rawOutput.problem_fragments ||
            rawOutput.parents_guide ||
            (Array.isArray(rawOutput.problem_fragments) && rawOutput.problem_fragments.length > 0)
          )

          if (hasAnalysisData) {
            console.log('%c[App] ✅ Обнаружены данные анализа, нормализуем...', 'color: #4CAF50; font-weight: bold', {
              finalRating: rawOutput.final_rating,
              modelFinalRating: rawOutput.model_final_rating,
              hasModelExplanation: !!rawOutput.model_explanation,
              modelExplanationPreview: rawOutput.model_explanation ? rawOutput.model_explanation.substring(0, 150) + '...' : null,
              rawOutputKeys: Object.keys(rawOutput),
              problemFragmentsCount: Array.isArray(rawOutput.problem_fragments) ? rawOutput.problem_fragments.length : 0,
              scenesTotal: rawOutput.scenes_total,
              existingAnalysisId: analysisData?.id
            })

            // ВАЖНО: Сохраняем существующий id при перерасчете, чтобы не сбрасывать состояние в ResultsPage
            const existingId = analysisData?.id || null
            const normalised = normaliseAnalysisFromRaw(rawOutput, scriptScenes, existingId)

            console.log('%c[App] 📊 Нормализованные данные', 'color: #2196F3; font-weight: bold', {
              finalRating: normalised.finalRating,
              hasModelExplanation: !!normalised.model_explanation,
              modelExplanationPreview: normalised.model_explanation ? normalised.model_explanation.substring(0, 150) + '...' : null,
              evidenceCount: normalised.evidence?.length ?? 0,
              problemFragmentsCount: normalised.problemFragments?.length ?? 0,
              reasonsCount: normalised.reasons?.length ?? 0,
              normalisedKeys: Object.keys(normalised)
            })

            const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
            const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }

            const updatedAnalysisData = {
              ...normalised,
              stageProgress: completedStageProgress,
              stages: completedStages
            }

            console.log('%c[App] 💾 Сохраняем в analysisData', 'color: #9C27B0; font-weight: bold', {
              hasModelExplanation: !!updatedAnalysisData.model_explanation,
              modelExplanationPreview: updatedAnalysisData.model_explanation ? updatedAnalysisData.model_explanation.substring(0, 150) + '...' : null,
              updatedKeys: Object.keys(updatedAnalysisData)
            })

            setAnalysisData(updatedAnalysisData)

            console.log('%c[App] ✅ Рейтинг всего сценария пересчитан и обновлён', 'color: #4CAF50; font-weight: bold', {
              finalRating: normalised.finalRating,
              evidenceCount: normalised.evidence?.length ?? 0,
              problemFragmentsCount: normalised.problemFragments?.length ?? 0
            })
          } else {
            console.warn('%c[App] ⚠️ Бэкенд не вернул данные анализа, пробуем получить финальный отчёт', 'color: #FF9800; font-weight: bold', {
              resultKeys: result ? Object.keys(result).slice(0, 10) : [],
              rawOutputKeys: rawOutput ? Object.keys(rawOutput).slice(0, 10) : []
            })

            // Если бэкенд не вернул полный анализ, пробуем получить финальный отчёт
            try {
              const stageFinal = await getStage(docId, 'final')
              const finalRawOutput = stageFinal?.output ?? stageFinal

              console.log('%c[App] 📥 Ответ от getStage(final)', 'color: #9C27B0', {
                hasStageFinal: !!stageFinal,
                hasOutput: !!stageFinal?.output,
                hasFinalRating: !!finalRawOutput?.final_rating,
                problemFragmentsCount: Array.isArray(finalRawOutput?.problem_fragments) ? finalRawOutput.problem_fragments.length : 0
              })

              if (finalRawOutput && (finalRawOutput.final_rating || finalRawOutput.problem_fragments)) {
                // ВАЖНО: Сохраняем существующий id при перерасчете
                const existingId = analysisData?.id || null
                const normalised = normaliseAnalysisFromRaw(finalRawOutput, scriptScenes, existingId)
                const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
                const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }

                setAnalysisData({
                  ...normalised,
                  stageProgress: completedStageProgress,
                  stages: completedStages
                })

                console.log('%c[App] ✅ Данные получены из final stage', 'color: #4CAF50; font-weight: bold', {
                  finalRating: normalised.finalRating,
                  evidenceCount: normalised.evidence?.length ?? 0
                })
              } else {
                console.warn('%c[App] ⚠️ Final stage тоже не содержит данных', 'color: #FF9800')
              }
            } catch (finalError) {
              console.error('%c[App] ❌ Ошибка при получении final stage', 'color: #F44336', finalError)
            }
          }
        } catch (error) {
          console.error('%c[App] ❌ Ошибка при перерасчете рейтинга всего сценария', 'color: #F44336; font-weight: bold', error)
          alert('Ошибка при перерасчете рейтинга. Попробуйте снова.')
        }
      }
      return
    }

    // Fallback: старое поведение на моках (если нет docId).
    try {
      const { mockReanalyzeScript } = await import('./utils/mockApi.js')

      const requestPayload = payload?.all_scenes
        ? payload
        : buildAllScenesPayload(Array.isArray(payload) ? payload : scriptScenes)

      const newAnalysis = await mockReanalyzeScript(requestPayload)
      setAnalysisData(newAnalysis)
    } catch (error) {
      console.error('Error reanalyzing script:', error)
    }
  }, [docId, scriptScenes])

  const handleHistorySelect = async (item) => {
    // Восстанавливаем данные из истории.
    // Если есть docId — пробуем подтянуть актуальные сцены и анализ с бэка,
    // иначе используем сохранённые во фронте.
    let restoredScenes = item.scriptScenes ?? []
    let restoredDocId = item.docId ?? null

    try {
      if (item.docId) {
        // Загружаем сцены с бэкенда
        const backendScenes = await getScenario(item.docId)
        const normalisedScenes = normaliseScriptScenes(backendScenes)
        restoredScenes = normalisedScenes
        restoredDocId = item.docId
        setScriptScenes(normalisedScenes)
        setDocId(item.docId)
        // Восстанавливаем оригинальное имя файла из истории
        if (item.fileName) {
          setOriginalFileName(item.fileName)
        }
        // Восстанавливаем сырые данные от бэка, если они есть в истории
        if (item.rawBackendScenes && Array.isArray(item.rawBackendScenes)) {
          setRawBackendScenes(item.rawBackendScenes)
        } else {
          // Если нет в истории, пробуем получить через GET запрос
          try {
            const scenarioData = await getScenario(item.docId)
            if (Array.isArray(scenarioData) && scenarioData.length > 0) {
              setRawBackendScenes(scenarioData)
            }
          } catch (error) {
            console.warn('Не удалось получить сырые данные сценария из истории', error)
            setRawBackendScenes([])
          }
        }

        // Запрашиваем анализ с бэкенда
        console.log('%c[App] 🔄 Загрузка анализа из истории с бэкенда', 'color: #2196F3; font-weight: bold', { docId: item.docId })
        try {
          const stageFinal = await getStage(item.docId, 'final')

          // Проверяем, что получили валидные данные
          if (stageFinal && !stageFinal.detail) {
            const rawOutput = stageFinal.output ?? stageFinal

            // Проверяем, что это действительно финальный отчёт
            if (rawOutput && (rawOutput.final_rating || rawOutput.problem_fragments || rawOutput.parents_guide)) {
              console.log('%c[App] ✅ Анализ получен с бэкенда', 'color: #4CAF50; font-weight: bold', {
                hasFinalRating: !!rawOutput.final_rating,
                problemFragmentsCount: rawOutput.problem_fragments?.length,
                scenesTotal: rawOutput.scenes_total
              })

              // Нормализуем данные анализа с учётом загруженных сцен
              const normalised = normaliseAnalysisFromRaw(rawOutput, normalisedScenes)

              // Устанавливаем все стадии в 100%, так как это завершённый анализ
              const completedStages = normalised.stages.map(s => ({ ...s, progress: 100, status: 'completed' }))
              const completedStageProgress = { stage1: 100, stage2: 100, stage3: 100 }

              setAnalysisData({
                ...normalised,
                stageProgress: completedStageProgress,
                stages: completedStages
              })

              setCurrentPage('results')
              return // Выходим, так как данные уже установлены
            } else {
              console.warn('%c[App] ⚠️ Данные от бэкенда не похожи на финальный отчёт', 'color: #FF9800', {
                keys: Object.keys(rawOutput).slice(0, 10)
              })
            }
          } else if (stageFinal?.detail) {
            console.log('%c[App] ⚠️ Final ещё не готов на бэкенде, используем данные из истории', 'color: #FF9800', {
              detail: stageFinal.detail
            })
          }
        } catch (analysisError) {
          // 404 означает, что анализ ещё не готов - это нормально, используем данные из истории
          const is404 = analysisError.status === 404 || analysisError.message?.includes('404')
          if (!is404) {
            console.error('%c[App] ❌ Ошибка при загрузке анализа с бэкенда, используем данные из истории', 'color: #F44336', analysisError)
          } else {
            console.log('%c[App] ⚠️ Анализ ещё не готов на бэкенде (404), используем данные из истории', 'color: #FF9800')
          }
        }
      } else if (item.scriptScenes) {
        restoredScenes = item.scriptScenes
        restoredDocId = null
        setScriptScenes(item.scriptScenes)
        setDocId(null)
      }
    } catch (error) {
      console.error('Error loading scenario from backend, using stored scriptScenes:', error)
      if (item.scriptScenes) {
        restoredScenes = item.scriptScenes
        setScriptScenes(item.scriptScenes)
      }
      restoredDocId = item.docId ?? null
      setDocId(restoredDocId)
    }

    // Восстанавливаем все данные анализа из истории (fallback, если бэкенд не вернул данные)
    // Важно сохранить все поля, включая stages, stageProgress и другие
    if (item) {
      // Восстанавливаем оригинальное имя файла из истории
      if (item.fileName) {
        setOriginalFileName(item.fileName)
      }
      const restoredAnalysis = {
        id: item.id ?? `analysis_${Date.now()}`,
        document: item.document ?? item.fileName ?? '',
        age_label: item.age_label ?? '',
        age_confidence: item.age_confidence ?? 0.65,
        scenes_total: item.scenes_total ?? restoredScenes.length,
        parents_guide: item.parents_guide ?? {},
        reasons: item.reasons ?? [],
        evidence: item.evidence ?? [],
        problem_fragments: item.problem_fragments ?? [],
        law_explanation: item.law_explanation ?? null,
        processing_seconds: item.processing_seconds ?? 0,
        // Восстанавливаем стадии и прогресс, если они есть в истории
        stages: item.stages ?? [
          { id: 'stage1', label: 'Первичная классификация', progress: 100, status: 'completed' },
          { id: 'stage2', label: 'Обогащение метаданными', progress: 100, status: 'completed' },
          { id: 'stage3', label: 'Финальная интерпретация', progress: 100, status: 'completed' }
        ],
        stageProgress: item.stageProgress ?? {
          stage1: 100,
          stage2: 100,
          stage3: 100
        },
        raw: item.raw ?? {}
      }

      // Нормализуем данные из истории с учётом загруженных сцен
      // Это важно для правильного отображения фрагментов
      if (restoredAnalysis.problem_fragments?.length > 0 || restoredAnalysis.evidence?.length > 0) {
        const normalised = normaliseAnalysisFromRaw({
          final_rating: restoredAnalysis.age_label,
          scenes_total: restoredAnalysis.scenes_total,
          parents_guide: restoredAnalysis.parents_guide,
          problem_fragments: restoredAnalysis.problem_fragments,
          law_explanation: restoredAnalysis.law_explanation,
          processing_seconds: restoredAnalysis.processing_seconds
        }, restoredScenes)

        setAnalysisData({
          ...normalised,
          stages: restoredAnalysis.stages,
          stageProgress: restoredAnalysis.stageProgress,
          raw: restoredAnalysis.raw
        })
      } else {
        setAnalysisData(restoredAnalysis)
      }
    } else {
      setAnalysisData(null)
    }

    setCurrentPage('results')
  }

  return (
    <div className="min-h-screen bg-wink-black relative overflow-hidden">
      <Header
        onBack={currentPage === 'results' ? handleBackToUpload : undefined}
        showLogo={headerConfig.showLogo}
        leftExtras={headerConfig.leftExtras}
        leftOrientation={headerConfig.leftOrientation}
      >
        {headerConfig.rightContent}
      </Header>

      {currentPage === 'upload' ? (
        <UploadPage
          onFileUpload={handleFileUpload}
          history={history}
          onHistorySelect={handleHistorySelect}
        />
      ) : (
        <ResultsPage
          analysisData={analysisData}
          scriptScenes={scriptScenes}
          onScriptUpdate={setScriptScenes}
          onReanalyze={handleReanalyze}
          configureHeader={updateHeaderConfig}
          docId={docId}
          setAnalysisData={setAnalysisData}
          originalFileName={originalFileName || analysisData?.document}
          rawBackendScenes={rawBackendScenes}
        />
      )}
    </div>
  )
}

export default App
