import { useEffect, useMemo, useState } from 'react'
import { getLabelDetails } from '../utils/mockApi'

const severityOptions = [
    { value: 'Severe', label: 'Severe' },
    { value: 'Moderate', label: 'Moderate' },
    { value: 'Mild', label: 'Mild' },
    { value: 'None', label: 'None' }
]

const defaultLabelDetails = (label, severity) => {
    const base = getLabelDetails(label, severity) ?? {}
    return {
        ...base,
        severity: severity ?? 'Moderate',
        score: base.score ?? 60,
        trigger: null
    }
}

const buildInitialState = (mode, fragment, scenes, initialData) => {
    if (mode === 'edit' && fragment) {
        const labelDetails = {}
        fragment.labels?.forEach(label => {
            const span = fragment.evidenceSpans?.[label]
            labelDetails[label] = {
                severity: span?.severity ?? fragment.severity ?? 'Moderate',
                reason: span?.reason ?? '',
                advice: span?.advice ?? '',
                score: span?.score ?? 60,
                trigger: span?.trigger ?? null
            }
        })

        return {
            id: fragment.id,
            text: fragment.originalText ?? fragment.text ?? '',
            sceneIndex: fragment.sceneIndex ?? (fragment.sceneHeading ? scenes?.find?.(scene => scene.heading === fragment.sceneHeading)?.sceneNumber : null) ?? null,
            labels: fragment.labels ?? [],
            severity: fragment.severity ?? 'Moderate',
            labelDetails
        }
    }

    if (initialData) {
        return {
            id: null,
            text: initialData.text ?? '',
            sceneIndex: initialData.sceneNumber ?? scenes?.[0]?.sceneNumber ?? 0,
            labels: initialData.labels ?? [],
            severity: 'Mild',
            labelDetails: {}
        }
    }

    const firstScene = scenes?.[0]
    return {
        id: null,
        text: '',
        sceneIndex: firstScene?.sceneNumber ?? 0,
        labels: [],
        severity: 'Mild',
        labelDetails: {}
    }
}

const ViolationEditorModal = ({
    isOpen,
    mode = 'add',
    fragment,
    initialData,
    scenes = [],
    availableLabels = [],
    onClose,
    onSubmit
}) => {
    const [form, setForm] = useState(() => buildInitialState(mode, fragment, scenes, initialData))
    const [validationError, setValidationError] = useState('')
    const [labelSearch, setLabelSearch] = useState('')

    useEffect(() => {
        if (isOpen) {
            setForm(buildInitialState(mode, fragment, scenes, initialData))
            setValidationError('')
            setLabelSearch('')
        }
    }, [isOpen, mode, fragment, scenes, initialData])

    const filteredLabels = useMemo(() => {
        if (!labelSearch) return availableLabels
        const query = labelSearch.toLowerCase()
        return availableLabels.filter(label => label.toLowerCase().includes(query))
    }, [availableLabels, labelSearch])

    const sceneOptions = useMemo(() => {
        return scenes.map(scene => ({
            value: scene.sceneNumber,
            label: scene.heading ?? `Сцена ${scene.sceneNumber}`
        }))
    }, [scenes])

    if (!isOpen) return null

    const handleFieldChange = (field, value) => {
        setForm(prev => ({ ...prev, [field]: value }))
    }

    const addLabel = (label) => {
        if (!label) return
        setForm(prev => {
            if (prev.labels.includes(label)) {
                return prev
            }
            return {
                ...prev,
                labels: [...prev.labels, label],
                labelDetails: {
                    ...prev.labelDetails,
                    [label]: prev.labelDetails[label] ?? defaultLabelDetails(label, prev.severity)
                }
            }
        })
    }

    const removeLabel = (label) => {
        setForm(prev => {
            if (!prev.labels.includes(label)) {
                return prev
            }
            const nextDetails = { ...prev.labelDetails }
            delete nextDetails[label]

            return {
                ...prev,
                labels: prev.labels.filter(item => item !== label),
                labelDetails: nextDetails
            }
        })
    }

    const toggleLabel = (label) => {
        if (!label) return
        if (form.labels.includes(label)) {
            removeLabel(label)
        } else {
            addLabel(label)
        }
    }

    const updateLabelDetail = (label, field, value) => {
        setForm(prev => ({
            ...prev,
            labelDetails: {
                ...prev.labelDetails,
                [label]: {
                    ...(prev.labelDetails[label] ?? defaultLabelDetails(label, prev.severity)),
                    [field]: value
                }
            }
        }))
    }

    const handleSubmit = (event) => {
        event.preventDefault()
        if (!form.labels.length) {
            setValidationError('Выберите хотя бы одну метку')
            return
        }
        if (!form.text.trim()) {
            setValidationError('Текст фрагмента не может быть пустым')
            return
        }

        const evidenceSpans = {}
        form.labels.forEach(label => {
            const span = form.labelDetails[label] ?? defaultLabelDetails(label, form.severity)
            evidenceSpans[label] = {
                severity: span.severity ?? form.severity,
                reason: span.reason ?? '',
                advice: span.advice ?? '',
                score: Number.isFinite(span.score) ? span.score : 60,
                trigger: null
            }
        })

        const payload = {
            id: form.id,
            mode,
            text: form.text,
            originalText: form.text,
            sceneIndex: Number(form.sceneIndex),
            sceneHeading: scenes.find(scene => scene.sceneNumber === Number(form.sceneIndex))?.heading ?? '',
            labels: form.labels,
            severity: form.severity,
            evidenceSpans
        }

        onSubmit?.(payload)
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="bg-[#121212] text-white rounded-[18px] w-[720px] max-h-[90vh] overflow-hidden shadow-[0px_30px_60px_rgba(0,0,0,0.65)] border border-white/10">
                <div className="flex items-center justify-between px-6 py-5 border-b border-white/10 bg-white/5">
                    <h2 className="font-unbounded text-[20px]">
                        {mode === 'add' ? 'Добавить нарушение вручную' : 'Редактировать нарушение'}
                    </h2>
                    <button
                        onClick={onClose}
                        className="text-white/70 hover:text-white text-[24px] leading-none"
                    >
                        ×
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="px-6 py-5 overflow-y-auto ScrollbarHide space-y-5" style={{ maxHeight: '70vh' }}>
                    <div className="space-y-2">
                        <p className="text-[13px] font-poppins text-white/70">Сцена</p>
                        <div className="relative">
                            <select
                                value={form.sceneIndex ?? ''}
                                onChange={(e) => handleFieldChange('sceneIndex', e.target.value)}
                                required
                                className="w-full appearance-none bg-white/10 border border-white/20 rounded-[12px] px-4 py-3 text-white text-[14px] focus:outline-none focus:border-wink-orange pr-10"
                            >
                                {sceneOptions.map(option => (
                                    <option key={option.value} value={option.value} className="bg-[#1d1d1d]">
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-white/60">▾</span>
                        </div>
                    </div>

                    <label className="flex flex-col gap-2 text-[13px] font-poppins text-white/70">
                        Текст фрагмента
                        <textarea
                            value={form.text}
                            onChange={(e) => handleFieldChange('text', e.target.value)}
                            rows={4}
                            className="bg-white/10 border border-white/20 rounded-[12px] px-3 py-3 text-white text-[14px] resize-none focus:outline-none focus:border-wink-orange"
                        />
                    </label>

                    <label className="flex flex-col gap-2 text-[13px] font-poppins text-white/70">
                        Тяжесть фрагмента
                        <select
                            value={form.severity}
                            onChange={(e) => handleFieldChange('severity', e.target.value)}
                            className="bg-white/10 border border-white/20 rounded-[10px] px-3 py-2 text-white text-[14px] focus:outline-none focus:border-wink-orange"
                        >
                            {severityOptions.map(option => (
                                <option key={option.value} value={option.value} className="bg-[#1d1d1d]">
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>

                    <div className="space-y-3">
                        <p className="text-white/70 text-[13px] font-poppins">
                            Метки
                        </p>
                        <input
                            type="text"
                            value={labelSearch}
                            onChange={(event) => setLabelSearch(event.target.value)}
                            placeholder="Поиск метки…"
                            className="w-full bg-white/10 border border-white/20 rounded-[10px] px-3 py-2 text-white text-[13px] focus:outline-none focus:border-wink-orange"
                        />
                        <div className="flex flex-wrap gap-2 max-h-[140px] overflow-y-auto pr-2 ScrollbarHide">
                            {filteredLabels.length > 0 ? (
                                filteredLabels.map(label => {
                                    const isActive = form.labels.includes(label)
                                    return (
                                        <button
                                            key={label}
                                            type="button"
                                            onClick={() => toggleLabel(label)}
                                            className={`px-3 py-1.5 rounded-full text-[12px] font-poppins border transition-colors ${isActive ? 'bg-wink-orange text-white border-wink-orange' : 'bg-white/5 text-white/70 border-white/15 hover:bg-white/10'}`}
                                        >
                                            {label}
                                        </button>
                                    )
                                })
                            ) : (
                                <span className="text-white/40 text-[12px] font-poppins">
                                    Ничего не найдено
                                </span>
                            )}
                        </div>
                    </div>

                    {form.labels.length > 0 && (
                        <div className="space-y-4">
                            <p className="text-white/70 text-[13px] font-poppins">
                                Обоснования и советы для выбранных меток
                            </p>
                            {form.labels.map(label => {
                                const details = form.labelDetails[label] ?? defaultLabelDetails(label, form.severity)
                                return (
                                    <div key={`details-${label}`} className="bg-white/10 rounded-[12px] border border-white/15 px-4 py-4 space-y-3">
                                        <div className="flex items-center justify-between">
                                            <span className="uppercase tracking-[0.08em] text-[12px] text-white/70">
                                                {label}
                                            </span>
                                            <div className="flex items-center gap-2">
                                                <label className="text-[12px] text-white/60">
                                                    Оценка:
                                                </label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="100"
                                                    value={details.score ?? 60}
                                                    onChange={(e) => updateLabelDetail(label, 'score', Number(e.target.value))}
                                                    className="w-[80px] bg-white/10 border border-white/20 rounded-[8px] px-2 py-1 text-white text-[12px] focus:outline-none focus:border-wink-orange"
                                                />
                                            </div>
                                        </div>
                                        <label className="text-[12px] text-white/70 flex flex-col gap-1">
                                            Локальная тяжесть
                                            <select
                                                value={details.severity ?? form.severity}
                                                onChange={(e) => updateLabelDetail(label, 'severity', e.target.value)}
                                                className="bg-white/10 border border-white/20 rounded-[8px] px-2 py-1 text-white text-[12px] focus:outline-none focus:border-wink-orange"
                                            >
                                                {severityOptions.map(option => (
                                                    <option key={`${label}-${option.value}`} value={option.value} className="bg-[#1d1d1d]">
                                                        {option.label}
                                                    </option>
                                                ))}
                                            </select>
                                        </label>

                                        <label className="text-[12px] text-white/70 flex flex-col gap-1">
                                            Причина
                                            <textarea
                                                value={details.reason ?? ''}
                                                onChange={(e) => updateLabelDetail(label, 'reason', e.target.value)}
                                                rows={2}
                                                className="bg-white/10 border border-white/20 rounded-[10px] px-2 py-2 text-white text-[12px] resize-none focus:outline-none focus:border-wink-orange"
                                            />
                                        </label>

                                        <label className="text-[12px] text-white/70 flex flex-col gap-1">
                                            Совет
                                            <textarea
                                                value={details.advice ?? ''}
                                                onChange={(e) => updateLabelDetail(label, 'advice', e.target.value)}
                                                rows={2}
                                                className="bg-white/10 border border-white/20 rounded-[10px] px-2 py-2 text-white text-[12px] resize-none focus:outline-none focus:border-wink-orange"
                                            />
                                        </label>
                                    </div>
                                )
                            })}
                        </div>
                    )}

                    {validationError && (
                        <div className="text-red-300 text-[12px] font-poppins">
                            {validationError}
                        </div>
                    )}

                    <div className="flex items-center justify-end gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 rounded-[12px] bg-white/10 text-white/80 text-[14px] font-poppins hover:bg-white/15 transition-colors"
                        >
                            Отмена
                        </button>
                        <button
                            type="submit"
                            className="px-5 py-2 rounded-[12px] bg-wink-orange text-white text-[14px] font-unbounded font-semibold hover:bg-wink-orange-light transition-colors"
                        >
                            {mode === 'add' ? 'Добавить' : 'Сохранить'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}

export default ViolationEditorModal


