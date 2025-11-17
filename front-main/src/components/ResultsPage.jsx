import { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import AnalysisPanel from './AnalysisPanel'
import ScriptEditor from './ScriptEditor'
import ViolationEditorModal from './ViolationEditorModal'
import { AVAILABLE_LABELS, detectReason as detectReasonFromLabels, getLabelDetails } from '../utils/mockApi'
import { HistoryIcon, photoBackImg, UploadIcon } from '../utils/icons'
import { buildAllScenesPayload, splitSceneIntoSentences } from '../utils/sceneUtils'
import { API_BASE_URL } from '../api/client'

const DEFAULT_PANEL_WIDTH = 520

const buildPaginationItems = (total, currentPage) => {
    if (total <= 7) {
        return Array.from({ length: total }, (_, index) => ({ type: 'page', value: index + 1 }))
    }

    if (currentPage <= 4) {
        const items = Array.from({ length: 5 }, (_, index) => ({ type: 'page', value: index + 1 }))
        items.push({ type: 'ellipsis', id: 'right' })
        items.push({ type: 'page', value: total })
        return items
    }

    if (currentPage >= total - 3) {
        const items = [{ type: 'page', value: 1 }, { type: 'ellipsis', id: 'left' }]
        const start = Math.max(total - 4, 2)
        for (let page = start; page <= total; page += 1) {
            items.push({ type: 'page', value: page })
        }
        return items
    }

    const items = [
        { type: 'page', value: 1 },
        { type: 'ellipsis', id: 'mid-left' },
        { type: 'page', value: currentPage - 1 },
        { type: 'page', value: currentPage },
    ]

    const nextPage = Math.min(currentPage + 1, total - 1)
    if (nextPage > currentPage) {
        items.push({ type: 'page', value: nextPage })
    }

    if (nextPage < total - 1) {
        items.push({ type: 'ellipsis', id: 'mid-right' })
    }

    items.push({ type: 'page', value: total })
    return items
}

const REASON_LABELS = {
    violence: 'Насилие',
    profanity: 'Лексика',
    weapons: 'Оружие',
    crime: 'Преступность',
    substances: 'Алкоголь и вещества',
    sexual_content: 'Секс и нагота',
    fear: 'Страх и напряжение',
    other: 'Прочее'
}

const ResultsPage = ({ analysisData, scriptScenes = [], onScriptUpdate, onReanalyze, configureHeader, docId, setAnalysisData, originalFileName, rawBackendScenes = [] }) => {
    const [editedScenes, setEditedScenes] = useState(() => scriptScenes ?? [])
    const [editedFragments, setEditedFragments] = useState({})
    const [isPanelOpen, setIsPanelOpen] = useState(true)
    const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
    const [isPanelExpanded, setIsPanelExpanded] = useState(false)
    const [activeFragmentId, setActiveFragmentId] = useState(null)
    const [dismissedFragments, setDismissedFragments] = useState([])
    const [manualFragments, setManualFragments] = useState([])
    const [fragmentMetadataOverrides, setFragmentMetadataOverrides] = useState({})
    const [violationModalState, setViolationModalState] = useState({ isOpen: false, mode: 'add', fragment: null, initialData: null })
    const [currentSceneIndex, setCurrentSceneIndex] = useState(0)
    const [viewportWidth, setViewportWidth] = useState(() => (typeof window !== 'undefined' ? window.innerWidth : 1440))
    // Отслеживание измененных и пересчитанных сцен
    const [changedScenes, setChangedScenes] = useState(new Set())
    const [recalculatedScenes, setRecalculatedScenes] = useState(new Set())

    // hasPendingChanges = есть измененные сцены, которые не были пересчитаны
    const hasPendingChanges = useMemo(() => {
        if (changedScenes.size === 0) return false
        // Проверяем, что все измененные сцены были пересчитаны
        for (const sceneNumber of changedScenes) {
            if (!recalculatedScenes.has(sceneNumber)) {
                return true
            }
        }
        return false
    }, [changedScenes, recalculatedScenes])

    const isLocalUpdateRef = useRef(false)
    const prevAnalysisDataIdRef = useRef(null)

    useEffect(() => {
        if (isLocalUpdateRef.current) {
            setEditedScenes(scriptScenes ?? [])
            isLocalUpdateRef.current = false
            return
        }

        setEditedScenes(scriptScenes ?? [])
        setActiveFragmentId(null)
        setCurrentSceneIndex(0)
        // НЕ сбрасываем editedFragments, dismissedFragments и manualFragments при обновлении scriptScenes
        // Это позволяет сохранить пользовательские изменения
    }, [scriptScenes])

    // Отдельный useEffect для обработки обновлений analysisData
    useEffect(() => {
        // ВАЖНО: Не сбрасываем editedFragments и dismissedFragments при обновлении analysisData
        // Это позволяет сохранить пользовательские изменения при перерасчете
        // Сбрасываем только если это новый анализ (новый id)
        const isNewAnalysis = analysisData?.id &&
            (prevAnalysisDataIdRef.current !== analysisData.id)

        if (isNewAnalysis) {
            console.log('%c[ResultsPage] 🔄 Новый анализ, сбрасываем состояние', 'color: #2196F3', {
                oldId: prevAnalysisDataIdRef.current,
                newId: analysisData.id,
                evidenceCount: analysisData?.evidence?.length ?? 0
            })
            setEditedFragments({})
            setDismissedFragments([])
            setManualFragments([])
            setFragmentMetadataOverrides({})
            // Сбрасываем отслеживание изменений при новом анализе
            setChangedScenes(new Set())
            setRecalculatedScenes(new Set())
            prevAnalysisDataIdRef.current = analysisData.id
        } else if (analysisData?.evidence) {
            console.log('%c[ResultsPage] 🔄 Обновление существующего анализа', 'color: #9C27B0', {
                analysisId: analysisData?.id,
                evidenceCount: analysisData?.evidence?.length ?? 0,
                preservedFragments: Object.keys(editedFragments).length,
                preservedDismissed: dismissedFragments.length
            })
        }

        // Не сбрасываем hasPendingChanges при обновлении analysisData - это может быть перерасчет
    }, [analysisData?.id, analysisData?.evidence?.length])

    // Удалён дублирующий useEffect - логика перенесена в useEffect выше

    const combinedEvidence = useMemo(() => {
        const base = analysisData?.evidence ?? []
        return [...base, ...manualFragments]
    }, [analysisData, manualFragments])

    const filteredEvidence = useMemo(() => {
        if (!combinedEvidence.length) return []
        const dismissedSet = new Set(dismissedFragments)
        return combinedEvidence.filter(fragment => !dismissedSet.has(fragment.id))
    }, [combinedEvidence, dismissedFragments])

    const resolvedFragments = useMemo(() => {
        return filteredEvidence.map(fragment => {
            const override = fragmentMetadataOverrides[fragment.id]
            const baseText = fragment.text
            const merged = override
                ? {
                    ...fragment,
                    ...override,
                    labels: override.labels ?? fragment.labels,
                    severity: override.severity ?? fragment.severity,
                    evidenceSpans: override.evidenceSpans ?? fragment.evidenceSpans,
                    recommendations: override.recommendations ?? fragment.recommendations
                }
                : fragment

            return {
                ...merged,
                originalText: fragment.originalText ?? baseText,
                text: editedFragments[fragment.id] ?? baseText
            }
        })
    }, [filteredEvidence, editedFragments, fragmentMetadataOverrides])

    const analysisWithResolved = useMemo(() => {
        if (!analysisData) return null
        return {
            ...analysisData,
            evidence: resolvedFragments
        }
    }, [analysisData, resolvedFragments])

    const sceneIndexByNumber = useMemo(() => {
        const map = new Map()
        editedScenes.forEach((scene, index) => {
            if (scene?.sceneNumber !== undefined) {
                map.set(scene.sceneNumber, index)
            }
        })
        return map
    }, [editedScenes])

    const replaceFragmentText = useCallback((source = '', target = '', replacement = '', occurrenceIndex = 0) => {
        if (!target) return source

        let searchStartPos = 0
        let occurrenceCount = 0

        while (searchStartPos < source.length) {
            const position = source.indexOf(target, searchStartPos)
            if (position === -1) break

            if (occurrenceCount === occurrenceIndex) {
                return `${source.slice(0, position)}${replacement}${source.slice(position + target.length)}`
            }

            occurrenceCount++
            searchStartPos = position + target.length
        }

        // Если не нашли нужное вхождение, заменяем первое (как fallback)
        const position = source.indexOf(target)
        if (position === -1) return source
        return `${source.slice(0, position)}${replacement}${source.slice(position + target.length)}`
    }, [])

    const handleFragmentEdit = useCallback(async (fragment, newText) => {
        if (!fragment) return
        const sceneNumber = fragment.sceneIndex
        const originalText = fragment.originalText ?? fragment.text ?? ''
        const occurrenceIndex = fragment.sceneFragmentIndex ?? 0
        const sentenceIndex = fragment.sentenceIndex

        // Если есть docId, отправляем на бэкенд
        if (docId && sentenceIndex !== null && sentenceIndex !== undefined) {
            // Находим scene_index (0-based индекс сцены в массиве)
            const sceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === sceneNumber)
            if (sceneIndex === -1) {
                console.error('Cannot find scene index for sceneNumber', sceneNumber)
                // Fallback на локальное редактирование
            } else {
                try {
                    const { editSentence } = await import('../api/analysisApi.js')
                    const result = await editSentence(docId, {
                        scene_index: sceneIndex,
                        sentence_index: sentenceIndex,
                        text: newText
                    })

                    // Бэкенд возвращает обновленный output.json
                    if (result && (result.final_rating || result.problem_fragments || result.parents_guide)) {
                        const { normaliseAnalysisFromRaw } = await import('../utils/mockApi.js')
                        const existingId = analysisData?.id || null
                        const normalised = normaliseAnalysisFromRaw(result, scriptScenes, existingId)

                        // Обновляем analysisData через onReanalyze (который обновит analysisData в App.jsx)
                        // Но сначала обновляем локально для немедленного отображения
                        setAnalysisData?.(prev => ({
                            ...normalised,
                            stageProgress: prev?.stageProgress ?? normalised.stageProgress,
                            stages: prev?.stages ?? normalised.stages
                        }))

                        console.log('%c[ResultsPage] ✅ Предложение отредактировано на бэкенде', 'color: #4CAF50; font-weight: bold', {
                            sceneIndex,
                            sentenceIndex,
                            newText
                        })

                        // Помечаем сцену как измененную
                        setChangedScenes(prev => new Set([...prev, sceneNumber]))
                    }
                } catch (error) {
                    console.error('%c[ResultsPage] ❌ Ошибка при редактировании предложения', 'color: #F44336; font-weight: bold', error)
                    // Fallback на локальное редактирование
                }
            }
        }

        // Обновляем editedFragments
        setEditedFragments(prev => ({
            ...prev,
            [fragment.id]: newText
        }))

        // Сбрасываем метки (labels) при редактировании фрагмента
        // Пользователь должен либо вручную добавить метки, либо пересчитать рейтинг
        setFragmentMetadataOverrides(prev => ({
            ...prev,
            [fragment.id]: {
                ...(prev[fragment.id] ?? {}),
                labels: [] // Сбрасываем метки
            }
        }))

        // Обновляем текст в сцене
        setEditedScenes(prevScenes => {
            const updatedScenes = prevScenes.map(scene => {
                if (scene.sceneNumber !== sceneNumber) return scene

                let updatedContent = scene.content ?? ''

                // Если есть sentenceIndex, используем его для точной замены предложения
                if (sentenceIndex !== null && sentenceIndex !== undefined && scene.originalSentences) {
                    const sentences = splitSceneIntoSentences(updatedContent)
                    if (sentenceIndex >= 0 && sentenceIndex < sentences.length) {
                        // Сохраняем старый текст ДО замены для логирования
                        const oldSentenceText = sentences[sentenceIndex]

                        // Заменяем предложение по индексу
                        sentences[sentenceIndex] = newText
                        updatedContent = sentences.join('\n\n')

                        console.log('%c[ResultsPage] ✏️ Редактирование фрагмента через sentenceIndex', 'color: #9C27B0', {
                            fragmentId: fragment.id,
                            sentenceIndex,
                            oldText: oldSentenceText,
                            newText,
                            textsMatch: oldSentenceText === newText,
                            contentLength: updatedContent.length,
                            sentencesCount: sentences.length
                        })

                        // Проверяем, что текст действительно изменился
                        if (oldSentenceText === newText) {
                            console.warn('%c[ResultsPage] ⚠️ Текст не изменился!', 'color: #FF9800; font-weight: bold', {
                                fragmentId: fragment.id,
                                sentenceIndex,
                                text: newText,
                                possibleCause: 'newText совпадает с текущим текстом предложения'
                            })
                        }
                    } else {
                        // Fallback: используем поиск по тексту
                        updatedContent = replaceFragmentText(updatedContent, originalText, newText, occurrenceIndex)
                    }
                } else {
                    // Fallback: используем поиск по тексту
                    updatedContent = replaceFragmentText(updatedContent, originalText, newText, occurrenceIndex)
                }

                // Обновляем originalSentences при редактировании фрагмента
                const newSentences = splitSceneIntoSentences(updatedContent)
                const updatedOriginalSentences = newSentences.map((text, idx) => ({
                    id: idx,
                    text: text
                }))

                return {
                    ...scene,
                    content: updatedContent,
                    originalSentences: updatedOriginalSentences.length > 0 ? updatedOriginalSentences : null
                }
            })
            isLocalUpdateRef.current = true

            // ВАЖНО: Обновляем родительский компонент асинхронно, чтобы избежать warning
            // React не позволяет обновлять родительский компонент во время рендеринга
            setTimeout(() => {
                onScriptUpdate?.(updatedScenes)
            }, 0)

            return updatedScenes
        })

        setActiveFragmentId(fragment.id)
        const targetIndex = sceneIndexByNumber.get(sceneNumber)
        if (targetIndex !== undefined) {
            setCurrentSceneIndex(targetIndex)
        }
        // Помечаем сцену как измененную
        setChangedScenes(prev => new Set([...prev, sceneNumber]))
    }, [onScriptUpdate, replaceFragmentText, sceneIndexByNumber])

    const handleFragmentReplace = useCallback(async (fragment, targetAgeRating = '') => {
        // Если нет docId, используем старое поведение (fallback на моки)
        if (!docId) {
            const { mockAIReplace } = await import('../utils/mockApi.js')
            const originalText = fragment.originalText ?? fragment.text
            const suggestion = await mockAIReplace(originalText, fragment.reason, targetAgeRating)
            handleFragmentEdit({ ...fragment }, suggestion)
            return
        }

        // Находим сцену с фрагментом
        const sceneNumber = fragment.sceneIndex
        const targetScene = editedScenes.find(scene => scene.sceneNumber === sceneNumber)
        if (!targetScene) {
            console.error('Scene not found for fragment', fragment)
            return
        }

        // ВАЖНО: replace_sentences_id должен содержать ID предложений (из поля id в sentences),
        // а не индексы!
        // fragment.sentenceIndex - это индекс предложения в сцене (0-based)
        const sentenceIndex = fragment.sentenceIndex ?? null

        if (sentenceIndex === null || sentenceIndex === undefined) {
            console.error('Cannot find sentence_index for fragment', fragment)
            alert('Не удалось определить предложение для замены. Попробуйте отредактировать вручную.')
            return
        }

        // Находим id предложения из originalSentences
        let sentenceId = null
        if (targetScene.originalSentences && Array.isArray(targetScene.originalSentences)) {
            if (sentenceIndex >= 0 && sentenceIndex < targetScene.originalSentences.length) {
                sentenceId = targetScene.originalSentences[sentenceIndex]?.id ?? sentenceIndex
            }
        }

        // Если не нашли id, используем sentenceIndex как fallback
        if (sentenceId === null) {
            sentenceId = sentenceIndex
        }

        // Формируем payload для AI replace
        const { buildAllScenesPayload } = await import('../utils/sceneUtils.js')
        const scenePayload = buildAllScenesPayload([targetScene])

        // Устанавливаем replace_sentences_id - это ID предложений (из поля id в sentences)
        if (scenePayload.all_scenes && scenePayload.all_scenes.length > 0) {
            // Проверяем, что предложение с таким id существует
            const sentenceExists = scenePayload.all_scenes[0].sentences?.some(s => s.id === sentenceId)
            if (sentenceExists) {
                scenePayload.all_scenes[0].replace_sentences_id = [sentenceId] // Используем id, а не индекс!
                scenePayload.all_scenes[0].age_rating = targetAgeRating
            } else {
                console.error('Sentence with id not found', {
                    sentenceId,
                    sentenceIndex,
                    sentences: scenePayload.all_scenes[0].sentences,
                    fragment
                })
                alert('Предложение с таким id не найдено. Попробуйте отредактировать вручную.')
                return
            }
        }

        // Детальное логирование payload перед отправкой
        console.log('%c[ResultsPage] 🤖 Запрос замены через AI', 'color: #9C27B0; font-weight: bold', {
            docId,
            sceneNumber,
            sentenceIndex,
            targetAgeRating,
            payload: JSON.parse(JSON.stringify(scenePayload)), // Глубокое копирование для логирования
            targetSentence: targetScene.originalSentences?.[sentenceIndex],
            targetSentenceId: targetScene.originalSentences?.[sentenceIndex]?.id,
            allSentences: targetScene.originalSentences?.slice(0, 5),
            sentencesCount: targetScene.originalSentences?.length,
            replace_sentences_id: scenePayload.all_scenes?.[0]?.replace_sentences_id,
            sentencesInPayload: scenePayload.all_scenes?.[0]?.sentences?.map(s => ({ id: s.id, text: s.text?.substring(0, 50) }))
        })

        try {
            const { aiReplace } = await import('../api/analysisApi.js')
            const result = await aiReplace(docId, scenePayload)

            // Детальное логирование ответа от бэкенда
            console.log('%c[ResultsPage] 📥 Ответ от AI replace', 'color: #9C27B0; font-weight: bold', {
                hasResult: !!result,
                resultType: typeof result,
                isArray: Array.isArray(result),
                keys: result ? Object.keys(result).slice(0, 20) : [],
                result: result
            })

            // Проверяем mode ответа
            if (result?.mode === 'noop') {
                console.warn('%c[ResultsPage] ⚠️ Бэкенд вернул mode: "noop"', 'color: #FF9800; font-weight: bold', {
                    mode: result.mode,
                    elapsed_seconds: result.elapsed_seconds,
                    possibleCause: 'AI не смог предложить замену или решил не изменять текст'
                })
                alert('AI не смог предложить замену для этого фрагмента. Бэкенд вернул mode: "noop". Попробуйте отредактировать текст вручную.')
                return
            }

            // Обрабатываем результат
            if (result && result.results && result.results.length > 0) {
                const sceneResult = result.results[0]
                console.log('%c[ResultsPage] 📦 Scene result', 'color: #2196F3', {
                    sceneResult,
                    replacementsCount: sceneResult.replacements?.length ?? 0,
                    replacements: sceneResult.replacements,
                    mode: result.mode,
                    elapsed_seconds: result.elapsed_seconds
                })

                if (sceneResult.replacements && sceneResult.replacements.length > 0) {
                    // Находим замену для нашего sentence_id
                    // Бэкенд возвращает sentence_id, который соответствует id из sentences
                    const replacement = sceneResult.replacements.find(r => r.sentence_id === sentenceId)

                    if (!replacement) {
                        console.warn('%c[ResultsPage] ⚠️ Замена не найдена по sentence_id', 'color: #FF9800', {
                            sentenceId,
                            sentenceIndex,
                            allReplacements: sceneResult.replacements,
                            possibleCause: 'sentence_id в ответе не совпадает с отправленным id'
                        })
                        // Fallback: берем первую замену, если не нашли по id
                        const fallbackReplacement = sceneResult.replacements[0]
                        if (fallbackReplacement) {
                            console.log('%c[ResultsPage] 🔄 Используем первую замену как fallback', 'color: #FF9800', {
                                fallbackReplacement
                            })
                            // Используем fallback, но это может быть неправильная замена
                        } else {
                            alert('AI не вернул замену для этого предложения.')
                            return
                        }
                    }

                    const finalReplacement = replacement || sceneResult.replacements[0]

                    console.log('%c[ResultsPage] 🔍 Найденная замена', 'color: #FF9800', {
                        sentenceIndex,
                        sentenceId,
                        replacement: finalReplacement,
                        allReplacements: sceneResult.replacements,
                        replacementSentenceId: finalReplacement?.sentence_id
                    })

                    if (finalReplacement && finalReplacement.new_sentence) {
                        // Извлекаем текст из формата "мягко[текст]" если нужно
                        let newText = finalReplacement.new_sentence
                        const originalNewText = newText

                        console.log('%c[ResultsPage] 📝 Обработка new_sentence', 'color: #2196F3', {
                            originalNewText,
                            length: originalNewText.length,
                            hasBrackets: originalNewText.includes('['),
                            hasMягко: originalNewText.toLowerCase().includes('мягко')
                        })

                        // Пробуем разные форматы:
                        // 1. "мягко[текст]" - извлекаем текст из скобок
                        const bracketMatch = newText.match(/\[(.*?)\]/)
                        if (bracketMatch) {
                            newText = bracketMatch[1]
                            console.log('%c[ResultsPage] 📝 Извлечен текст из скобок', 'color: #4CAF50', {
                                original: originalNewText,
                                extracted: newText,
                                bracketContent: bracketMatch[1]
                            })
                        }

                        // 2. Если текст начинается с "мягко" или другого префикса, убираем его
                        if (newText.toLowerCase().startsWith('мягко')) {
                            const before = newText
                            newText = newText.replace(/^мягко\s*/i, '').trim()
                            console.log('%c[ResultsPage] 📝 Убран префикс "мягко"', 'color: #4CAF50', {
                                before,
                                after: newText
                            })
                        }

                        // 3. Если текст все еще содержит "мягко" в начале, пробуем убрать его другим способом
                        if (newText.toLowerCase().trim().startsWith('мягко')) {
                            const before = newText
                            newText = newText.replace(/^мягко\s*:?\s*/i, '').trim()
                            console.log('%c[ResultsPage] 📝 Убран префикс "мягко" (вариант 2)', 'color: #4CAF50', {
                                before,
                                after: newText
                            })
                        }

                        console.log('%c[ResultsPage] ✅ AI замена получена', 'color: #4CAF50; font-weight: bold', {
                            original: fragment.text,
                            originalNewText,
                            finalReplacement: newText,
                            textsMatch: fragment.text === newText,
                            sentenceIndex,
                            sentenceId: targetScene.originalSentences?.[sentenceIndex]?.id
                        })

                        // Проверяем, что текст действительно изменился
                        // Сравниваем с оригинальным текстом фрагмента (trim для надежности)
                        const originalTextTrimmed = fragment.text?.trim() ?? ''
                        const newTextTrimmed = newText?.trim() ?? ''

                        if (originalTextTrimmed === newTextTrimmed) {
                            console.warn('%c[ResultsPage] ⚠️ AI вернул тот же текст!', 'color: #FF9800; font-weight: bold', {
                                original: fragment.text,
                                originalTrimmed: originalTextTrimmed,
                                replacement: newText,
                                replacementTrimmed: newTextTrimmed,
                                mode: result.mode,
                                possibleCause: 'AI не смог предложить замену или вернул оригинальный текст. Возможно, бэкенд не может смягчить этот фрагмент для целевого рейтинга.'
                            })
                            alert(`AI не смог предложить замену для этого фрагмента.\n\nОригинал: "${originalTextTrimmed}"\nAI вернул: "${newTextTrimmed}"\n\nПопробуйте отредактировать текст вручную или выбрать другой целевой рейтинг.`)
                            return
                        }

                        // Сбрасываем метки (labels) при замене через AI
                        // Пользователь должен либо вручную добавить метки, либо пересчитать рейтинг
                        setFragmentMetadataOverrides(prev => ({
                            ...prev,
                            [fragment.id]: {
                                ...(prev[fragment.id] ?? {}),
                                labels: [] // Сбрасываем метки
                            }
                        }))

                        // Применяем замену
                        handleFragmentEdit({ ...fragment }, newText)
                    } else {
                        console.warn('Replacement not found in result', { sentenceId, replacements: sceneResult.replacements })
                        alert('AI не вернул замену для этого предложения.')
                    }
                } else {
                    console.warn('No replacements in result', result)
                    alert('AI не вернул замены.')
                }
            } else {
                console.warn('Invalid result format', result)
                alert('Неверный формат ответа от AI.')
            }
        } catch (error) {
            console.error('%c[ResultsPage] ❌ Ошибка при замене через AI', 'color: #F44336; font-weight: bold', error)
            alert('Ошибка при замене через AI. Попробуйте снова.')
        }
    }, [docId, editedScenes, handleFragmentEdit, setFragmentMetadataOverrides])

    const handleSceneChange = useCallback((sceneNumber, newContent) => {
        setEditedScenes(prevScenes => {
            const scene = prevScenes.find(s => s.sceneNumber === sceneNumber)
            const oldContent = scene?.content ?? ''

            const updatedScenes = prevScenes.map(scene => {
                if (scene.sceneNumber !== sceneNumber) return scene

                // При редактировании обновляем originalSentences, чтобы сохранить согласование
                // Разбиваем новый content на предложения (по переносам строк)
                const newSentences = splitSceneIntoSentences(newContent)
                const updatedOriginalSentences = newSentences.map((text, idx) => ({
                    id: idx,
                    text: text
                }))

                return {
                    ...scene,
                    content: newContent,
                    originalSentences: updatedOriginalSentences.length > 0 ? updatedOriginalSentences : null
                }
            })

            // Синхронизируем фрагменты: когда редактируем текст в ScriptEditor,
            // обновляем editedFragments для фрагментов на основе нового текста сцены
            // ВАЖНО: используем filteredEvidence (исходные фрагменты), а не resolvedFragments
            // чтобы избежать циклической зависимости
            setEditedFragments(prevEditedFragments => {
                const updatedFragments = { ...prevEditedFragments }
                // Используем исходные фрагменты из filteredEvidence, а не resolvedFragments
                const fragmentsForScene = filteredEvidence.filter(f => f.sceneIndex === sceneNumber)

                // Разбиваем новый контент на предложения для поиска по индексу
                const newSentences = splitSceneIntoSentences(newContent)

                fragmentsForScene.forEach(fragment => {
                    const sentenceIndex = fragment.sentenceIndex

                    // Если есть sentenceIndex, используем его для точного сопоставления
                    if (sentenceIndex !== null && sentenceIndex !== undefined && sentenceIndex >= 0 && sentenceIndex < newSentences.length) {
                        const newSentenceText = newSentences[sentenceIndex].trim()
                        const originalFragmentText = fragment.originalText ?? fragment.text ?? ''
                        const currentFragmentText = prevEditedFragments[fragment.id] ?? originalFragmentText

                        // Если текст предложения изменился, обновляем editedFragments
                        if (newSentenceText && newSentenceText !== currentFragmentText) {
                            updatedFragments[fragment.id] = newSentenceText
                            console.log('%c[ResultsPage] 🔄 Синхронизация фрагмента из текста сцены', 'color: #2196F3', {
                                fragmentId: fragment.id,
                                oldText: currentFragmentText,
                                newText: newSentenceText,
                                sentenceIndex
                            })
                        } else if (newSentenceText === originalFragmentText && prevEditedFragments[fragment.id]) {
                            // Если текст вернулся к оригинальному, удаляем из editedFragments
                            delete updatedFragments[fragment.id]
                        }
                    } else {
                        // Если нет sentenceIndex, используем поиск по тексту в старом контенте
                        const originalFragmentText = fragment.originalText ?? fragment.text ?? ''
                        const currentFragmentText = prevEditedFragments[fragment.id] ?? originalFragmentText

                        // Проверяем, изменился ли текст фрагмента
                        if (oldContent.includes(currentFragmentText) && !newContent.includes(currentFragmentText)) {
                            // Текст был изменен или удален
                            // Если оригинальный текст найден в новом контенте, удаляем editedFragments
                            if (newContent.includes(originalFragmentText)) {
                                delete updatedFragments[fragment.id]
                            }
                        } else if (newContent.includes(originalFragmentText) && prevEditedFragments[fragment.id]) {
                            // Если оригинальный текст найден и был edited, проверяем, нужно ли обновить
                            // Для простоты оставляем как есть, если текст не изменился кардинально
                        }
                    }
                })

                return updatedFragments
            })

            isLocalUpdateRef.current = true

            // ВАЖНО: Обновляем родительский компонент асинхронно, чтобы избежать warning
            // React не позволяет обновлять родительский компонент во время рендеринга
            setTimeout(() => {
                onScriptUpdate?.(updatedScenes)
            }, 0)

            return updatedScenes
        })
        // Помечаем сцену как измененную
        setChangedScenes(prev => new Set([...prev, sceneNumber]))
    }, [onScriptUpdate, filteredEvidence])

    const handleReanalyze = useCallback(() => {
        onReanalyze?.(buildAllScenesPayload(editedScenes))
        // При полном пересчете сбрасываем все флаги - все сцены пересчитаны
        setChangedScenes(new Set())
        setRecalculatedScenes(new Set())
    }, [onReanalyze, editedScenes])

    const handleSceneRecalculate = useCallback((sceneNumber) => {
        if (!sceneNumber) return
        const targetScene = editedScenes.find(scene => scene.sceneNumber === sceneNumber)
        if (!targetScene) return

        // Находим scene_index (0-based индекс сцены в массиве)
        const sceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === sceneNumber)
        if (sceneIndex === -1) {
            console.error('Cannot find scene index for sceneNumber', sceneNumber)
            return
        }

        // Формируем payload в формате, который ожидает бэкенд: { scene_index, heading, page, sentences: string[] }
        const sentences = targetScene.originalSentences && Array.isArray(targetScene.originalSentences) && targetScene.originalSentences.length > 0
            ? targetScene.originalSentences.map(s => typeof s === 'string' ? s : (s.text ?? '')).filter(Boolean)
            : splitSceneIntoSentences(targetScene.content ?? '')

        const scenePayload = {
            scene_index: sceneIndex, // 0-based индекс сцены в массиве
            heading: targetScene.heading ?? '',
            page: targetScene.page ?? null,
            sentences: sentences
        }

        // Если есть docId, передаем напрямую в правильном формате
        // Иначе используем старый формат через buildAllScenesPayload
        if (docId) {
            onReanalyze?.(scenePayload)
        } else {
            onReanalyze?.(buildAllScenesPayload([targetScene]))
        }
        // Помечаем эту сцену как пересчитанную
        setRecalculatedScenes(prev => new Set([...prev, sceneNumber]))
    }, [onReanalyze, editedScenes, docId])

    const handleExportReport = useCallback(() => {
        if (hasPendingChanges) {
            // Находим сцены, которые были изменены, но не пересчитаны
            const pendingScenes = Array.from(changedScenes).filter(sceneNum => !recalculatedScenes.has(sceneNum))
            const pendingScenesList = pendingScenes.length > 0
                ? pendingScenes.map(num => `Сцена ${num}`).join(', ')
                : 'некоторые сцены'

            alert(`⚠️ Сначала необходимо пересчитать рейтинг после внесенных изменений, прежде чем показывать отчет.\n\nНе пересчитаны: ${pendingScenesList}`)
            return
        }

        if (!docId) {
            alert('Ошибка: отсутствует docId')
            return
        }

        // Открываем отчет напрямую по URL в новой вкладке
        const reportUrl = `${API_BASE_URL}/api/report/${encodeURIComponent(docId)}`
        window.open(reportUrl, '_blank', 'noopener,noreferrer')
    }, [hasPendingChanges, changedScenes, recalculatedScenes, docId])

    const handleDownloadScript = useCallback(async () => {
        // Открытие сценария для просмотра в новой вкладке
        if (!docId) {
            alert('Ошибка: отсутствует docId')
            return
        }

        if (!editedScenes || editedScenes.length === 0) {
            alert('Нет сценария для просмотра')
            return
        }

        try {
            // Преобразуем editedScenes в формат для отправки на бэкенд
            const scriptScenesForView = editedScenes.map((scene, index) => ({
                id: scene.id || `scene_${index + 1}`,
                sceneNumber: scene.sceneNumber ?? scene.number ?? index + 1,
                page: scene.page ?? null,
                heading: scene.heading ?? '',
                content: scene.content ?? '',
                originalSentences: scene.originalSentences ?? null,
                blocks: scene.blocks ?? null,
                cast_list: scene.cast_list ?? [],
                meta: scene.meta ?? null,
                number: scene.number ?? String(scene.sceneNumber ?? index + 1),
                number_suffix: scene.number_suffix ?? '',
                ie: scene.ie ?? '',
                location: scene.location ?? '',
                time_of_day: scene.time_of_day ?? '',
                shoot_day: scene.shoot_day ?? '',
                timecode: scene.timecode ?? '',
                removed: scene.removed ?? false,
                scene_index: index
            }))

            // Определяем базовое имя файла для заголовка
            const fileName = originalFileName || analysisData?.document || `scenario_${docId || Date.now()}`
            const baseName = fileName.replace(/\.(docx|pdf|txt)$/i, '') || `scenario_${docId || Date.now()}`

            const { openScenarioView } = await import('../api/scenarioApi.js')
            await openScenarioView(docId, scriptScenesForView, {
                inline: true,
                save: true,
                showLines: false,
                useBlocks: false,
                uppercaseHeadings: false,
                title: baseName
            })
        } catch (error) {
            console.error('%c[ResultsPage] ❌ Ошибка при открытии просмотра сценария', 'color: #F44336; font-weight: bold', error)
            alert(`Ошибка при открытии сценария: ${error.message || 'Неизвестная ошибка'}`)
        }
    }, [docId, editedScenes, originalFileName, analysisData])


    const handleFragmentNavigate = useCallback((fragment) => {
        if (!fragment) return
        const targetSceneIndex = sceneIndexByNumber.get(fragment.sceneIndex)
        if (targetSceneIndex !== undefined) {
            setCurrentSceneIndex(targetSceneIndex)
        }
        setActiveFragmentId(fragment.id)
    }, [sceneIndexByNumber])

    const handleFragmentFocus = useCallback((fragmentId, sceneNumber) => {
        setActiveFragmentId(fragmentId)
        if (sceneNumber !== undefined) {
            const targetSceneIndex = sceneIndexByNumber.get(sceneNumber)
            if (targetSceneIndex !== undefined) {
                setCurrentSceneIndex(targetSceneIndex)
            }
        }
    }, [sceneIndexByNumber])

    const handleSceneSelect = useCallback((index) => {
        setCurrentSceneIndex(index)
        setActiveFragmentId(null)
    }, [])

    const handleFragmentMetadataUpdate = useCallback((fragmentId, updates) => {
        if (!fragmentId || !updates) return
        // Находим сцену фрагмента
        const fragment = resolvedFragments.find(f => f.id === fragmentId)
        const sceneNumber = fragment?.sceneIndex

        if (manualFragments.some(fragment => fragment.id === fragmentId)) {
            setManualFragments(prev => prev.map(fragment => fragment.id === fragmentId ? { ...fragment, ...updates } : fragment))
            if (sceneNumber) {
                setChangedScenes(prev => new Set([...prev, sceneNumber]))
            }
            return
        }

        setFragmentMetadataOverrides(prev => ({
            ...prev,
            [fragmentId]: {
                ...(prev[fragmentId] ?? {}),
                ...updates
            }
        }))
        if (sceneNumber) {
            setChangedScenes(prev => new Set([...prev, sceneNumber]))
        }
    }, [manualFragments, resolvedFragments])

    const handleFragmentRevert = useCallback(async (fragmentId) => {
        // Находим фрагмент
        const fragment = resolvedFragments.find(f => f.id === fragmentId)
        if (!fragment) {
            console.error('Fragment not found for revert', fragmentId)
            return
        }

        // Если нет docId, используем старое поведение (только скрываем локально)
        if (!docId) {
            const isManual = manualFragments.some(f => f.id === fragmentId)
            if (isManual) {
                setManualFragments(prev => prev.filter(f => f.id !== fragmentId))
            } else {
                setDismissedFragments(prev => prev.includes(fragmentId) ? prev : [...prev, fragmentId])
            }
            setEditedFragments(prev => {
                const updated = { ...prev }
                delete updated[fragmentId]
                return updated
            })
            setFragmentMetadataOverrides(prev => {
                const updated = { ...prev }
                delete updated[fragmentId]
                return updated
            })
            return
        }

        // Находим сцену с фрагментом
        const sceneNumber = fragment.sceneIndex
        const targetScene = editedScenes.find(scene => scene.sceneNumber === sceneNumber)
        if (!targetScene) {
            console.error('Scene not found for fragment', fragment)
            setDismissedFragments(prev => prev.includes(fragmentId) ? prev : [...prev, fragmentId])
            return
        }

        // Находим scene_index (0-based индекс сцены в массиве)
        const sceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === sceneNumber)
        if (sceneIndex === -1) {
            console.error('Cannot find scene index for sceneNumber', sceneNumber)
            setDismissedFragments(prev => prev.includes(fragmentId) ? prev : [...prev, fragmentId])
            return
        }

        console.log('%c[ResultsPage] 🗑️ Отмена нарушения', 'color: #FF9800; font-weight: bold', {
            docId,
            sceneIndex,
            sceneNumber,
            fragmentId,
            fragmentText: fragment.text
        })

        try {
            const { cancelViolation } = await import('../api/analysisApi.js')

            // Формируем payload для отмены нарушения
            const payload = {
                scene_index: sceneIndex, // 0-based индекс сцены в массиве
                sentence_index: fragment.sentenceIndex ?? null
            }

            if (payload.sentence_index === null || payload.sentence_index === undefined) {
                console.error('Cannot find sentence_index for fragment', fragment)
                alert('Не удалось определить предложение для отмены.')
                return
            }

            const result = await cancelViolation(docId, payload)

            // Бэкенд возвращает обновленный output.json
            if (result && (result.final_rating || result.problem_fragments || result.parents_guide)) {
                const { normaliseAnalysisFromRaw } = await import('../utils/mockApi')
                const existingId = analysisData?.id || null
                const normalised = normaliseAnalysisFromRaw(result, scriptScenes, existingId)

                setAnalysisData?.(prev => ({
                    ...normalised,
                    stageProgress: prev?.stageProgress ?? normalised.stageProgress,
                    stages: prev?.stages ?? normalised.stages
                }))

                console.log('%c[ResultsPage] ✅ Нарушение отменено на бэкенде', 'color: #4CAF50; font-weight: bold')
                // Помечаем сцену как измененную
                if (fragment?.sceneIndex) {
                    setChangedScenes(prev => new Set([...prev, fragment.sceneIndex]))
                }
            }

            // После успешной отмены на бэкенде, скрываем фрагмент локально
            const isManual = manualFragments.some(f => f.id === fragmentId)
            if (isManual) {
                setManualFragments(prev => prev.filter(f => f.id !== fragmentId))
            } else {
                setDismissedFragments(prev => prev.includes(fragmentId) ? prev : [...prev, fragmentId])
            }

            setEditedFragments(prev => {
                const updated = { ...prev }
                delete updated[fragmentId]
                return updated
            })

            setFragmentMetadataOverrides(prev => {
                if (!prev[fragmentId]) return prev
                const updated = { ...prev }
                delete updated[fragmentId]
                return updated
            })
        } catch (error) {
            console.error('%c[ResultsPage] ❌ Ошибка при отмене нарушения', 'color: #F44336; font-weight: bold', error)
            alert('Ошибка при отмене нарушения. Попробуйте снова.')
        }
    }, [docId, editedScenes, resolvedFragments, manualFragments, scriptScenes, analysisData, setAnalysisData])

    const handleManualFragmentCreate = useCallback(async (payload) => {
        if (!payload || !payload.labels?.length) return

        const sceneNumber = payload.sceneIndex
        const sceneHeading = payload.sceneHeading ?? editedScenes.find(scene => scene.sceneNumber === sceneNumber)?.heading ?? ''

        // Если есть docId, отправляем на бэкенд
        if (docId && payload.sentenceIndex !== null && payload.sentenceIndex !== undefined) {
            const sceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === sceneNumber)
            if (sceneIndex === -1) {
                console.error('Cannot find scene index for sceneNumber', sceneNumber)
                // Fallback на локальное создание
            } else {
                try {
                    const { addViolation } = await import('../api/analysisApi.js')

                    // Преобразуем labels в формат бэкенда
                    const backendLabels = payload.labels.map(label => ({
                        label: label,
                        local_severity: payload.severity ?? 'Mild',
                        reason: payload.evidenceSpans?.[label]?.reason ?? 'Авто: требуется сверка с текстом.',
                        advice: payload.evidenceSpans?.[label]?.advice ?? 'Смягчить при необходимости.'
                    }))

                    const result = await addViolation(docId, {
                        scene_index: sceneIndex,
                        sentence_index: payload.sentenceIndex,
                        text: payload.text,
                        fragment_severity: payload.severity ?? 'Moderate',
                        labels: backendLabels
                    })

                    // Бэкенд возвращает обновленный output.json
                    if (result && (result.final_rating || result.problem_fragments || result.parents_guide)) {
                        const { normaliseAnalysisFromRaw } = await import('../utils/mockApi.js')
                        const existingId = analysisData?.id || null
                        const normalised = normaliseAnalysisFromRaw(result, scriptScenes, existingId)

                        setAnalysisData?.(prev => ({
                            ...normalised,
                            stageProgress: prev?.stageProgress ?? normalised.stageProgress,
                            stages: prev?.stages ?? normalised.stages
                        }))

                        console.log('%c[ResultsPage] ✅ Нарушение добавлено на бэкенде', 'color: #4CAF50; font-weight: bold')
                        // Помечаем сцену как измененную
                        if (sceneNumber) {
                            setChangedScenes(prev => new Set([...prev, sceneNumber]))
                        }
                        return // Не создаем локальный фрагмент, так как он уже в ответе бэкенда
                    }
                } catch (error) {
                    console.error('%c[ResultsPage] ❌ Ошибка при добавлении нарушения', 'color: #F44336; font-weight: bold', error)
                    // Fallback на локальное создание
                }
            }
        }

        // Локальное создание (fallback или если нет docId)
        const currentFragments = [
            ...(analysisData?.evidence ?? []),
            ...manualFragments
        ]
        const occurrence = currentFragments.filter(fragment =>
            fragment.sceneIndex === sceneNumber &&
            ((fragment.originalText ?? fragment.text) === payload.text)
        ).length

        const id = payload.id ?? `manual_${sceneNumber}_${Date.now()}`
        const confidence = payload.confidence ?? Object.fromEntries(
            payload.labels.map(label => [label, 0.86])
        )
        const evidenceSpans = payload.evidenceSpans ?? Object.fromEntries(
            payload.labels.map(label => [label, getLabelDetails(label, payload.severity ?? 'Mild')])
        )

        const newFragment = {
            id,
            reason: detectReasonFromLabels(payload.labels) ?? 'other',
            text: payload.text,
            originalText: payload.originalText ?? payload.text,
            sceneHeading,
            sceneIndex: sceneNumber,
            sentenceIndex: payload.sentenceIndex ?? null,
            sceneFragmentIndex: occurrence,
            severity: payload.severity ?? 'Mild',
            labels: payload.labels,
            confidence,
            evidenceSpans,
            recommendations: payload.recommendations ?? []
        }

        setManualFragments(prev => [...prev, newFragment])
        setActiveFragmentId(id)
        const targetSceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === sceneNumber)
        if (targetSceneIndex !== -1) {
            setCurrentSceneIndex(targetSceneIndex)
        }
        // Помечаем сцену как измененную
        if (sceneNumber) {
            setChangedScenes(prev => new Set([...prev, sceneNumber]))
        }
    }, [analysisData, manualFragments, editedScenes, docId, scriptScenes, setAnalysisData])

    const handleViolationMetadataSave = useCallback(async (payload) => {
        if (!payload) return
        const { id, mode } = payload

        // Если есть docId и это редактирование существующего фрагмента, отправляем на бэкенд
        if (docId && mode === 'edit' && id) {
            const fragment = resolvedFragments.find(f => f.id === id)
            if (fragment && fragment.sentenceIndex !== null && fragment.sentenceIndex !== undefined) {
                const sceneIndex = editedScenes.findIndex(scene => scene.sceneNumber === fragment.sceneIndex)
                if (sceneIndex !== -1) {
                    try {
                        const { updateViolation } = await import('../api/analysisApi')

                        // Преобразуем labels в формат бэкенда
                        const backendLabels = (payload.labels || []).map(label => ({
                            label: label,
                            local_severity: payload.severity ?? 'Moderate',
                            reason: payload.evidenceSpans?.[label]?.reason ?? 'Авто: требуется сверка с текстом.',
                            advice: payload.evidenceSpans?.[label]?.advice ?? 'Смягчить при необходимости.'
                        }))

                        const result = await updateViolation(docId, {
                            scene_index: sceneIndex,
                            sentence_index: fragment.sentenceIndex,
                            text: fragment.text ?? payload.text ?? '',
                            fragment_severity: payload.severity ?? 'Moderate',
                            labels: backendLabels
                        })

                        // Бэкенд возвращает обновленный output.json
                        if (result && (result.final_rating || result.problem_fragments || result.parents_guide)) {
                            const { normaliseAnalysisFromRaw } = await import('../utils/mockApi.js')
                            const existingId = analysisData?.id || null
                            const normalised = normaliseAnalysisFromRaw(result, scriptScenes, existingId)

                            setAnalysisData?.(prev => ({
                                ...normalised,
                                stageProgress: prev?.stageProgress ?? normalised.stageProgress,
                                stages: prev?.stages ?? normalised.stages
                            }))

                            console.log('%c[ResultsPage] ✅ Нарушение обновлено на бэкенде', 'color: #4CAF50; font-weight: bold')
                            // Помечаем сцену как измененную
                            if (fragment?.sceneIndex) {
                                setChangedScenes(prev => new Set([...prev, fragment.sceneIndex]))
                            }
                            setViolationModalState({ isOpen: false, mode: 'add', fragment: null, initialData: null })
                            return
                        }
                    } catch (error) {
                        console.error('%c[ResultsPage] ❌ Ошибка при обновлении нарушения', 'color: #F44336; font-weight: bold', error)
                        // Fallback на локальное обновление
                    }
                }
            }
        }

        // Локальное обновление (fallback или если нет docId)
        const evidenceSpans = payload.evidenceSpans ?? Object.fromEntries(
            (payload.labels || []).map(label => [label, getLabelDetails(label, payload.severity)])
        )
        const confidence = payload.confidence ?? Object.fromEntries(
            (payload.labels || []).map(label => [label, 0.86])
        )

        const updates = {
            labels: payload.labels,
            severity: payload.severity,
            evidenceSpans,
            recommendations: payload.recommendations ?? [],
            confidence
        }

        if (mode === 'add') {
            handleManualFragmentCreate(payload)
        } else if (id) {
            handleFragmentMetadataUpdate(id, updates)
        }

        setViolationModalState({ isOpen: false, mode: 'add', fragment: null, initialData: null })
    }, [handleManualFragmentCreate, handleFragmentMetadataUpdate, docId, editedScenes, resolvedFragments, scriptScenes, analysisData, setAnalysisData])

    const openAddViolationModal = useCallback((initialData = null) => {
        setViolationModalState({ isOpen: true, mode: 'add', fragment: null, initialData })
    }, [])

    const openEditViolationModal = useCallback((fragment) => {
        setViolationModalState({ isOpen: true, mode: 'edit', fragment, initialData: null })
    }, [])

    const closeViolationModal = useCallback(() => {
        setViolationModalState({ isOpen: false, mode: 'add', fragment: null, initialData: null })
    }, [])

    const historyToggleButton = useMemo(() => (
        <button
            onClick={() => setIsPanelOpen(true)}
            className="w-[40px] h-[40px] flex items-center justify-center hover:opacity-80 transition-opacity"
            aria-label="Показать панель аналитики"
        >
            <HistoryIcon isOrange={false} className="w-[40px] h-[40px]" />
        </button>
    ), [])

    useEffect(() => {
        if (!configureHeader) return

        if (isPanelOpen) {
            configureHeader()
        } else {
            configureHeader({
                showLogo: false,
                leftExtras: historyToggleButton,
                leftOrientation: 'column'
            })
        }

        return () => {
            configureHeader()
        }
    }, [isPanelOpen, configureHeader, historyToggleButton])

    const totalScenes = editedScenes.length
    const safeSceneIndex = totalScenes === 0 ? 0 : Math.min(currentSceneIndex, totalScenes - 1)
    const paginationItems = useMemo(() => buildPaginationItems(totalScenes, safeSceneIndex + 1), [totalScenes, safeSceneIndex])

    useEffect(() => {
        if (typeof window === 'undefined') return undefined
        const handleWindowResize = () => {
            setViewportWidth(window.innerWidth || 1440)
        }
        window.addEventListener('resize', handleWindowResize)
        return () => window.removeEventListener('resize', handleWindowResize)
    }, [])

    const showTopPagination = totalScenes > 0 && (!isPanelExpanded || viewportWidth >= 1700)
    const useArrowLabels = isPanelExpanded && viewportWidth < 1700

    const computeExpandedWidth = useCallback(() => {
        if (typeof window === 'undefined') {
            return Math.max(720, DEFAULT_PANEL_WIDTH)
        }
        return Math.max(DEFAULT_PANEL_WIDTH, Math.min(window.innerWidth - 140, 1000))
    }, [])

    useEffect(() => {
        if (isPanelExpanded) {
            setPanelWidth(computeExpandedWidth())
        } else {
            setPanelWidth(DEFAULT_PANEL_WIDTH)
        }
    }, [isPanelExpanded, computeExpandedWidth])

    useEffect(() => {
        if (!isPanelExpanded) return
        const handleResize = () => {
            setPanelWidth(computeExpandedWidth())
        }
        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    }, [isPanelExpanded, computeExpandedWidth])

    const handlePanelExpandToggle = useCallback(() => {
        setIsPanelExpanded(prev => !prev)
    }, [])

    const scriptContainerStyle = {
        marginLeft: isPanelOpen ? panelWidth + 50 : 100,
        marginRight: isPanelOpen ? 50 : 100,
        marginTop: 25,
        marginBottom: 25,
        height: 'calc(100vh - 50px)',
        display: 'flex',
        flexDirection: 'column',
        transition: 'margin 0.3s ease'
    }

    const handlePanelWidthChange = useCallback((nextWidth, options = {}) => {
        setPanelWidth(nextWidth)
        if (options.expand !== undefined) {
            setIsPanelExpanded(options.expand)
            return
        }
        setIsPanelExpanded(nextWidth > DEFAULT_PANEL_WIDTH + 30)
    }, [])

    const handlePanelToggleExpand = useCallback(() => {
        const viewportWidth = window.innerWidth || 1440
        if (isPanelExpanded) {
            handlePanelWidthChange(DEFAULT_PANEL_WIDTH, { expand: false })
            return
        }

        const targetWidth = Math.min(viewportWidth - 120, 900)
        handlePanelWidthChange(Math.max(DEFAULT_PANEL_WIDTH, targetWidth), { expand: true })
    }, [handlePanelWidthChange, isPanelExpanded])

    return (
        <>
            <div
                className="relative min-h-screen text-white overflow-hidden"
                style={{
                    backgroundImage: `url(${photoBackImg})`,
                    backgroundSize: 'cover',
                    backgroundPosition: 'center',
                    backgroundRepeat: 'no-repeat'
                }}
            >
                {isPanelOpen && (
                    <AnalysisPanel
                        analysisData={analysisWithResolved}
                        activeFragmentId={activeFragmentId}
                        onClose={() => setIsPanelOpen(false)}
                        panelWidth={panelWidth}
                        onPanelWidthChange={handlePanelWidthChange}
                        onTogglePanelExpand={handlePanelToggleExpand}
                        isPanelExpanded={isPanelExpanded}
                        onFragmentEdit={handleFragmentEdit}
                        onFragmentReplace={handleFragmentReplace}
                        onFragmentNavigate={handleFragmentNavigate}
                        onFragmentFocus={handleFragmentFocus}
                        onFragmentRevert={handleFragmentRevert}
                        onManageViolation={openEditViolationModal}
                        onAddViolation={openAddViolationModal}
                        stages={analysisData?.stages}
                        stageProgress={analysisData?.stageProgress}
                        reasonLabels={REASON_LABELS}
                        onReanalyze={handleReanalyze}
                        onRecalculate={handleReanalyze}
                        onExportReport={handleExportReport}
                        canExportReport={!hasPendingChanges}
                    />
                )}

                <div className="relative" style={scriptContainerStyle}>
                    <div className="relative h-full">
                        <div className="absolute top-0 left-0 right-0">
                            <div className="bg-white/70 text-gray-900 rounded-[25px] h-[60px] px-[40px] flex items-center justify-between gap-6 shadow-[0px_12px_30px_rgба(22,22,22,0.35)] font-unbounded font-bold text-[20px] tracking-[0.02em] w-full">
                                <div className="flex items-center gap-3">
                                    <span>Текст сценария</span>
                                    <button
                                        type="button"
                                        onClick={handleDownloadScript}
                                        className="h-10 px-4 rounded-[12px] bg-wink-orange text-white flex items-center gap-2 justify-center shadow-[0px_12px_24px_rgba(254,148,46,0.35)] hover:bg-wink-orange-light transition-colors"
                                        aria-label="Показать сценарий"
                                    >
                                        <UploadIcon className="w-5 h-5" />
                                        <span className="text-[12px] font-unbounded uppercase tracking-[0.08em]">Показать</span>
                                    </button>
                                </div>
                                {showTopPagination && (
                                    <div className="flex items-center gap-2 flex-wrap justify-end">
                                        {paginationItems.map((item, index) => {
                                            if (item.type === 'ellipsis') {
                                                return (
                                                    <span key={`ellipsis-${item.id ?? index}`} className="text-gray-500 font-poppins text-[14px] px-1">
                                                        …
                                                    </span>
                                                )
                                            }

                                            const isActive = item.value === safeSceneIndex + 1
                                            return (
                                                <button
                                                    key={`page-${item.value}`}
                                                    onClick={() => handleSceneSelect(item.value - 1)}
                                                    className={`w-9 h-9 rounded-full flex items-center justify-center text-[15px] font-poppins font-semibold border transition-colors ${isActive ? 'bg-wink-orange text-white border-transparent shadow-[0px_8px_18px_rgba(254,148,46,0.35)]' : 'bg-white/30 text-gray-800 border-white/60 hover:bg-white/50'}`}
                                                    aria-label={`Перейти к сцене ${item.value}`}
                                                >
                                                    {item.value}
                                                </button>
                                            )
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="bg-white/55 text-gray-900 rounded-[24px] pt-[85px] pb-[45px] px-[40px] shadow-[0px_30px_80px_rgba(12,12,12,0.35)] w-full h-full overflow-hidden">
                            <ScriptEditor
                                scenes={editedScenes}
                                currentSceneIndex={safeSceneIndex}
                                onSceneSelect={handleSceneSelect}
                                onSceneChange={handleSceneChange}
                                onSceneRecalculate={handleSceneRecalculate}
                                onSelectionAddViolation={(payload) => openAddViolationModal(payload)}
                                fragments={resolvedFragments}
                                activeFragmentId={activeFragmentId}
                                onFragmentFocus={handleFragmentFocus}
                                useArrowLabels={useArrowLabels}
                            />
                        </div>
                    </div>
                </div>
            </div>

            <ViolationEditorModal
                isOpen={violationModalState.isOpen}
                mode={violationModalState.mode}
                fragment={violationModalState.fragment}
                initialData={violationModalState.initialData}
                scenes={editedScenes}
                availableLabels={AVAILABLE_LABELS}
                onClose={closeViolationModal}
                onSubmit={handleViolationMetadataSave}
            />
        </>
    )
}

export default ResultsPage
