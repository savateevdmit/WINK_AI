const sanitizeLine = (line = '') => line.replace(/\r/g, '').trim()

export const splitSceneIntoSentences = (content = '') => {
    if (!content) return []
    return content
        .split(/\n+/)
        .map(sanitizeLine)
        .filter(Boolean)
}

export const buildAllScenesPayload = (scenes = []) => {
    return {
        all_scenes: scenes.map(scene => {
            // ВАЖНО: Используем оригинальную структуру предложений, если она есть,
            // чтобы сохранить согласование с sentence_index от бэкенда
            // Бэкенд ожидает только { id, text } в sentences при отправке
            let sentences = []
            
            if (scene?.originalSentences && Array.isArray(scene.originalSentences) && scene.originalSentences.length > 0) {
                // Используем оригинальную структуру от бэкенда
                // При отправке на бэкенд отправляем только id и text (как ожидает бэкенд)
                sentences = scene.originalSentences.map(s => ({
                    id: s.id ?? 0,
                    text: s.text ?? ''
                    // НЕ отправляем kind, speaker, line_no - бэкенд их не ожидает в этом эндпоинте
                })).filter(s => s.text)
            } else {
                // Fallback: разбиваем content по переносам строк (старое поведение)
                const splitSentences = splitSceneIntoSentences(scene?.content ?? '')
                sentences = splitSentences.map((text, index) => ({ id: index, text }))
            }
            
            return {
                heading: scene?.heading ?? '',
                replace_sentences_id: sentences.map((_, index) => index),
                age_rating: scene?.ageRating ?? '',
                sentences: sentences
            }
        })
    }
}
