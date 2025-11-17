import { getCategoryIcon } from '../utils/icons'

const severityBadgeStyles = {
    Severe: 'bg-red-500/20 text-red-200 border border-red-400/40',
    Moderate: 'bg-yellow-500/20 text-yellow-100 border border-yellow-400/40',
    Mild: 'bg-green-500/20 text-green-200 border border-green-400/40',
    None: 'bg-slate-500/20 text-slate-200 border border-slate-400/30'
}

const CategoryScore = ({ reason, isExpanded, onToggle }) => {
    const percentage = Math.round(reason.score * 100)

    // Определяем размер иконки в зависимости от категории
    const iconSize = reason.code === 'profanity' ? 'w-[33px] h-[33px]' : 'w-[30px] h-[30px]'

    return (
        <div className="relative flex items-start">
            {/* Оранжевая вертикальная полоска слева */}
            <div className="absolute left-0 top-0 bottom-0 w-5 bg-wink-orange rounded-[5px]" />

            <button
                onClick={onToggle}
                className="w-full flex items-center justify-between p-4 ml-[30px] bg-[#ffffff1a] rounded-[10px] hover:bg-[#ffffff26] transition-colors"
            >
                <div className="flex items-center gap-4 flex-1">
                    {/* Иконка категории */}
                    <div className={`${iconSize} flex-shrink-0`}>
                        {getCategoryIcon(reason.code)}
                    </div>

                    <div className="flex-1 text-left">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-white font-unbounded font-semibold text-[20px] leading-tight">
                                {reason.label}
                            </h3>
                            <div className="flex items-center gap-2">
                                {reason.severity && (
                                    <span className={`px-2.5 py-1 rounded-full text-[12px] font-poppins ${severityBadgeStyles[reason.severity] ?? severityBadgeStyles.Moderate}`}>
                                        {reason.severity}
                                    </span>
                                )}
                                <span className="text-white font-poppins font-normal text-[18px] leading-tight">
                                    {percentage}%
                                </span>
                            </div>
                        </div>

                        {/* Прогресс-бар */}
                        <div className="relative w-full h-1 bg-wink-gray/30 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-wink-orange rounded-full transition-all duration-500"
                                style={{ width: `${percentage}%` }}
                            />
                        </div>
                    </div>
                </div>

                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className={`text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                >
                    <path d="M6 9l6 6 6-6" />
                </svg>
            </button>
        </div>
    )
}

export default CategoryScore

