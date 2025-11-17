import { HistoryIcon } from '../utils/icons'

const HistoryButton = ({ onClick, className = '', style }) => {
    return (
        <button
            onClick={onClick}
            className={`w-[40px] h-[40px] flex items-center justify-center hover:opacity-80 transition-opacity ${className}`.trim()}
            style={style}
            aria-label="Показать историю"
        >
            <HistoryIcon isOrange={false} className="w-[40px] h-[40px]" />
        </button>
    )
}

export default HistoryButton

