/**
 * Форматирует markdown-текст в HTML
 * Обрабатывает:
 * - \n -> переносы строк
 * - **text** -> жирный текст
 * - - item -> маркированный список
 * - (e.g., ...) -> примеры
 */
export const formatMarkdown = (text) => {
  if (!text || typeof text !== 'string') return ''

  // Заменяем \n на реальные переносы строк
  let formatted = text.replace(/\\n/g, '\n')

  // Разбиваем на строки для обработки
  const lines = formatted.split('\n')
  const result = []
  let inList = false
  let listItems = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    
    if (!line) {
      // Пустая строка - закрываем список, если он был открыт
      if (inList && listItems.length > 0) {
        result.push(`<ul class="list-disc list-inside space-y-1 my-2 ml-4">${listItems.join('')}</ul>`)
        listItems = []
        inList = false
      }
      continue
    }

    // Проверяем, является ли строка элементом списка
    const listMatch = line.match(/^[-–•]\s+(.+)$/)
    if (listMatch) {
      // Это элемент списка
      if (!inList) {
        inList = true
      }
      // Обрабатываем содержимое элемента списка
      let itemContent = listMatch[1]
      // Обрабатываем жирный текст в элементе списка
      itemContent = itemContent.replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
      // Обрабатываем примеры
      itemContent = itemContent.replace(/\(e\.g\.,\s*(.+?)\)/gi, '<span class="text-white/70 italic">(например, $1)</span>')
      listItems.push(`<li class="mb-1">${itemContent}</li>`)
    } else {
      // Это не элемент списка
      if (inList && listItems.length > 0) {
        // Закрываем список
        result.push(`<ul class="list-disc list-inside space-y-1 my-2 ml-4">${listItems.join('')}</ul>`)
        listItems = []
        inList = false
      }
      
      // Обрабатываем обычную строку
      let processedLine = line
      
      // Обрабатываем жирный текст **text**
      processedLine = processedLine.replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
      
      // Обрабатываем курсив *text* (но не **text**)
      processedLine = processedLine.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, '<em class="italic">$1</em>')
      
      // Обрабатываем примеры (e.g., ...)
      processedLine = processedLine.replace(/\(e\.g\.,\s*(.+?)\)/gi, '<span class="text-white/70 italic">(например, $1)</span>')
      
      // Если строка заканчивается на ":" и начинается с заглавной буквы, делаем её заголовком
      if (/^[A-Z][^:]+:$/.test(processedLine)) {
        result.push(`<p class="font-semibold text-white mb-2 mt-3">${processedLine}</p>`)
      } else {
        result.push(`<p class="mb-2">${processedLine}</p>`)
      }
    }
  }

  // Закрываем список, если он остался открытым
  if (inList && listItems.length > 0) {
    result.push(`<ul class="list-disc list-inside space-y-1 my-2 ml-4">${listItems.join('')}</ul>`)
  }

  return result.join('')
}

// Компонент MarkdownContent удален - используйте formatMarkdown напрямую в компонентах

