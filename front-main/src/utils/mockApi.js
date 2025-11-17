import rawAnalysisData from './mockAnalysis.json'

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))

const CATEGORY_CONFIG = {
  Violence_Gore: { code: 'violence', label: 'Насилие' },
  Profanity: { code: 'profanity', label: 'Лексика' },
  Alcohol_Drugs_Smoking: { code: 'substances', label: 'Алкоголь, наркотики, курение' },
  Sex_Nudity: { code: 'sexual_content', label: 'Секс и нагота' },
  Crime: { code: 'crime', label: 'Преступность' },
  Weapons: { code: 'weapons', label: 'Оружие' },
  Frightening_Intense: { code: 'fear', label: 'Страшные и напряжённые сцены' }
}

export const LABEL_REASON_MAP = {
  MURDER_HOMICIDE: 'violence',
  VIOLENCE_GRAPHIC: 'violence',
  VIOLENCE_NON_GRAPHIC: 'violence',
  DANGEROUS_IMITABLE_ACTS: 'violence',
  WEAPONS_USAGE: 'weapons',
  WEAPONS_MENTION: 'weapons',
  CRIMINAL_ACTIVITY: 'crime',
  CRIME_INSTRUCTIONS: 'crime',
  MILD_CONFLICT: 'violence',
  PROFANITY_OBSCENE: 'profanity',
  DRUGS_USE_DEPICTION: 'substances',
  DRUGS_MENTION_NON_DETAILED: 'substances',
  ALCOHOL_USE: 'substances',
  TOBACCO_USE: 'substances',
  SEX_EXPLICIT: 'sexual_content',
  SEX_SUGGESTIVE: 'sexual_content',
  SEXUAL_VIOLENCE: 'sexual_content',
  NUDITY_EXPLICIT: 'sexual_content',
  NUDITY_NONSEXUAL: 'sexual_content',
  ABUSE_HATE_EXTREMISM: 'fear',
  HORROR_FEAR: 'fear',
  MEDICAL_GORE_DETAILS: 'violence',
  GAMBLING: 'crime'
}

const LABEL_DESCRIPTIONS = {
  MURDER_HOMICIDE: {
    reason: 'Сцена содержит явные угрозы убийством или описания убийства.',
    advice: 'Смягчите формулировки или уменьшите детализацию насилия.'
  },
  VIOLENCE_GRAPHIC: {
    reason: 'Фрагмент детально описывает насильственные действия.',
    advice: 'Уберите графические подробности или опишите сцену более нейтрально.'
  },
  VIOLENCE_NON_GRAPHIC: {
    reason: 'Присутствует описание насилия без графических деталей.',
    advice: 'Сократите упоминания насилия или опишите последствия мягче.'
  },
  PROFANITY_OBSCENE: {
    reason: 'Обнаружена обсценная лексика.',
    advice: 'Замените выражение на более нейтральную формулировку.'
  },
  CRIMINAL_ACTIVITY: {
    reason: 'Фрагмент поощряет или описывает противоправные действия.',
    advice: 'Уберите призывы к нарушению закона или покажите последствия.'
  },
  WEAPONS_USAGE: {
    reason: 'Есть сцены активного использования оружия.',
    advice: 'Снизьте интенсивность сцены или покажите безопасную альтернативу.'
  },
  WEAPONS_MENTION: {
    reason: 'Фрагмент содержит упоминание оружия.',
    advice: 'Переопишите сцену, избегая фокусировки на оружии.'
  },
  DRUGS_USE_DEPICTION: {
    reason: 'Описано употребление запрещённых веществ.',
    advice: 'Уберите сцену или покажите негативные последствия.'
  },
  ALCOHOL_USE: {
    reason: 'Показано употребление алкоголя.',
    advice: 'Сделайте акцент на умеренности или уберите эпизод.'
  },
  TOBACCO_USE: {
    reason: 'Фрагмент демонстрирует употребление табака.',
    advice: 'Уберите сцену или сделайте акцент на вреде курения.'
  },
  SEX_EXPLICIT: {
    reason: 'Присутствует явное описание сексуальной сцены.',
    advice: 'Сократите детали или замените сцену более деликатной.'
  },
  SEX_SUGGESTIVE: {
    reason: 'Намеки на сексуальный контент.',
    advice: 'Ослабьте сексуальный подтекст или уберите сцену.'
  },
  SEXUAL_VIOLENCE: {
    reason: 'Зафиксировано сексуальное насилие.',
    advice: 'Удалите сцену или замените на более безопасную альтернативу.'
  },
  NUDITY_EXPLICIT: {
    reason: 'Явное изображение наготы.',
    advice: 'Смягчите описание или уберите сцену.'
  },
  NUDITY_NONSEXUAL: {
    reason: 'Присутствует не сексуализированная нагота.',
    advice: 'Оцените необходимость сцены и смягчите описание.'
  },
  HORROR_FEAR: {
    reason: 'Сцена может вызвать страх или шок.',
    advice: 'Снизьте напряжение или примените предупреждение.'
  },
  DANGEROUS_IMITABLE_ACTS: {
    reason: 'Сцена описывает опасные действия, которые могут быть скопированы.',
    advice: 'Добавьте предупреждение или измените поведение персонажей.'
  }
}

export const getLabelDetails = (label, severityFallback) => {
  const base = LABEL_DESCRIPTIONS[label] ?? {
    reason: `Обнаружено срабатывание правила ${label}.`,
    advice: 'Смягчите формулировку или рассмотрите изменение сцены.'
  }

  return {
    severity: severityFallback ?? 'Moderate',
    score: 60,
    reason: base.reason,
    advice: base.advice,
    trigger: null
  }
}

export const detectReason = (labels = []) => {
  for (const label of labels) {
    const reason = LABEL_REASON_MAP[label]
    if (reason) {
      return reason
    }
  }
  return 'other'
}

export const buildReasons = (parentsGuide = {}) => {
  return Object.entries(parentsGuide)
    .map(([key, stats]) => {
      const config = CATEGORY_CONFIG[key]
      if (!config) return null

      const percent = Number(stats.scenes_with_issues_percent ?? 0)
      const score = Math.min(1, percent / 100)

      return {
        key,
        code: config.code,
        label: config.label,
        score,
        severity: stats.severity,
        episodes: stats.episodes,
        scenesWithIssuesPercent: percent
      }
    })
    .filter(Boolean)
}

export const AVAILABLE_LABELS = Object.keys(LABEL_REASON_MAP)

export const buildEvidence = (fragments = [], scenes = []) => {
  const occurrenceMap = new Map()

  console.log('%c[mockApi] 🔍 buildEvidence вызван', 'color: #9C27B0; font-weight: bold', {
    fragmentsCount: fragments?.length ?? 0,
    fragmentsType: Array.isArray(fragments) ? 'array' : typeof fragments,
    scenesCount: scenes?.length ?? 0,
    firstFragment: fragments?.[0] ? {
      keys: Object.keys(fragments[0]),
      scene_index: fragments[0].scene_index,
      text: fragments[0].text?.substring(0, 50),
      labels: fragments[0].labels
    } : null
  })

  if (!Array.isArray(fragments) || fragments.length === 0) {
    console.warn('%c[mockApi] ⚠️ buildEvidence: fragments пуст или не массив', 'color: #FF9800', {
      fragments,
      fragmentsType: typeof fragments
    })
    return []
  }

  const evidence = fragments.reduce((acc, fragment) => {
    const reason = detectReason(fragment.labels)
    if (reason === 'other') {
      console.log('%c[mockApi] ⏭️ Фрагмент пропущен (reason=other)', 'color: #757575', {
        fragmentText: fragment.text?.substring(0, 50),
        labels: fragment.labels
      })
      return acc
    }

    // Бэкенд возвращает scene_index как 0-based индекс массива сцен
    // Нужно сопоставить с sceneNumber фронтенда
    const backendSceneIndex = fragment.scene_index ?? -1
    let sceneNumber = backendSceneIndex + 1 // По умолчанию: 0->1, 1->2, и т.д.
    
    // Пытаемся найти сцену по индексу и взять её sceneNumber
    if (backendSceneIndex >= 0 && scenes && scenes.length > backendSceneIndex) {
      const scene = scenes[backendSceneIndex]
      if (scene && scene.sceneNumber !== undefined) {
        sceneNumber = scene.sceneNumber
      }
    }
    
    const sentenceIndex = fragment.sentence_index ?? null
    const baseText = fragment.text ?? ''
    const occurrenceKey = `${sceneNumber}::${baseText}`
    const occurrence = occurrenceMap.get(occurrenceKey) ?? 0
    occurrenceMap.set(occurrenceKey, occurrence + 1)

    const evidenceSpans = fragment.evidence_spans ?? {}
    const confidence = fragment.confidence ?? {}

    const mergedSpans = {}
    fragment.labels?.forEach((label) => {
      mergedSpans[label] = evidenceSpans[label] ?? getLabelDetails(label, fragment.severity_local)
      if (!confidence[label]) {
        confidence[label] = 0.82
      }
    })

    const evidenceItem = {
      id: `fragment_${sceneNumber}_${sentenceIndex ?? 'na'}_${occurrence}`,
      reason,
      text: baseText,
      sceneHeading: fragment.scene_heading,
      sceneIndex: sceneNumber, // Используем sceneNumber вместо 0-based индекса
      sentenceIndex,
      sceneFragmentIndex: occurrence,
      severity: fragment.severity_local ?? 'Moderate',
      labels: fragment.labels ?? [],
      confidence,
      evidenceSpans: mergedSpans,
      recommendations: fragment.recommendations ?? []
    }

    acc.push(evidenceItem)
    return acc
  }, [])

  console.log('%c[mockApi] ✅ buildEvidence завершён', 'color: #4CAF50; font-weight: bold', {
    inputFragmentsCount: fragments.length,
    outputEvidenceCount: evidence.length,
    evidenceReasons: [...new Set(evidence.map(e => e.reason))]
  })

  return evidence
}

export const computeConfidence = (parentsGuide = {}) => {
  const percents = Object.values(parentsGuide)
    .map(item => Number(item.scenes_with_issues_percent ?? 0))
    .filter(value => value > 0)

  if (!percents.length) {
    return 0.75
  }

  const maxPercent = Math.max(...percents)
  return Math.min(0.98, Math.max(0.65, 0.65 + maxPercent / 100))
}

export const normaliseAnalysisFromRaw = (raw = rawAnalysisData, scenes = [], existingId = null) => {
  const reasons = buildReasons(raw.parents_guide)
  const evidence = buildEvidence(raw.problem_fragments, scenes)
  const ageConfidence = computeConfidence(raw.parents_guide)

  // Используем model_final_rating, если он есть (более точный рейтинг от модели)
  // Иначе используем final_rating
  const finalRating = raw.model_final_rating ?? raw.final_rating

  console.log('%c[mockApi] 📊 normaliseAnalysisFromRaw', 'color: #2196F3; font-weight: bold', {
    existingId,
    willUseExistingId: !!existingId,
    problemFragmentsCount: Array.isArray(raw.problem_fragments) ? raw.problem_fragments.length : 0,
    evidenceCount: evidence.length,
    finalRating: finalRating,
    modelFinalRating: raw.model_final_rating,
    hasModelExplanation: !!raw.model_explanation,
    modelExplanationLength: raw.model_explanation ? raw.model_explanation.length : 0,
    modelExplanationPreview: raw.model_explanation ? raw.model_explanation.substring(0, 150) + '...' : null,
    rawKeys: Object.keys(raw),
    ageConfidence: ageConfidence
  })

  const result = {
    id: existingId || `analysis_${Date.now()}`, // Используем существующий id, если передан
    document: raw.document,
    age_label: finalRating, // Используем model_final_rating, если есть
    finalRating: finalRating, // Добавляем finalRating для совместимости
    age_confidence: ageConfidence,
    model_final_rating: raw.model_final_rating, // Сохраняем оригинальный рейтинг модели, если есть
    model_explanation: raw.model_explanation || null, // Сохраняем объяснение модели, если есть
    scenes_total: raw.scenes_total,
    parents_guide: raw.parents_guide,
    reasons,
    evidence,
    problem_fragments: raw.problem_fragments,
    law_explanation: raw.law_explanation,
    processing_seconds: raw.processing_seconds,
    stageProgress: {
      stage1: 100,
      stage2: 100,
      stage3: 100
    },
    stages: [
      { id: 'stage1', label: 'Первичная классификация', progress: 100, status: 'completed' },
      { id: 'stage2', label: 'Обогащение метаданными', progress: 100, status: 'completed' },
      { id: 'stage3', label: 'Финальная интерпретация', progress: 100, status: 'completed' }
    ],
    raw
  }

  // Логируем, что именно сохраняется в result
  console.log('%c[mockApi] ✅ normaliseAnalysisFromRaw результат', 'color: #4CAF50; font-weight: bold', {
    hasModelExplanation: !!result.model_explanation,
    modelExplanationLength: result.model_explanation ? result.model_explanation.length : 0,
    modelExplanationPreview: result.model_explanation ? result.model_explanation.substring(0, 150) + '...' : null,
    resultKeys: Object.keys(result)
  })

  return result
}

export const mockAnalyzeScript = async () => {
  await delay(600)
  return normaliseAnalysisFromRaw()
}

export const mockReanalyzeScript = async (payload) => {
  await delay(500)
  return normaliseAnalysisFromRaw()
}

export const mockAIReplace = async (fragmentText, reason, targetAgeRating = '') => {
  await delay(600)

  const replacements = {
    violence: {
      'Тут ребенка убить пытались!': 'Здесь говорили о серьёзной угрозе ребенку.',
      'У Юли паника, она пытается убежать.': 'Юля в панике пытается уйти.',
      'Стекло выбрось, а гвоздями - люк заколоти!': 'Предлагают закрыть люк без подробностей.',
      'Намертво!': 'Сделайте так, чтобы всё было надёжно.'
    },
    profanity: {
      '(злится) Да пошла ты!..': '(злится) Отстань от меня!',
      '(злится) Ты издеваешься?': '(злится) Ты серьезно?'
    }
  }

  const base = replacements[reason]?.[fragmentText] || `[Более мягкая формулировка: ${fragmentText}]`
  return targetAgeRating ? `${base} (рейтинг ${targetAgeRating})` : base
}

