import { useState, useEffect, useRef } from 'react'
import { getFragmentIcon, EditIcon, AIIcon } from '../utils/icons'
import { mockAIReplace } from '../utils/mockApi'

const severityStyles = {
    Severe: 'bg-red-500/15 text-red-200 border border-red-400/40',
    Moderate: 'bg-yellow-500/15 text-yellow-100 border border-yellow-400/40',
    Mild: 'bg-green-500/15 text-green-200 border border-green-400/40',
    None: 'bg-slate-500/15 text-slate-200 border border-slate-400/30'
}

const ProblematicFragment = ({
    fragment,
    reasonLabel,
    onEdit,
    onReplace,
    onNavigate,
    onRevert,
    onFocus,
    onManage,
    isActive,
    variant = 'overview',
    isDetailsExpanded,
    onToggleDetails,
    onRequestDetails,
    onRequestCategory,
    dataFragmentId
}) => {
    const cardRef = useRef(null)
    const aiButtonRef = useRef(null)
    const [isEditing, setIsEditing] = useState(false)
    const [editedText, setEditedText] = useState(fragment.text)
    const [aiMenu, setAiMenu] = useState({ open: false, position: { top: 0, left: 0 } })
    const ageRatings = ['0+', '6+', '12+', '16+', '18+']
    const [internalDetailsExpanded, setInternalDetailsExpanded] = useState(false)
    const [labelsExpanded, setLabelsExpanded] = useState(false)

    const reasonTitleClass = variant === 'details'
        ? 'text-white/90 font-unbounded text-[13px]'
        : 'text-white font-unbounded text-[15px]'

    useEffect(() => {
        setEditedText(fragment.text)
    }, [fragment.text])

    useEffect(() => {
        setAiMenu({ open: false, position: { top: 0, left: 0 } })
        setLabelsExpanded(false)
    }, [fragment.id])

    useEffect(() => {
        if (!aiMenu.open) return
        const handleClickOutside = (event) => {
            if (cardRef.current?.contains(event.target)) {
                if (aiButtonRef.current?.contains(event.target)) return
                if (event.target?.closest?.('[data-ai-rating-option]')) return
            }
            setAiMenu(prev => ({ ...prev, open: false }))
        }
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                setAiMenu(prev => ({ ...prev, open: false }))
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        document.addEventListener('keydown', handleKeyDown)
        return () => {
            document.removeEventListener('mousedown', handleClickOutside)
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [aiMenu.open])

    useEffect(() => {
        if (variant === 'details') {
            setInternalDetailsExpanded(isDetailsExpanded ?? false)
        }
    }, [variant, isDetailsExpanded, fragment.id])

    const detailsOpen = variant === 'details' ? (isDetailsExpanded ?? internalDetailsExpanded) : true

    const handleDetailsToggle = (nextValue) => {
        if (onToggleDetails) {
            onToggleDetails(nextValue)
        } else {
            setInternalDetailsExpanded(nextValue)
        }
    }

    const handleEdit = (e) => {
        e.stopPropagation()
        setIsEditing(true)
    }

    const handleSave = () => {
        onEdit(fragment, editedText)
        setIsEditing(false)
    }

    const handleCancel = () => {
        setEditedText(fragment.text)
        setIsEditing(false)
    }

    const openAiMenu = (event) => {
        event.stopPropagation()
        if (aiMenu.open) {
            setAiMenu({ open: false, position: { top: 0, left: 0 } })
            return
        }

        if (!aiButtonRef.current || !cardRef.current) {
            setAiMenu({ open: true, position: { top: 48, left: 16 } })
            return
        }

        const buttonRect = aiButtonRef.current.getBoundingClientRect()
        const cardRect = cardRef.current.getBoundingClientRect()
        const cardWidth = cardRef.current.clientWidth
        const cardHeight = cardRef.current.clientHeight

        let top = buttonRect.bottom - cardRect.top + 12
        let left = buttonRect.left - cardRect.left

        const maxLeft = cardWidth - 200
        top = Math.max(12, Math.min(cardHeight - 80, top))
        left = Math.max(12, Math.min(maxLeft, left))

        setAiMenu({ open: true, position: { top, left } })
    }

    const handleAiOptionSelect = async (rating) => {
        setAiMenu({ open: false, position: { top: 0, left: 0 } })

        try {
            // Вызываем onReplace с фрагментом и рейтингом
            // onReplace теперь сам обрабатывает вызов API
            await onReplace(fragment, rating)
            // Не устанавливаем editedText здесь - это сделает handleFragmentEdit после получения результата
        } catch (error) {
            console.error('AI replace failed', error)
        }
    }

    const scrollToFragment = (e) => {
        e.stopPropagation()
        if (onNavigate) {
            onNavigate(fragment)
        }
    }

    const handleRevert = (e) => {
        e.stopPropagation()
        onRevert?.(fragment.id)
    }

    const handleFocus = () => {
        onFocus?.(fragment.id, fragment.sceneIndex)
    }

    return (
        <div
            className={`relative bg-[#ffffff1a] rounded-[10px] p-5 hover:bg-[#ffffff26] transition-colors border ${isActive ? 'border-wink-orange' : 'border-transparent'}`}
            onClick={handleFocus}
            data-panel-fragment={fragment.id}
            ref={cardRef}
        >
            <div className="absolute top-[21px] left-[25px] w-[18px] h-[18px]">
                {getFragmentIcon(fragment.reason)}
            </div>

            <button
                onClick={scrollToFragment}
                className="absolute top-4 right-4 w-7 h-7 rounded-full border border-white/30 text-white flex items-center justify-center hover:border-wink-orange hover:text-wink-orange transition-colors"
                aria-label="Перейти к фрагменту"
            >
                →
            </button>

            <div className="ml-[53px] pr-[56px] mb-3 space-y-2">
                <div className="flex flex-wrap items-center gap-3">
                    <span className={reasonTitleClass}>
                        {reasonLabel ?? 'Категория'}
                    </span>
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-poppins tracking-wide ${severityStyles[fragment.severity] ?? severityStyles.Moderate}`}>
                        Тяжесть: {fragment.severity ?? 'Moderate'}
                    </span>
                    {fragment.sceneHeading && (
                        <span className="text-white/70 font-poppins text-[12px] bg-white/10 rounded-full px-3 py-1">
                            Сцена: {fragment.sceneHeading.split('\n')[0].trim()}
                        </span>
                    )}
                    {fragment.sentenceIndex !== undefined && fragment.sentenceIndex !== null && (
                        <span className="text-white/60 font-poppins text-[12px]">
                            Предложение №{fragment.sentenceIndex + 1}
                        </span>
                    )}
                </div>
                <p className="text-white text-[16px] font-poppins font-normal leading-relaxed">
                    {fragment.text}
                </p>
            </div>

            {fragment.labels?.length > 0 && (
                <div className="ml-[53px] pr-[56px] mb-3">
                    <button
                        type="button"
                        onClick={(event) => {
                            event.stopPropagation()
                            setLabelsExpanded(prev => !prev)
                        }}
                        className="px-3 py-1.5 rounded-[10px] bg-white/10 text-white/80 text-[11px] font-unbounded uppercase tracking-[0.08em] flex items-center gap-2 hover:bg-white/15 transition-colors"
                        aria-expanded={labelsExpanded}
                    >
                        Метки ({fragment.labels.length})
                        <span className="text-white/60 text-[10px]">{labelsExpanded ? '▲' : '▼'}</span>
                    </button>
                    {labelsExpanded && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                            {fragment.labels.map(label => (
                                <span
                                    key={label}
                                    className="px-2 py-0.5 text-[11px] font-poppins text-white/80 bg-white/8 border border-white/12 rounded-full uppercase tracking-[0.08em]"
                                >
                                    {label.replace(/_(MILD|MODERATE|SEVERE)$/i, '')}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {variant === 'details' && fragment.evidenceSpans && (
                <div className="ml-[53px] pr-[56px] mb-3">
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            handleDetailsToggle(!detailsOpen)
                        }}
                        className={`px-4 py-2 rounded-[10px] text-[12px] font-unbounded tracking-[0.08em] transition-colors ${detailsOpen ? 'bg-white/15 text-white hover:bg-white/25' : 'bg-wink-orange text-white hover:bg-wink-orange-light'}`}
                    >
                        {detailsOpen ? 'Скрыть подробности' : 'Подробнее'}
                    </button>
                </div>
            )}

            {variant === 'details' && fragment.evidenceSpans && detailsOpen && (
                <div className="ml-[53px] pr-[56px] mb-4 space-y-3">
                    {fragment.labels?.map(label => {
                        const span = fragment.evidenceSpans?.[label]
                        if (!span) return null
                        return (
                            <div key={`span-${label}`} className="bg-white/8 rounded-[10px] p-3 border border-white/10">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-white/80 font-poppins text-[13px] font-semibold">
                                        Обоснование для {label}
                                    </span>
                                </div>
                                {span.reason && (
                                    <p className="text-white/80 text-[13px] font-poppins leading-relaxed">
                                        <span className="text-white/60 font-semibold">Причина:</span> {span.reason}
                                    </p>
                                )}
                                {span.advice && (
                                    <p className="text-white/75 text-[13px] font-poppins leading-relaxed mt-1">
                                        <span className="text-white/60 font-semibold">Совет:</span> {span.advice}
                                    </p>
                                )}
                            </div>
                        )
                    })}
                    {fragment.recommendations?.length > 0 && (
                        <div className="bg-white/8 rounded-[8px] p-3 border border-white/10">
                            <p className="text-white/70 font-poppins text-[11px] uppercase tracking-[0.08em] mb-1">
                                Рекомендации
                            </p>
                            <div className="flex flex-wrap gap-x-3 gap-y-1 text-white/85 text-[12px] font-poppins">
                                {fragment.recommendations.map((item, index) => (
                                    <span key={`recommendation-${fragment.id}-${index}`} className="after:content-[','] last:after:content-['']">
                                        {item}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            <div className="flex flex-wrap items-center gap-3 ml-[53px]">
                {variant === 'overview' && (
                    <>
                        <button
                            onClick={handleEdit}
                            className="h-[27px] px-2.5 py-0 bg-[#fe942e4c] rounded-[5px] flex items-center gap-1.5 hover:bg-[#fe942e66] transition-colors"
                            aria-label="Редактировать фрагмент"
                        >
                            <EditIcon className="w-[14.59px] h-[14.59px]" />
                            <span className="text-wink-orange text-[14px] font-poppins font-medium">
                                Редактировать
                            </span>
                        </button>

                        <div className="relative">
                            <button
                                ref={aiButtonRef}
                                onClick={openAiMenu}
                                className="h-[27px] px-[10px] bg-[#ffffff4c] rounded-[5px] flex items-center gap-2 hover:bg-[#ffffff66] transition-colors"
                                aria-label="Заменить с помощью AI"
                                aria-haspopup="menu"
                                aria-expanded={aiMenu.open}
                            >
                                <AIIcon className="w-4 h-4" />
                                <span className="text-white text-[14px] font-poppins font-medium">
                                    Заменить AI
                                </span>
                            </button>
                        </div>

                        {!!onManage && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onManage(fragment)
                                }}
                                className="h-[27px] px-2.5 py-0 bg-white/15 rounded-[5px] text-white text-[14px] font-poppins font-medium hover:bg-white/25 transition-colors"
                            >
                                Изменить метки
                            </button>
                        )}

                        {!!onRequestDetails && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onRequestDetails(fragment)
                                }}
                                className="h-[27px] px-2.5 py-0 bg-white/10 rounded-[5px] text-white text-[14px] font-poppins font-medium hover:bg-white/20 transition-colors"
                            >
                                Обоснование
                            </button>
                        )}
                    </>
                )}

                {variant === 'details' && !!onRequestCategory && (
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            onRequestCategory()
                        }}
                        className="h-[27px] px-2.5 py-0 bg-white/15 rounded-[5px] text-white text-[14px] font-poppins font-medium hover:bg-white/25 transition-colors"
                    >
                        К категории
                    </button>
                )}

                <button
                    onClick={handleRevert}
                    className="h-[27px] px-2.5 py-0 bg-white/20 rounded-[5px] text-white text-[14px] font-poppins font-medium hover:bg-white/30 transition-colors"
                >
                    Отменить нарушение
                </button>
            </div>

            {aiMenu.open && (
                <div
                    className="absolute z-30 bg-[#1f1f1f] border border-white/15 rounded-[12px] shadow-[0px_18px_36px_rgba(0,0,0,0.45)] min-w-[190px] overflow-hidden"
                    style={{ top: aiMenu.position.top, left: aiMenu.position.left }}
                    onMouseDown={(event) => event.stopPropagation()}
                    role="menu"
                >
                    <p className="px-4 py-2 text-white/60 text-[11px] font-unbounded uppercase tracking-[0.08em] border-b border-white/10">
                        Возрастная категория
                    </p>
                    {ageRatings.map(rating => (
                        <button
                            key={rating}
                            data-ai-rating-option
                            onClick={(event) => {
                                event.stopPropagation()
                                handleAiOptionSelect(rating)
                            }}
                            className="px-4 py-2 text-left text-white text-[14px] font-poppins hover:bg-white/10 transition-colors"
                            role="menuitem"
                        >
                            {rating}
                        </button>
                    ))}
                </div>
            )}

            {isEditing && (
                <div className="absolute inset-0 bg-wink-black/95 rounded-[10px] p-4 z-10 flex flex-col">
                    <textarea
                        value={editedText}
                        onChange={(e) => setEditedText(e.target.value)}
                        className="flex-1 bg-wink-black/50 text-white text-[14px] font-poppins font-normal p-3 rounded border border-wink-gray/50 focus:border-wink-orange focus:outline-none resize-none"
                        rows="5"
                        autoFocus
                    />
                    <div className="flex gap-2 mt-3">
                        <button
                            onClick={handleSave}
                            className="flex-1 bg-wink-orange text-white text-[14px] font-poppins font-medium py-2 rounded hover:opacity-90 transition-opacity"
                        >
                            Сохранить
                        </button>
                        <button
                            onClick={handleCancel}
                            className="flex-1 bg-wink-gray text-white text-[14px] font-poppins font-medium py-2 rounded hover:bg-wink-gray/80 transition-colors"
                        >
                            Отмена
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}

export default ProblematicFragment