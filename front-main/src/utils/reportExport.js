// Утилиты для экспорта отчета

export const exportToPDF = (analysisData, scriptText, editedFragments) => {
  // Здесь будет логика экспорта в PDF
  // Можно использовать библиотеку типа jsPDF или pdfkit
  console.log('Exporting to PDF:', { analysisData, scriptText, editedFragments })
  
  // Заглушка - в реальном приложении здесь будет генерация PDF
  alert('Экспорт в PDF будет реализован с использованием библиотеки jsPDF')
}

export const exportToHTML = (analysisData, scriptText, editedFragments) => {
  // Генерация HTML отчета
  const htmlContent = generateHTMLReport(analysisData, scriptText, editedFragments)
  const reportWindow = window.open('', '_blank', 'noopener,noreferrer')
  if (reportWindow) {
    reportWindow.document.write(htmlContent)
    reportWindow.document.close()
  } else {
    console.warn('Не удалось открыть новое окно для отчета. Проверьте настройки блокировщика всплывающих окон.')
  }
}

const generateHTMLReport = (analysisData, scriptText, editedFragments) => {
  const reasonsHTML = analysisData?.reasons?.map(reason => `
    <tr>
      <td>${reason.label}</td>
      <td>${Math.round(reason.score * 100)}%</td>
      <td>${reason.score >= 0.7 ? 'Высокая' : reason.score >= 0.4 ? 'Средняя' : 'Низкая'}</td>
    </tr>
  `).join('') || ''

  const evidenceHTML = analysisData?.evidence?.map((fragment, index) => {
    const reasonLabel = analysisData.reasons?.find(r => r.code === fragment.reason)?.label || fragment.reason
    return `
      <div class="fragment">
        <h4>Фрагмент ${index + 1}: ${reasonLabel}</h4>
        <p class="quote">"${fragment.text}"</p>
        <p class="position">Позиция: ${fragment.start}-${fragment.end}</p>
      </div>
    `
  }).join('') || ''

  return `
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Отчет Wink - ${analysisData?.id || 'Анализ сценария'}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0a0a0a;
      color: #ffffff;
      padding: 40px;
      line-height: 1.6;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    .header {
      background: linear-gradient(45deg, #FE942E 0%, #FD5924 100%);
      padding: 30px;
      border-radius: 20px;
      margin-bottom: 40px;
      text-align: center;
    }
    .header h1 { font-size: 36px; margin-bottom: 10px; }
    .rating {
      display: inline-block;
      background: #FD5924;
      padding: 20px 40px;
      border-radius: 15px;
      font-size: 48px;
      font-weight: bold;
      margin: 20px 0;
    }
    .confidence {
      font-size: 24px;
      margin-top: 10px;
    }
    .section {
      background: rgba(127, 127, 127, 0.2);
      backdrop-filter: blur(10px);
      padding: 30px;
      border-radius: 20px;
      margin-bottom: 30px;
    }
    .section h2 {
      color: #FE942E;
      margin-bottom: 20px;
      font-size: 24px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 20px;
    }
    th, td {
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    th {
      background: rgba(253, 89, 36, 0.2);
      color: #FE942E;
      font-weight: bold;
    }
    .fragment {
      background: rgba(0, 0, 0, 0.3);
      padding: 20px;
      border-radius: 10px;
      margin-bottom: 15px;
      border-left: 4px solid #FD5924;
    }
    .fragment h4 {
      color: #FE942E;
      margin-bottom: 10px;
    }
    .quote {
      font-style: italic;
      margin: 10px 0;
      padding: 10px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 5px;
    }
    .position {
      font-size: 12px;
      color: #888;
      margin-top: 5px;
    }
    .script-preview {
      background: rgba(0, 0, 0, 0.5);
      padding: 20px;
      border-radius: 10px;
      font-family: monospace;
      white-space: pre-wrap;
      max-height: 400px;
      overflow-y: auto;
      margin-top: 20px;
    }
    .footer {
      text-align: center;
      margin-top: 40px;
      padding-top: 20px;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
      color: #888;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>WINK</h1>
      <div class="rating">${analysisData?.age_label || 'N/A'}</div>
      <div class="confidence">Уверенность: ${Math.round((analysisData?.age_confidence || 0) * 100)}%</div>
    </div>

    <div class="section">
      <h2>Анализ по категориям</h2>
      <table>
        <thead>
          <tr>
            <th>Категория</th>
            <th>Оценка</th>
            <th>Серьезность</th>
          </tr>
        </thead>
        <tbody>
          ${reasonsHTML}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>Проблемные фрагменты</h2>
      ${evidenceHTML || '<p>Проблемные фрагменты не найдены.</p>'}
    </div>

    ${analysisData?.legal_refs && analysisData.legal_refs.length > 0 ? `
    <div class="section">
      <h2>Правовые ссылки</h2>
      ${analysisData.legal_refs.map(ref => `
        <div class="fragment">
          <h4>${ref.article}</h4>
          <p>${ref.note}</p>
        </div>
      `).join('')}
    </div>
    ` : ''}

    <div class="section">
      <h2>Текст сценария</h2>
      <div class="script-preview">${scriptText || 'Текст сценария не загружен.'}</div>
    </div>

    <div class="footer">
      <p>Отчет сгенерирован автоматически системой Wink</p>
      <p>Дата: ${new Date().toLocaleString('ru-RU')}</p>
    </div>
  </div>
</body>
</html>
  `
}

