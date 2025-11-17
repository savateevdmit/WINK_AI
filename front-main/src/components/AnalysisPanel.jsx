import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import CategoryScore from './CategoryScore'
import ProblematicFragment from './ProblematicFragment'
import { HistoryIcon, ConfidenceMarkIcon } from '../utils/icons'
import { formatMarkdown } from '../utils/markdownFormatter'

const DEFAULT_VISIBLE = 5

const STAGE_ORDER = ['stage1', 'stage2', 'stage3']

const STAGE_DEFAULTS = {
    stage1: { label: 'Stage 1', description: 'Первичная классификация' },
    stage2: { label: 'Stage 2', description: 'Обогащение метаданными' },
    stage3: { label: 'Stage 3', description: 'Финальная интерпретация' }
}

const TAB_CONFIG = [
    { id: 'analytics', label: 'Аналитика', requiresDetails: false },
    { id: 'categories', label: 'Категории', requiresDetails: false },
    { id: 'details', label: 'Обоснования', requiresDetails: true }
]

const StageProgress = ({ stages = [], stageProgress = {} }) => {
    const ordered = STAGE_ORDER.map(id => {
        const fromStages = stages?.find?.(stage => stage?.id === id)
        const defaults = STAGE_DEFAULTS[id]
        return {
            id,
            label: fromStages?.label ?? defaults?.label ?? id,
            description: fromStages?.description ?? defaults?.description ?? '',
            progress: fromStages?.progress ?? stageProgress?.[id] ?? 0,
            status: fromStages?.status ?? (stageProgress?.[id] === 100 ? 'completed' : 'pending')
        }
    })

    return (
        <div className="bg-white/10 rounded-[14px] px-5 py-4 space-y-3">
            <div className="flex items-center justify-between">
                <h3 className="text-white/80 font-unbounded text-[14px] uppercase tracking-[0.08em]">
                    Прогресс анализа
                </h3>
            </div>
            <div className="flex gap-3">
                {ordered.map(stage => {
                    const isCompleted = stage.status === 'completed' || stage.progress === 100
                    const isActive = !isCompleted && stage.progress > 0
                    return (
                        <div key={stage.id} className="flex-1 flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-white font-poppins text-[12px] font-semibold">
                                    {stage.label}
                                </span>
                                <span className={`text-[12px] font-poppins ${isCompleted ? 'text-green-300' : isActive ? 'text-wink-orange-light' : 'text-white/50'}`}>
                                    {Math.round(stage.progress)}%
                                </span>
                            </div>
                            <div className="h-2 bg-white/15 rounded-full overflow-hidden">
                                <div
                                    className={`${isCompleted ? 'bg-green-400' : isActive ? 'bg-wink-orange' : 'bg-white/30'} h-full transition-all duration-500`}
                                    style={{ width: `${Math.min(100, Math.max(0, stage.progress))}%` }}
                                />
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

const MIN_PANEL_WIDTH = 520
const MAX_PANEL_WIDTH = Number.POSITIVE_INFINITY

const AnalysisPanel = ({
    analysisData,
    onClose,
    onFragmentEdit,
    onFragmentReplace,
    onFragmentNavigate,
    onFragmentFocus,
    onFragmentRevert,
    onManageViolation,
    onAddViolation,
    onReanalyze,
    onRecalculate,
    onExportReport,
    canExportReport = true,
    activeFragmentId,
    stages,
    stageProgress,
    reasonLabels = {},
    panelWidth = 520,
    onPanelWidthChange,
    onTogglePanelExpand,
    isPanelExpanded
}) => {
    const [expandedCategories, setExpandedCategories] = useState({})
    const [visibleCounts, setVisibleCounts] = useState({})
    const [activeTab, setActiveTab] = useState('analytics')
    const [expandedDetails, setExpandedDetails] = useState({})
    const [exportTooltipVisible, setExportTooltipVisible] = useState(false)
    const [scrollTicket, setScrollTicket] = useState(0)

    const reasons = analysisData?.reasons ?? []

    const filteredEvidence = useMemo(() => analysisData?.evidence ?? [], [analysisData])

    const evidenceByReason = useMemo(() => {
        const map = {}
        filteredEvidence.forEach(fragment => {
            if (!map[fragment.reason]) {
                map[fragment.reason] = []
            }
            map[fragment.reason].push(fragment)
        })
        return map
    }, [filteredEvidence])

    const reasonsWithEvidence = useMemo(() => {
        return reasons.filter(reason => (evidenceByReason[reason.code]?.length ?? 0) > 0)
    }, [reasons, evidenceByReason])

    const detailUnlocked = useMemo(() => {
        const stage3 = stages?.find?.(stage => stage?.id === 'stage3')
        if (stage3) {
            return stage3.status === 'completed' || (stage3.progress ?? 0) >= 100
        }
        if (stageProgress?.stage3 !== undefined) {
            return stageProgress.stage3 >= 100
        }
        return false
    }, [stages, stageProgress])

    useEffect(() => {
        if (!detailUnlocked && activeTab === 'details') {
            setActiveTab('analytics')
        }
    }, [detailUnlocked, activeTab])

    useEffect(() => {
        setExpandedDetails({})
    }, [activeTab, filteredEvidence])

    const requestScrollToFragment = useCallback((fragmentId) => {
        if (!fragmentId) return
        scrollTargetRef.current = fragmentId
        setScrollTicket(prev => prev + 1)
    }, [])

    useEffect(() => {
        if (!activeFragmentId) return
        requestScrollToFragment(activeFragmentId)
    }, [activeFragmentId, requestScrollToFragment])

    const exportDisabled = !canExportReport
    const handleExportClick = () => {
        if (exportDisabled) {
            setExportTooltipVisible(true)
            return
        }
        onExportReport?.()
    }

    useEffect(() => {
        if (!exportTooltipVisible) return
        const timer = setTimeout(() => setExportTooltipVisible(false), 2200)
        return () => clearTimeout(timer)
    }, [exportTooltipVisible])

    useEffect(() => {
        if (!scrollTicket) return
        const fragmentId = scrollTargetRef.current
        if (!fragmentId) return
        const frame = requestAnimationFrame(() => {
            const node = panelRef.current?.querySelector(`[data-panel-fragment="${fragmentId}"]`)
            if (node) {
                node.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }
            scrollTargetRef.current = null
        })
        return () => cancelAnimationFrame(frame)
    }, [scrollTicket])

    if (!analysisData) return null

    const getConfidenceColor = (confidence) => {
        if (confidence >= 0.8) return 'text-green-400'
        if (confidence >= 0.6) return 'text-yellow-400'
        return 'text-red-400'
    }

    const getRatingColor = (rating) => {
        const colors = {
            '0+': 'bg-green-500',
            '6+': 'bg-blue-500',
            '12+': 'bg-yellow-500',
            '16+': 'bg-wink-orange',
            '18+': 'bg-red-600'
        }
        return colors[rating] || 'bg-gray-500'
    }

    const toggleCategory = (code) => {
        setExpandedCategories(prev => ({
            ...prev,
            [code]: !prev[code]
        }))
        setVisibleCounts(prev => ({
            ...prev,
            [code]: DEFAULT_VISIBLE
        }))
    }

    const handleShowMore = (code) => {
        const count = evidenceByReason[code]?.length || 0
        setVisibleCounts(prev => ({ ...prev, [code]: count }))
    }

    const handleCollapse = (code) => {
        setVisibleCounts(prev => ({ ...prev, [code]: DEFAULT_VISIBLE }))
    }

    const handleTabChange = (tabId, fragmentId, sceneNumber) => {
        if (tabId === 'details' && !detailUnlocked) {
            return
        }
        setActiveTab(tabId)
        if (fragmentId) {
            onFragmentFocus?.(fragmentId, sceneNumber)
        }
    }

    const handleToggleDetails = (fragmentId, nextValue) => {
        setExpandedDetails(prev => ({
            ...prev,
            [fragmentId]: nextValue
        }))
    }

    const handleJumpToDetails = (fragment) => {
        if (!detailUnlocked || !fragment) return
        handleTabChange('details', fragment.id, fragment.sceneIndex)
        handleToggleDetails(fragment.id, true)
        requestScrollToFragment(fragment.id)
    }

    const handleJumpToCategories = (fragment) => {
        const reasonCode = fragment.reason
        if (!expandedCategories[reasonCode]) {
            setExpandedCategories(prev => ({ ...prev, [reasonCode]: true }))
        }
        handleTabChange('categories', fragment.id, fragment.sceneIndex)
        requestScrollToFragment(fragment.id)
    }

    const analyticsSummary = reasons

    const panelRef = useRef(null)
    const scrollTargetRef = useRef(null)
    const resizeStateRef = useRef(null)

    const handleResize = useCallback((event) => {
        if (!resizeStateRef.current) return
        const { startX, startWidth } = resizeStateRef.current
        const delta = event.clientX - startX
        const viewportWidth = window.innerWidth || 1440
        const manualMaxWidth = Math.max(MIN_PANEL_WIDTH, Math.min(viewportWidth / 2, viewportWidth - 120, MAX_PANEL_WIDTH))
        const nextWidth = Math.min(manualMaxWidth, Math.max(MIN_PANEL_WIDTH, startWidth + delta))
        onPanelWidthChange?.(nextWidth)
    }, [onPanelWidthChange])

    const stopResizeListeners = useCallback(() => {
        resizeStateRef.current = null
        document.removeEventListener('mousemove', handleResize)
        document.removeEventListener('mouseup', stopResizeListeners)
    }, [handleResize])

    const handleResizeStart = useCallback((event) => {
        event.preventDefault()
        resizeStateRef.current = {
            startX: event.clientX,
            startWidth: panelWidth
        }
        document.addEventListener('mousemove', handleResize)
        document.addEventListener('mouseup', stopResizeListeners)
    }, [handleResize, stopResizeListeners, panelWidth])

    useEffect(() => () => stopResizeListeners(), [stopResizeListeners])
    return (
        <aside
            ref={panelRef}
            className="fixed left-0 top-0 h-screen z-30 transition-transform duration-300"
            style={{ width: panelWidth, backgroundColor: 'rgba(122, 122, 122, 0.3)', backdropFilter: 'blur(50px)' }}
        >
            <div className="h-full flex flex-col px-[30px] pt-[25px] pb-[30px] overflow-hidden">
                <div className="flex justify-end flex-shrink-0 gap-3">
                    <button
                        onClick={onTogglePanelExpand}
                        className="w-[40px] h-[40px] flex items-center justify-center text-white/70 hover:text-white transition-colors"
                        aria-label={isPanelExpanded ? 'Свернуть панель' : 'Расширить панель'}
                    >
                        {isPanelExpanded ? '⤢' : '⤡'}
                    </button>
                    <button
                        onClick={onClose}
                        className="w-[40px] h-[40px] flex items-center justify-center hover:opacity-80 transition-opacity"
                        aria-label="Свернуть панель"
                    >
                        <HistoryIcon isOrange={false} className="w-[40px] h-[40px]" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto pr-1 mt-6 space-y-6 ScrollbarHide">
                    <div className="bg-white/10 rounded-[14px] w-full" style={{ minHeight: '120px' }}>
                        <div className="flex items-center px-6 py-6 gap-6">
                            <div className={`${getRatingColor(analysisData.age_label)} w-[65px] h-[65px] rounded-[18px] flex items-center justify-center shadow-[0px_12px_30px_rgba(0,0,0,0.35)]`}>
                                <span className="text-white font-unbounded font-bold text-[24px] leading-none">{analysisData.age_label}</span>
                            </div>
                            <div className="flex flex-col gap-2">
                                <p className="text-white font-unbounded font-bold text-[16px] leading-tight">
                                    Возрастной рейтинг
                                </p>
                                <div className="flex items-center gap-2 text-white font-unbounded font-normal text-[16px] leading-tight">
                                    <ConfidenceMarkIcon className="w-[20px] h-[20px]" />
                                    <span className="text-white/90">
                                        Уверенность:{' '}
                                        <span className={`${getConfidenceColor(analysisData.age_confidence)} font-unbounded font-normal text-[16px]`}>
                                            {Math.round(analysisData.age_confidence * 100)}%
                                        </span>
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white/10 rounded-[14px] p-1 flex gap-2">
                        {TAB_CONFIG.map(tab => {
                            const disabled = tab.requiresDetails && !detailUnlocked
                            const isActive = activeTab === tab.id
                            return (
                                <button
                                    key={tab.id}
                                    onClick={() => handleTabChange(tab.id)}
                                    disabled={disabled}
                                    className={`flex-1 py-2 rounded-[12px] text-[13px] font-unbounded uppercase tracking-[0.08em] transition-all ${isActive ? 'bg-wink-orange text-white shadow-[0px_8px_18px_rgba(254,148,46,0.35)]' : disabled ? 'text-white/30 cursor-not-allowed border border-transparent' : 'text-white/80 border border-transparent hover:text-white hover:bg-wink-orange/20'}`}
                                >
                                    {tab.label}
                                </button>
                            )
                        })}
                    </div>

                    {activeTab === 'analytics' && (
                        <>
                            <StageProgress stages={stages} stageProgress={stageProgress} />

                            {analysisData.model_explanation && (
                                <div className="bg-white/10 rounded-[14px] p-5 text-white/80 font-poppins text-[14px] leading-relaxed space-y-2 shadow-[0px_16px_30px_rgba(0,0,0,0.25)]">
                                    <h3 className="font-unbounded text-[16px] text-white mb-3">
                                        Объяснение модели
                                    </h3>
                                    <div
                                        className="text-white/80 prose prose-invert max-w-none"
                                        dangerouslySetInnerHTML={{ __html: formatMarkdown(analysisData.model_explanation) }}
                                    />
                                </div>
                            )}

                            {analysisData.law_explanation && (
                                <div className="bg-white/10 rounded-[14px] p-5 text-white/80 font-poppins text-[14px] leading-relaxed space-y-2 shadow-[0px_16px_30px_rgba(0,0,0,0.25)]">
                                    <h3 className="font-unbounded text-[16px] text-white">
                                        Краткий вывод
                                    </h3>
                                    <p className="text-white/80 whitespace-pre-wrap">
                                        {analysisData.law_explanation}
                                    </p>
                                </div>
                            )}

                            <div className="bg-white/10 rounded-[14px] p-5 text-white/80 font-poppins text-[14px] leading-relaxed space-y-4">
                                <h3 className="font-unbounded text-[16px] text-white">
                                    Сводка по категориям
                                </h3>
                                <div className="space-y-3">
                                    {analyticsSummary.map(reason => (
                                        <div key={`summary-${reason.code}`} className="flex items-center justify-between bg-white/5 rounded-[12px] px-4 py-3 border border-white/10">
                                            <div className="flex-1">
                                                <p className="text-white font-poppins font-semibold text-[14px]">
                                                    {reason.label}
                                                </p>
                                                <p className="text-white/60 text-[12px]">
                                                    Эпизодов: {reason.episodes} · Сцены с нарушениями: {Math.round(reason.scenesWithIssuesPercent)}%
                                                </p>
                                            </div>
                                            <span className="text-white font-unbounded text-[16px]">
                                                {Math.round(reason.score * 100)}%
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </>
                    )}

                    {activeTab === 'categories' && (
                        <div className="bg-white/10 rounded-[10px] p-6 h-full overflow-hidden flex flex-col">
                            <div className="flex items-start justify-between mb-4">
                                <h3 className="text-white/70 text-[14px] font-poppins font-semibold">
                                    Категории нарушений
                                </h3>
                                <button
                                    onClick={onAddViolation}
                                    className="px-3 py-1.5 rounded-[10px] bg-wink-orange text-white font-poppins text-[13px] font-medium hover:bg-wink-orange-light transition-colors"
                                >
                                    Добавить нарушение
                                </button>
                            </div>
                            <div className="flex-1 overflow-y-auto pr-2 space-y-4 ScrollbarHide">
                                {reasonsWithEvidence.length === 0 ? (
                                    <p className="text-white/60 text-[14px] font-poppins text-center mt-6">
                                        Нарушения по категориям пока не найдены.
                                    </p>
                                ) : (
                                    reasonsWithEvidence.map(reason => {
                                        const fragments = evidenceByReason[reason.code] || []
                                        const visibleCount = visibleCounts[reason.code] ?? DEFAULT_VISIBLE
                                        const visibleFragments = expandedCategories[reason.code]
                                            ? fragments.slice(0, visibleCount)
                                            : []
                                        const showMoreAvailable = fragments.length > visibleCount
                                        const canCollapse = fragments.length > DEFAULT_VISIBLE && visibleCount > DEFAULT_VISIBLE

                                        return (
                                            <div key={reason.code} className="space-y-2">
                                                <CategoryScore
                                                    reason={reason}
                                                    isExpanded={expandedCategories[reason.code]}
                                                    onToggle={() => toggleCategory(reason.code)}
                                                />

                                                {expandedCategories[reason.code] && (
                                                    <div className="space-y-3">
                                                        {visibleFragments.map(fragment => (
                                                            <ProblematicFragment
                                                                key={fragment.id}
                                                                fragment={fragment}
                                                                reasonLabel={reason.label ?? reasonLabels[reason.code]}
                                                                isActive={activeFragmentId === fragment.id}
                                                                onEdit={onFragmentEdit}
                                                                onReplace={onFragmentReplace}
                                                                onNavigate={onFragmentNavigate}
                                                                onFocus={onFragmentFocus}
                                                                onRevert={onFragmentRevert}
                                                                onManage={onManageViolation}
                                                                onRequestDetails={handleJumpToDetails}
                                                                variant="overview"
                                                                dataFragmentId={fragment.id}
                                                            />
                                                        ))}

                                                        {fragments.length === 0 && (
                                                            <p className="text-white/60 text-[14px] font-poppins font-normal">Нарушений не найдено</p>
                                                        )}

                                                        {fragments.length > 0 && (
                                                            <div className="flex gap-4 text-white/60 text-[12px] font-poppins font-medium">
                                                                {showMoreAvailable && (
                                                                    <button onClick={() => handleShowMore(reason.code)} className="hover:text-white transition-colors">
                                                                        Показать ещё
                                                                    </button>
                                                                )}
                                                                {canCollapse && (
                                                                    <button onClick={() => handleCollapse(reason.code)} className="hover:text-white transition-colors">
                                                                        Скрыть
                                                                    </button>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })
                                )}
                            </div>
                        </div>
                    )}

                    {activeTab === 'details' && (
                        <div className="bg-white/10 rounded-[14px] p-6 h-full overflow-hidden flex flex-col">
                            {!detailUnlocked ? (
                                <div className="flex-1 flex items-center justify-center text-white/60 font-poppins text-[14px] text-center px-6">
                                    Детальная информация появится после завершения всех стадий анализа.
                                </div>
                            ) : (
                                <div className="flex-1 overflow-y-auto pr-2 space-y-4 ScrollbarHide">
                                    {filteredEvidence.length === 0 ? (
                                        <p className="text-white/60 text-[14px] font-poppins text-center mt-10">
                                            Нарушения не найдены.
                                        </p>
                                    ) : (
                                        filteredEvidence.map(fragment => (
                                            <ProblematicFragment
                                                key={`details-${fragment.id}`}
                                                fragment={fragment}
                                                reasonLabel={reasonLabels[fragment.reason] ?? fragment.reason}
                                                isActive={activeFragmentId === fragment.id}
                                                onEdit={onFragmentEdit}
                                                onReplace={onFragmentReplace}
                                                onNavigate={onFragmentNavigate}
                                                onFocus={onFragmentFocus}
                                                onRevert={onFragmentRevert}
                                                onManage={onManageViolation}
                                                variant="details"
                                                isDetailsExpanded={expandedDetails[fragment.id] ?? false}
                                                onToggleDetails={(next) => handleToggleDetails(fragment.id, next)}
                                                onRequestCategory={() => handleJumpToCategories(fragment)}
                                            />
                                        ))
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div className="flex-shrink-0 space-y-2 pt-4 mt-4 border-t border-white/10">
                    <button
                        onClick={onRecalculate}
                        className="w-full h-[52px] rounded-[14px] bg-wink-orange text-white font-unbounded font-bold text-[16px] shadow-[0px_10px_24px_rgba(254,148,46,0.35)] hover:bg-wink-orange-light transition-colors"
                    >
                        Перерасчитать рейтинг
                    </button>
                    <button
                        type="button"
                        onClick={handleExportClick}
                        className={`w-full h-[52px] rounded-[14px] font-unbounded font-bold text-[16px] transition-colors ${exportDisabled ? 'bg-white/10 text-white/40 cursor-not-allowed border border-white/15' : 'bg-white/80 text-wink-black hover:bg-white/90 shadow-[0px_12px_30px_rgba(22,22,22,0.2)]'}`}
                        aria-disabled={exportDisabled}
                    >
                        Показать отчёт
                    </button>
                    {exportTooltipVisible && exportDisabled && (
                        <p className="text-wink-orange text-[12px] text-center">
                            Пересчитайте рейтинг, чтобы учесть все изменения
                        </p>
                    )}
                </div>
            </div>
            <div
                className="absolute top-0 right-0 h-full w-[10px] cursor-col-resize"
                onMouseDown={handleResizeStart}
                role="separator"
                aria-orientation="vertical"
                aria-label="Изменить ширину панели"
            />
        </aside>
    )
}

export default AnalysisPanel

