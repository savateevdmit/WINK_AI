/**
 * Форматирование сценария в российском сценарном формате
 */

/**
 * Определяет тип строки сценария
 */
const detectLineType = (line, prevLine = '') => {
  const trimmed = line.trim()
  if (!trimmed) return 'empty'

  // Заголовок сцены (обычно начинается с номера и содержит ИНТ/НАТ/ЭКСТ и т.п.)
  if (/^\d+[-\d]*[.\s]*(ИНТ|НАТ|ЭКСТ|INT|EXT|INT\.|EXT\.|ИНТ\.|НАТ\.|ЭКСТ\.)/i.test(trimmed)) {
    return 'scene_heading'
  }

  // Персонаж (обычно капсом, по центру, без точки в конце)
  if (
    trimmed === trimmed.toUpperCase() &&
    trimmed.length > 1 &&
    trimmed.length < 50 &&
    !trimmed.endsWith('.') &&
    !trimmed.includes(':') &&
    !/^\d/.test(trimmed) &&
    prevLine.trim() === '' // Персонаж обычно после пустой строки
  ) {
    return 'character'
  }

  // Реплика (обычно после персонажа, с отступом)
  if (prevLine && detectLineType(prevLine) === 'character') {
    return 'dialogue'
  }

  // Ремарка (в скобках, обычно после персонажа или реплики)
  if (/^\([^)]+\)$/.test(trimmed) || /^\([^)]*$/.test(trimmed)) {
    return 'parenthetical'
  }

  // Вставка (ЗК, OFF, ОFF и т.п.)
  if (/^(ЗК|OFF|ОFF|ВК|ВК\.|ЗК\.|OFF\.|ОFF\.)/i.test(trimmed)) {
    return 'transition'
  }

  // Действие (по умолчанию)
  return 'action'
}

/**
 * Форматирует строку в зависимости от типа
 */
const formatLine = (line, lineType, options = {}) => {
  const { indentAction = 0, indentDialogue = 0, indentCharacter = 0 } = options
  const trimmed = line.trim()

  switch (lineType) {
    case 'scene_heading':
      // Заголовок сцены - капсом, без отступа
      return trimmed.toUpperCase()

    case 'character':
      // Персонаж - капсом, по центру (примерно 40% от левого края)
      const charIndent = Math.max(0, indentCharacter)
      return ' '.repeat(charIndent) + trimmed.toUpperCase()

    case 'dialogue':
      // Реплика - с отступом
      const dialogueIndent = Math.max(0, indentDialogue)
      return ' '.repeat(dialogueIndent) + trimmed

    case 'parenthetical':
      // Ремарка - с отступом, в скобках
      const parenIndent = Math.max(0, indentDialogue + 10)
      return ' '.repeat(parenIndent) + trimmed

    case 'transition':
      // Вставка - справа
      return trimmed.toUpperCase().padStart(70)

    case 'action':
      // Действие - с отступом
      const actionIndent = Math.max(0, indentAction)
      return ' '.repeat(actionIndent) + trimmed

    case 'empty':
      return ''

    default:
      return trimmed
  }
}

/**
 * Форматирует сцену в российском сценарном формате
 */
export const formatScene = (scene, options = {}) => {
  const {
    indentAction = 0,
    indentDialogue = 25,
    indentCharacter = 20,
    sceneSeparator = '\n\n'
  } = options

  const lines = []
  
  // Проверяем, не начинается ли контент с заголовка сцены
  let contentStartsWithHeading = false
  let headingInContent = null // Сохраняем найденный заголовок в контенте
  
  // Проверяем первый блок, если есть
  if (scene.blocks && Array.isArray(scene.blocks) && scene.blocks.length > 0) {
    const firstBlock = scene.blocks[0]
    if (firstBlock && firstBlock.text) {
      const firstLine = firstBlock.text.split('\n')[0]?.trim() || ''
      // Проверяем, является ли первая строка заголовком сцены
      if (firstLine && detectLineType(firstLine, '') === 'scene_heading') {
        contentStartsWithHeading = true
        headingInContent = firstLine
      }
      // Также проверяем, не совпадает ли первая строка с scene.heading (с учетом возможных различий в регистре и пробелах)
      if (scene.heading) {
        const headingNormalized = scene.heading.toUpperCase().trim()
        const firstLineNormalized = firstLine.toUpperCase().trim()
        if (firstLineNormalized === headingNormalized || 
            firstLineNormalized.includes(headingNormalized) || 
            headingNormalized.includes(firstLineNormalized)) {
          contentStartsWithHeading = true
          headingInContent = firstLine
        }
      }
    }
  }
  
  // Проверяем content, если нет blocks
  if (!contentStartsWithHeading && scene.content && !scene.blocks) {
    const contentLines = scene.content.split('\n')
    const firstLine = contentLines[0]?.trim() || ''
    if (firstLine && detectLineType(firstLine, '') === 'scene_heading') {
      contentStartsWithHeading = true
      headingInContent = firstLine
    }
    // Также проверяем, не совпадает ли первая строка с scene.heading
    if (scene.heading) {
      const headingNormalized = scene.heading.toUpperCase().trim()
      const firstLineNormalized = firstLine.toUpperCase().trim()
      if (firstLineNormalized === headingNormalized || 
          firstLineNormalized.includes(headingNormalized) || 
          headingNormalized.includes(firstLineNormalized)) {
        contentStartsWithHeading = true
        headingInContent = firstLine
      }
    }
  }
  
  // Проверяем originalSentences, если нет blocks и content
  if (!contentStartsWithHeading && scene.originalSentences && Array.isArray(scene.originalSentences) && scene.originalSentences.length > 0) {
    const firstSentence = scene.originalSentences[0]
    if (firstSentence && firstSentence.text) {
      const firstLine = firstSentence.text.split('\n')[0]?.trim() || ''
      if (firstLine && detectLineType(firstLine, '') === 'scene_heading') {
        contentStartsWithHeading = true
        headingInContent = firstLine
      }
      if (scene.heading) {
        const headingNormalized = scene.heading.toUpperCase().trim()
        const firstLineNormalized = firstLine.toUpperCase().trim()
        if (firstLineNormalized === headingNormalized || 
            firstLineNormalized.includes(headingNormalized) || 
            headingNormalized.includes(firstLineNormalized)) {
          contentStartsWithHeading = true
          headingInContent = firstLine
        }
      }
    }
  }
  
  // Заголовок сцены - капсом (только если его нет в контенте)
  if (scene.heading && !contentStartsWithHeading) {
    lines.push(scene.heading.toUpperCase())
    lines.push('') // Пустая строка после заголовка
  } else if (contentStartsWithHeading && headingInContent) {
    // Если заголовок найден в контенте, добавляем его один раз здесь
    lines.push(headingInContent.toUpperCase())
    lines.push('') // Пустая строка после заголовка
  }

  // Если есть blocks (структурированные данные от бэкенда)
  if (scene.blocks && Array.isArray(scene.blocks) && scene.blocks.length > 0) {
    scene.blocks.forEach((block, index) => {
      const blockType = block.type || 'action'
      const text = block.text || ''
      
      if (!text.trim()) return
      
      // Убираем заголовок сцены из первого блока, если он там есть (чтобы избежать дублирования)
      let processedText = text
      if (index === 0 && contentStartsWithHeading && headingInContent) {
        const firstLine = text.split('\n')[0]?.trim() || ''
        const firstLineNormalized = firstLine.toUpperCase().trim()
        const headingNormalized = headingInContent.toUpperCase().trim()
        // Если первая строка блока - это заголовок сцены, убираем её
        if (firstLine && (detectLineType(firstLine, '') === 'scene_heading' || 
            firstLineNormalized === headingNormalized ||
            (scene.heading && firstLineNormalized === scene.heading.toUpperCase().trim()))) {
          // Убираем первую строку из текста блока
          processedText = text.split('\n').slice(1).join('\n')
          if (!processedText.trim()) return // Если после удаления заголовка ничего не осталось, пропускаем блок
        }
      }

      switch (blockType) {
        case 'dialogue':
          // Диалог: персонаж -> реплика
          if (block.speaker) {
            // Персонаж - капсом, по центру
            lines.push('')
            lines.push(formatLine(block.speaker, 'character', { indentCharacter }))
            // Реплика
            const dialogueLines = processedText.split('\n').filter(l => l.trim())
            dialogueLines.forEach(dialogueLine => {
              // Проверяем, не является ли строка ремаркой
              const trimmedDialogue = dialogueLine.trim()
              if (/^\([^)]+\)$/.test(trimmedDialogue) || /^\([^)]*$/.test(trimmedDialogue)) {
                lines.push(formatLine(dialogueLine, 'parenthetical', { indentDialogue }))
              } else {
                lines.push(formatLine(dialogueLine, 'dialogue', { indentDialogue }))
              }
            })
            lines.push('')
          } else {
            // Реплика без персонажа
            processedText.split('\n').forEach(dialogueLine => {
              if (dialogueLine.trim()) {
                lines.push(formatLine(dialogueLine, 'dialogue', { indentDialogue }))
              }
            })
          }
          break

        case 'action':
        default:
          // Действие
          const actionLines = processedText.split('\n').filter(l => l.trim())
          actionLines.forEach(actionLine => {
            const trimmed = actionLine.trim()
            
            // Дополнительная проверка: не добавляем заголовок сцены, если он уже был добавлен
            if (index === 0 && contentStartsWithHeading && headingInContent) {
              const lineNormalized = trimmed.toUpperCase().trim()
              const headingNormalized = headingInContent.toUpperCase().trim()
              if (lineNormalized === headingNormalized || 
                  (scene.heading && lineNormalized === scene.heading.toUpperCase().trim())) {
                return // Пропускаем эту строку, так как заголовок уже добавлен
              }
            }
            
            // Проверяем, не является ли строка вставкой (ЗК, OFF и т.п.)
            if (/^(ЗК|OFF|ОFF|ВК|ВК\.|ЗК\.|OFF\.|ОFF\.)/i.test(trimmed)) {
              lines.push(formatLine(actionLine, 'transition', {}))
            } else {
              lines.push(formatLine(actionLine, 'action', { indentAction }))
            }
          })
          // Добавляем пустую строку после действия, если следующее - диалог
          if (index < scene.blocks.length - 1 && scene.blocks[index + 1]?.type === 'dialogue') {
            // Пустая строка уже будет добавлена перед диалогом
          }
          break
      }
    })
  } else if (scene.originalSentences && Array.isArray(scene.originalSentences) && scene.originalSentences.length > 0) {
    // Используем originalSentences, если есть информация о kind и speaker
    let currentSpeaker = null
    scene.originalSentences.forEach((sentence, index) => {
      const kind = sentence.kind || 'action'
      const speaker = sentence.speaker
      let text = sentence.text || ''

      // Убираем заголовок сцены из первого предложения, если он там есть
      if (index === 0 && contentStartsWithHeading && headingInContent) {
        const firstLine = text.split('\n')[0]?.trim() || ''
        const firstLineNormalized = firstLine.toUpperCase().trim()
        const headingNormalized = headingInContent.toUpperCase().trim()
        if (firstLine && (detectLineType(firstLine, '') === 'scene_heading' || 
            firstLineNormalized === headingNormalized ||
            (scene.heading && firstLineNormalized === scene.heading.toUpperCase().trim()))) {
          // Убираем первую строку из текста
          text = text.split('\n').slice(1).join('\n')
          if (!text.trim()) {
            return // Если после удаления заголовка ничего не осталось, пропускаем предложение
          }
        }
      }

      if (!text.trim()) {
        lines.push('')
        return
      }

      if (kind === 'dialogue' && speaker) {
        // Если сменился персонаж, добавляем его имя
        if (currentSpeaker !== speaker) {
          lines.push('')
          lines.push(formatLine(speaker, 'character', { indentCharacter }))
          currentSpeaker = speaker
        }
        // Реплика
        const trimmed = text.trim()
        if (/^\([^)]+\)$/.test(trimmed) || /^\([^)]*$/.test(trimmed)) {
          lines.push(formatLine(text, 'parenthetical', { indentDialogue }))
        } else {
          lines.push(formatLine(text, 'dialogue', { indentDialogue }))
        }
      } else {
        // Действие
        currentSpeaker = null
        const trimmed = text.trim()
        
        // Дополнительная проверка: не добавляем заголовок сцены, если он уже был добавлен
        if (index === 0 && contentStartsWithHeading && headingInContent) {
          const lineNormalized = trimmed.toUpperCase().trim()
          const headingNormalized = headingInContent.toUpperCase().trim()
          if (lineNormalized === headingNormalized || 
              (scene.heading && lineNormalized === scene.heading.toUpperCase().trim())) {
            return // Пропускаем эту строку, так как заголовок уже добавлен
          }
        }
        
        if (/^(ЗК|OFF|ОFF|ВК|ВК\.|ЗК\.|OFF\.|ОFF\.)/i.test(trimmed)) {
          lines.push(formatLine(text, 'transition', {}))
        } else {
          lines.push(formatLine(text, 'action', { indentAction }))
        }
      }
    })
  } else {
    // Fallback: используем content и пытаемся определить типы строк
    let contentLines = scene.content ? scene.content.split('\n') : []
    
    // Убираем заголовок сцены из первой строки content, если он там есть
    if (contentStartsWithHeading && headingInContent && contentLines.length > 0) {
      const firstLine = contentLines[0]?.trim() || ''
      const firstLineNormalized = firstLine.toUpperCase().trim()
      const headingNormalized = headingInContent.toUpperCase().trim()
      if (firstLine && (detectLineType(firstLine, '') === 'scene_heading' || 
          firstLineNormalized === headingNormalized ||
          (scene.heading && firstLineNormalized === scene.heading.toUpperCase().trim()))) {
        // Убираем первую строку
        contentLines = contentLines.slice(1)
      }
    }
    
    let prevLine = ''
    contentLines.forEach((line, index) => {
      const trimmed = line.trim()
      
      // Дополнительная проверка: не добавляем заголовок сцены, если он уже был добавлен
      if (index === 0 && contentStartsWithHeading && headingInContent) {
        const lineNormalized = trimmed.toUpperCase().trim()
        const headingNormalized = headingInContent.toUpperCase().trim()
        if (lineNormalized === headingNormalized || 
            (scene.heading && lineNormalized === scene.heading.toUpperCase().trim())) {
          prevLine = line
          return // Пропускаем эту строку, так как заголовок уже добавлен
        }
      }
      
      const lineType = detectLineType(line, prevLine)
      const formatted = formatLine(line, lineType, { indentAction, indentDialogue, indentCharacter })
      
      if (formatted || lineType === 'empty') {
        lines.push(formatted)
      }
      
      prevLine = line
    })
  }

  // Убираем лишние пустые строки в конце
  while (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop()
  }

  return lines.join('\n')
}

/**
 * Форматирует весь сценарий в российском сценарном формате
 */
export const formatScript = (scenes = [], options = {}) => {
  const {
    sceneSeparator = '\n\n\n', // Три пустые строки между сценами
    indentAction = 0,
    indentDialogue = 25,
    indentCharacter = 20
  } = options

  const formattedScenes = scenes.map(scene => 
    formatScene(scene, { indentAction, indentDialogue, indentCharacter })
  )

  return formattedScenes.join(sceneSeparator)
}

/**
 * Определяет формат файла по имени
 */
export const getFileFormat = (fileName = '') => {
  if (!fileName || typeof fileName !== 'string') {
    console.warn('[getFileFormat] ⚠️ fileName не является строкой:', fileName)
    return 'txt'
  }
  
  const lower = fileName.toLowerCase().trim()
  
  // Проверяем расширение в конце имени файла
  if (lower.endsWith('.docx')) return 'docx'
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.txt')) return 'txt'
  
  // Если расширения нет, пытаемся определить по MIME типу или другим признакам
  // Но по умолчанию возвращаем txt
  console.warn('[getFileFormat] ⚠️ Не удалось определить формат для:', fileName, 'возвращаем txt')
  return 'txt' // По умолчанию txt
}

