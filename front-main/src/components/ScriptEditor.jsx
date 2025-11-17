import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const CARET_STYLE_PROPERTIES = [
    'direction',
    'boxSizing',
    'width',
    'height',
    'overflowX',
    'overflowY',
    'borderTopWidth',
    'borderRightWidth',
    'borderBottomWidth',
    'borderLeftWidth',
    'paddingTop',
    'paddingRight',
    'paddingBottom',
    'paddingLeft',
    'fontFamily',
    'fontSize',
    'fontWeight',
    'fontStyle',
    'letterSpacing',
    'textTransform',
    'textAlign',
    'textIndent',
    'lineHeight',
    'wordSpacing',
    'tabSize'
]

const getTextareaCaretCoordinates = (textarea, position) => {
    if (!textarea) return null
    const computed = window.getComputedStyle(textarea)
    const mirror = document.createElement('div')

    CARET_STYLE_PROPERTIES.forEach(prop => {
        mirror.style[prop] = computed[prop]
    })

    mirror.style.position = 'absolute'
    mirror.style.visibility = 'hidden'
    mirror.style.whiteSpace = 'pre-wrap'
    mirror.style.wordWrap = 'break-word'
    mirror.style.top = '0'
    mirror.style.left = '0'
    mirror.style.width = `${textarea.clientWidth}px`
    mirror.style.overflow = 'visible'

    const textBefore = textarea.value.substring(0, position)
    const textAfter = textarea.value.substring(position) || '.'

    mirror.textContent = textBefore
    const span = document.createElement('span')
    span.textContent = textAfter
    mirror.appendChild(span)

    document.body.appendChild(mirror)
    const spanRect = span.getBoundingClientRect()
    const mirrorRect = mirror.getBoundingClientRect()

    const caretTop = spanRect.top - mirrorRect.top
    const caretLeft = spanRect.left - mirrorRect.left

    document.body.removeChild(mirror)

    return {
        top: caretTop,
        left: caretLeft
    }
}

const reasonColors = {
    violence: 'rgba(254, 148, 46, 0.35)',
    profanity: 'rgba(255, 194, 135, 0.35)',
    alcohol: 'rgba(161, 120, 223, 0.35)',
    scary: 'rgba(108, 180, 238, 0.35)',
    erotic: 'rgba(245, 142, 209, 0.35)'
}

const escapeHtml = (text = '') =>
    text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')

const escapeRegExp = (text = '') => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const computeHighlightRanges = (text, fragments) => {
    if (!text) return []
    const ranges = []

    fragments.forEach(fragment => {
        const needle = fragment?.text
        if (!needle) return

        const regex = new RegExp(escapeRegExp(needle), 'g')
        let match
        while ((match = regex.exec(text)) !== null) {
            const start = match.index
            const end = start + needle.length

            if (ranges.some(range => start < range.end && end > range.start)) {
                continue
            }

            ranges.push({ start, end, fragment })
            break
        }
    })

    return ranges.sort((a, b) => a.start - b.start)
}

const renderHighlightedHtml = (text, ranges, activeFragmentId) => {
    if (!text) return ''

    let cursor = 0
    let html = ''

    ranges.forEach(({ start, end, fragment }) => {
        if (cursor < start) {
            html += escapeHtml(text.slice(cursor, start))
        }

        const color = reasonColors[fragment.reason] || reasonColors.violence
        const isActive = fragment.id === activeFragmentId
        const highlighted = escapeHtml(text.slice(start, end))

        html += `<span class="highlight-fragment${isActive ? ' highlight-active' : ''}" data-fragment-id="${fragment.id}" style="background:${color};color:#1F1F1F;">${highlighted}</span>`
        cursor = end
    })

    if (cursor < text.length) {
        html += escapeHtml(text.slice(cursor))
    }

    return html.replace(/\n/g, '<br/>')
}

const ScriptEditor = ({
    scenes = [],
    currentSceneIndex = 0,
    onSceneSelect,
    onSceneChange,
    onSceneRecalculate,
    onSelectionAddViolation,
    fragments = [],
    activeFragmentId,
    onFragmentFocus,
    useArrowLabels = false
}) => {
    const textareaRef = useRef(null)
    const overlayRef = useRef(null)
    const editorContainerRef = useRef(null)
    const selectionButtonRef = useRef(null)

    const totalScenes = scenes.length
    const currentScene = scenes[currentSceneIndex] ?? null

    const currentContent = useMemo(() => {
        if (!currentScene) return ''
        const raw = currentScene.content
        if (Array.isArray(raw)) {
            return raw.join('\n\n')
        }
        return raw ?? ''
    }, [currentScene])

    const [localText, setLocalText] = useState(currentContent)

    const [selectionPrompt, setSelectionPrompt] = useState({
        visible: false,
        text: '',
        sceneNumber: null,
        position: { top: 0, left: 0 },
        range: { start: 0, end: 0 }
    })

    useEffect(() => {
        setLocalText(currentContent)
    }, [currentContent, currentSceneIndex])

    const fragmentsForScene = useMemo(() => {
        if (!currentScene) return []
        return fragments.filter(fragment => fragment.sceneIndex === currentScene.sceneNumber)
    }, [fragments, currentScene])

    const highlightRanges = useMemo(
        () => computeHighlightRanges(localText, fragmentsForScene),
        [localText, fragmentsForScene]
    )

    const highlightedHtml = useMemo(
        () => renderHighlightedHtml(localText, highlightRanges, activeFragmentId),
        [localText, highlightRanges, activeFragmentId]
    )

    const syncScroll = () => {
        if (overlayRef.current && textareaRef.current) {
            overlayRef.current.scrollTop = textareaRef.current.scrollTop
        }
    }

    const handleTextChange = (event) => {
        const value = event.target.value
        setLocalText(value)
        if (currentScene) {
            onSceneChange?.(currentScene.sceneNumber, value)
        }
    }

    const handleCaretChange = () => {
        if (!textareaRef.current || !currentScene) return
        const cursorPos = textareaRef.current.selectionStart
        const range = highlightRanges.find(item => cursorPos >= item.start && cursorPos <= item.end)
        if (range) {
            onFragmentFocus?.(range.fragment.id, currentScene.sceneNumber)
        }
    }

    const hideSelectionPrompt = useCallback(() => {
        setSelectionPrompt({
            visible: false,
            text: '',
            sceneNumber: null,
            position: { top: 0, left: 0 },
            range: { start: 0, end: 0 }
        })
    }, [])

    const handleSelectionCheck = useCallback(() => {
        if (!textareaRef.current || !editorContainerRef.current || !currentScene || typeof onSelectionAddViolation !== 'function') {
            hideSelectionPrompt()
            return
        }

        const textarea = textareaRef.current
        const container = editorContainerRef.current
        const { selectionStart, selectionEnd } = textarea

        if (selectionStart === selectionEnd) {
            hideSelectionPrompt()
            return
        }

        const selectedText = textarea.value.slice(selectionStart, selectionEnd).trim()
        if (!selectedText) {
            hideSelectionPrompt()
            return
        }

        const caret = getTextareaCaretCoordinates(textarea, selectionEnd)
        if (!caret) {
            hideSelectionPrompt()
            return
        }

        const textareaRect = textarea.getBoundingClientRect()
        const containerRect = container.getBoundingClientRect()

        let top = textareaRect.top - containerRect.top + caret.top - textarea.scrollTop - 36
        let left = textareaRect.left - containerRect.left + caret.left - textarea.scrollLeft

        const maxLeft = container.clientWidth - 160
        const maxTop = container.clientHeight - 64
        top = Math.max(8, Math.min(maxTop, top))
        left = Math.max(8, Math.min(maxLeft, left))

        setSelectionPrompt({
            visible: true,
            text: selectedText,
            sceneNumber: currentScene.sceneNumber,
            position: { top, left },
            range: { start: selectionStart, end: selectionEnd }
        })
    }, [currentScene, hideSelectionPrompt, onSelectionAddViolation])

    const handleSelectionAdd = useCallback(() => {
        if (!selectionPrompt.visible || !selectionPrompt.text) return
        onSelectionAddViolation?.({
            sceneNumber: selectionPrompt.sceneNumber,
            text: selectionPrompt.text,
            range: selectionPrompt.range
        })
        hideSelectionPrompt()
        if (textareaRef.current) {
            const pos = textareaRef.current.selectionEnd
            textareaRef.current.selectionStart = pos
            textareaRef.current.selectionEnd = pos
            textareaRef.current.focus()
        }
    }, [hideSelectionPrompt, onSelectionAddViolation, selectionPrompt])

    const handlePrevScene = () => {
        if (typeof onSceneSelect !== 'function' || currentSceneIndex <= 0) return
        onSceneSelect(currentSceneIndex - 1)
    }

    const handleNextScene = () => {
        if (typeof onSceneSelect !== 'function' || currentSceneIndex >= totalScenes - 1) return
        onSceneSelect(currentSceneIndex + 1)
    }

    useEffect(() => {
        const textarea = textareaRef.current
        if (!textarea) return
        textarea.style.height = '100%'
        textarea.style.width = '100%'
    }, [])

    useEffect(() => {
        if (!overlayRef.current || !textareaRef.current || !activeFragmentId) return
        const node = overlayRef.current.querySelector(`[data-fragment-id="${activeFragmentId}"]`)
        if (!node) return
        const offset = node.offsetTop - overlayRef.current.clientHeight / 2
        const target = Math.max(0, offset)
        overlayRef.current.scrollTo({ top: target, behavior: 'smooth' })
        textareaRef.current.scrollTop = target
    }, [activeFragmentId, currentSceneIndex, highlightedHtml])

    useEffect(() => {
        const textarea = textareaRef.current
        if (!textarea) return
        const handleMouseUp = () => {
            handleSelectionCheck()
        }
        const handleKeyUp = () => {
            handleSelectionCheck()
        }
        const handleScroll = () => {
            hideSelectionPrompt()
        }
        textarea.addEventListener('mouseup', handleMouseUp)
        textarea.addEventListener('keyup', handleKeyUp)
        textarea.addEventListener('scroll', handleScroll)
        return () => {
            textarea.removeEventListener('mouseup', handleMouseUp)
            textarea.removeEventListener('keyup', handleKeyUp)
            textarea.removeEventListener('scroll', handleScroll)
        }
    }, [currentSceneIndex, currentScene, handleSelectionCheck, hideSelectionPrompt])

    useEffect(() => {
        hideSelectionPrompt()
    }, [currentSceneIndex, hideSelectionPrompt])

    useEffect(() => {
        if (!selectionPrompt.visible) return
        const handleDocumentClick = (event) => {
            if (selectionButtonRef.current?.contains(event.target)) return
            if (textareaRef.current?.contains(event.target)) return
            hideSelectionPrompt()
        }
        document.addEventListener('mousedown', handleDocumentClick)
        return () => document.removeEventListener('mousedown', handleDocumentClick)
    }, [selectionPrompt.visible, hideSelectionPrompt])

    if (!currentScene) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <div className="rounded-[18px] bg-white/40 text-gray-600 p-10 min-h-[240px] flex items-center justify-center">
                    <p className="font-poppins text-[16px] text-center">
                        Сцены сценария не найдены. Загрузите текст, чтобы продолжить работу.
                    </p>
                </div>
            </div>
        )
    }

    const sceneLabel = currentScene.sceneNumber ?? currentSceneIndex + 1
    const pageLabel = currentScene.page ?? sceneLabel
    const heading = currentScene.heading ?? `Сцена ${sceneLabel}`
    const prevDisabled = typeof onSceneSelect !== 'function' || currentSceneIndex <= 0
    const nextDisabled = typeof onSceneSelect !== 'function' || currentSceneIndex >= totalScenes - 1

    return (
        <div className="w-full h-full flex flex-col">
            <div className="rounded-[18px] p-0 overflow-hidden flex-1 flex flex-col">
                <div className="px-[20px] pt-[6px]">
                    <div className="flex items-start justify-between mb-6 mt-2">
                        <div className="flex items-center gap-4">
                            <p className="text-gray-900 font-unbounded font-semibold text-[18px] leading-tight">
                                {heading}
                            </p>
                            {typeof onSceneRecalculate === 'function' && (
                                <button
                                    onClick={() => onSceneRecalculate(currentScene.sceneNumber)}
                                    className="px-3 py-1.5 rounded-[10px] bg-wink-orange text-white text-[12px] font-poppins font-medium shadow-[0px_8px_18px_rgba(254,148,46,0.3)] hover:bg-wink-orange-light transition-colors"
                                >
                                    Перерасчитать сцену
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                <div className="relative flex-1 min-h-0" ref={editorContainerRef}>
                    <div
                        ref={overlayRef}
                        className="absolute inset-0 whitespace-pre-wrap text-gray-900 leading-relaxed overflow-y-auto pointer-events-none ScrollbarHide px-[20px] py-[20px] text-[20px] font-poppins"
                        dangerouslySetInnerHTML={{ __html: highlightedHtml }}
                    />
                    <textarea
                        ref={textareaRef}
                        value={localText}
                        onChange={handleTextChange}
                        onScroll={syncScroll}
                        onClick={handleCaretChange}
                        onKeyUp={handleCaretChange}
                        className="absolute inset-0 px-[20px] py-[20px] bg-transparent text-transparent caret-white leading-relaxed focus:outline-none resize-none selection:bg-wink-orange/30 ScrollbarHide text-[20px] font-poppins"
                        spellCheck={false}
                    />
                    {selectionPrompt.visible && (
                        <button
                            ref={selectionButtonRef}
                            type="button"
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={handleSelectionAdd}
                            className="absolute z-20 px-3 py-1.5 rounded-[10px] bg-wink-orange text-white text-[11px] font-unbounded tracking-[0.08em] uppercase shadow-[0px_8px_18px_rgba(0,0,0,0.3)] hover:bg-wink-orange-light transition-colors"
                            style={{ top: selectionPrompt.position.top, left: selectionPrompt.position.left }}
                        >
                            Добавить нарушение
                        </button>
                    )}
                </div>

                <div className="px-[20px] mt-6 mb-4 flex items-center justify-between text-gray-700">
                    <button
                        onClick={handlePrevScene}
                        disabled={prevDisabled}
                        className={`px-5 py-2 rounded-[12px] font-unbounded text-[14px] transition-colors ${prevDisabled ? 'bg-white/30 text-gray-400 border border-transparent cursor-not-allowed' : 'bg-white/80 text-wink-orange border border-wink-orange shadow-sm hover:bg-white/95'}`}
                    >
                        {useArrowLabels ? '←' : '← Предыдущая'}
                    </button>
                    <span className="text-[16px] font-unbounded font-semibold text-white">
                        Страница {pageLabel}
                    </span>
                    <button
                        onClick={handleNextScene}
                        disabled={nextDisabled}
                        className={`px-5 py-2 rounded-[12px] font-unbounded text-[14px] transition-colors ${nextDisabled ? 'bg-white/30 text-gray-400 border border-transparent cursor-not-allowed' : 'bg-wink-orange text-white border border-wink-orange shadow-[0px_8px_18px_rgba(254,148,46,0.35)] hover:bg-wink-orange-light'}`}
                    >
                        {useArrowLabels ? '→' : 'Следующая →'}
                    </button>
                </div>
            </div>
        </div>
    )
}

export default ScriptEditor
