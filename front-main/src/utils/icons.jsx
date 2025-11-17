// Импорты PNG иконок
// В Vite можно использовать обычные импорты для изображений
// Если файла нет - используем SVG fallback

// Иконки которые есть в папке
import cough1Img from '../assets/icons/cough1.png'
import sword1Img from '../assets/icons/free-icon-sword-2230033-1.png'
import editIconImg from '../assets/icons/vector-5.png'
import aiIconImg from '../assets/icons/vector-6.png'
import closeIconImg from '../assets/icons/close.png'
import uploadDocIconImg from '../assets/icons/apload_doc.png'
import documentsIconImg from '../assets/icons/documents.png'
import historyOrangeIconImg from '../assets/icons/history_orange.png'
import historyWhiteIconImg from '../assets/icons/history_white.png'
import winkLogoImg from '../assets/icons/wink-logo-black-1-png-1.png'
import photoBackImg from '../assets/icons/photo_background.png'
import galochkaImg from '../assets/icons/galochka.png'
import uploadIconImg from '../assets/icons/upload.png'

// Иконки которых может не быть - используем null и SVG fallback
let group18Img = null // Если файл group18.png добавите - раскомментируйте: import group18Img from '../assets/icons/group18.png'

// Если какие-то иконки не найдены, используем SVG заглушки
const getCategoryIcon = (code) => {
    const icons = {
        violence: group18Img ? (
            <img
                src={group18Img}
                alt="Насилие"
                className="w-[30px] h-[30px] object-contain"
            />
        ) : (
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" className="text-wink-orange">
                <path d="M12 2C8.5 2 6 4.5 6 8c0 2 1 4 2 5v7h8v-7c1-1 2-3 2-5 0-3.5-2.5-6-6-6z" stroke="currentColor" strokeWidth="2" fill="currentColor" />
                <path d="M9 12h6M9 15h6" stroke="currentColor" strokeWidth="1.5" />
            </svg>
        ),
        profanity: (
            <img
                src={cough1Img}
                alt="Мат"
                className="w-[33px] h-[33px] object-contain"
            />
        ),
        alcohol: (
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" className="text-wink-orange">
                <rect x="8" y="4" width="8" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
                <path d="M10 8h4M10 12h4M10 16h4" stroke="currentColor" strokeWidth="1.5" />
            </svg>
        ),
        scary: (
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" className="text-wink-orange">
                <path d="M12 2a8 8 0 0 0-8 8c0 4.5 8 12 8 12s8-7.5 8-12a8 8 0 0 0-8-8z" stroke="currentColor" strokeWidth="2" />
                <circle cx="12" cy="10" r="2" fill="currentColor" />
                <path d="M9 13h6" stroke="currentColor" strokeWidth="2" />
            </svg>
        ),
        erotic: (
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" className="text-wink-orange">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
                <path d="M12 8v8M8 12h8" stroke="currentColor" strokeWidth="2" />
            </svg>
        )
    }

    return icons[code] || icons.violence
}

export const getFragmentIcon = (reason) => {
    // Иконка для проблемного фрагмента в зависимости от категории
    if (reason === 'violence') {
        return (
            <div className="relative w-[18px] h-[18px]">
                <img
                    src={sword1Img}
                    alt="Насилие"
                    className="absolute top-0 left-0 w-[17px] h-[17px] object-cover"
                />
            </div>
        )
    }
    if (reason === 'profanity') {
        return (
            <div className="relative w-[18px] h-[18px]">
                <img
                    src={cough1Img}
                    alt="Мат"
                    className="absolute top-0 left-0 w-[17px] h-[17px] object-cover"
                />
            </div>
        )
    }
    return getCategoryIcon(reason)
}

export const EditIcon = ({ className = "w-[14.59px] h-[14.59px]" }) => (
    <img
        src={editIconImg}
        alt="Редактировать"
        className={className}
    />
)

export const AIIcon = ({ className = "w-[18px] h-[17px]" }) => (
    <div className={`relative ${className}`}>
        <img
            src={aiIconImg}
            alt="AI"
            className="absolute inset-0 w-full h-full object-contain"
        />
    </div>
)

export const CloseIcon = ({ className = "w-[19px] h-[19px]" }) => (
    <img
        src={closeIconImg}
        alt="Закрыть"
        className={className}
    />
)

export const CheckIcon = ({ className = "w-[23px] h-[23px]" }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M20 6L9 17l-5-5" />
    </svg>
)

export const UploadDocIcon = ({ className = "w-[133.5px] h-[167px]" }) => (
    <img
        src={uploadDocIconImg}
        alt="Загрузить документ"
        className={className}
    />
)

export const DocumentsIcon = ({ className = "w-[22px] h-8" }) => (
    <img
        src={documentsIconImg}
        alt="Документ"
        className={className}
    />
)

export const UploadIcon = ({ className = "w-[22px] h-[22px]" }) => (
    <img
        src={uploadIconImg}
        alt="Загрузить"
        className={className}
    />
)

export const HistoryIcon = ({ isOrange = false, className = "w-5 h-5" }) => {
    const iconSrc = isOrange ? historyOrangeIconImg : historyWhiteIconImg
    return (
        <img
            src={iconSrc}
            alt="История"
            className={className}
        />
    )
}

export const WinkLogo = ({ className = "w-[180px] h-[47px]" }) => (
    <img
        src={winkLogoImg}
        alt="Wink"
        className={className}
    />
)

export const ConfidenceMarkIcon = ({ className = "w-[20px] h-[20px]" }) => (
    <img src={galochkaImg} alt="Уверенность" className={className} />
)

// Экспорт фонового изображения
export { photoBackImg }

// Экспорт для использования в компонентах
export { getCategoryIcon }

