import { DocumentsIcon, HistoryIcon } from '../utils/icons'

const HistorySidebar = ({ history, onSelect, isOpen, onClose }) => {
    const getRatingColor = (rating) => {
        const colors = {
            '0+': '#00ff00',
            '6+': '#ffc287',
            '12+': '#fe942e',
            '16+': '#fe942e',
            '18+': '#ff6600'
        }
        return colors[rating] || '#fe942e'
    }

    return (
        <aside
            className="fixed right-0 top-0 h-screen w-[340px] z-40 transition-transform duration-300"
            style={{
                transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
                pointerEvents: isOpen ? 'auto' : 'none'
            }}
            aria-label="Панель истории запросов"
        >
            <div className="relative h-full" style={{ backgroundColor: 'rgba(77, 77, 77, 0.5)', backdropFilter: 'blur(50px)' }}>
                <div className="sticky top-0 px-[30px] pt-[88px] pb-[15px] bg-transparent">
                    <div className="flex items-center gap-3 text-white/80 text-[14px] font-poppins font-medium leading-tight">
                        <button
                            onClick={onClose}
                            className="flex items-center justify-center hover:opacity-80 transition-opacity"
                            aria-label="Закрыть историю"
                        >
                            <HistoryIcon isOrange={true} className="w-[40px] h-[40px]" />
                        </button>
                        <span>История запросов</span>
                    </div>
                </div>

                <div className="px-[30px] mt-[15px] pb-[80px] overflow-y-scroll space-y-[10px] ScrollbarHide box-border" style={{ height: 'calc(100% - 150px)' }}>
                    {history.length === 0 ? (
                        <p className="text-white/50 text-[12px] font-poppins font-normal">История пуста</p>
                    ) : (
                        history.map((item, index) => (
                            <article
                                key={item.id || index}
                                onClick={() => onSelect(item)}
                                className="w-[280px] h-[73px] flex items-center gap-3 bg-[#00000080] rounded-[10px] border border-[#373737] cursor-pointer hover:bg-[#000000a0] transition-colors px-4"
                            >
                                <DocumentsIcon className="w-[22px] h-8 flex-shrink-0" />

                                <div className="flex-1 flex flex-col gap-1 min-w-0">
                                    <div className="font-poppins font-bold text-[12px] leading-normal truncate text-white">
                                        {item.fileName || `Документ ${index + 1}`}
                                    </div>
                                    <time className="font-poppins font-light text-[12px] leading-normal text-white/80">
                                        {item.date || new Date().toLocaleDateString('ru-RU')}
                                    </time>
                                </div>

                                <div className="w-[25px] h-[25px] rounded-[5px] flex items-center justify-center flex-shrink-0"
                                    style={{ backgroundColor: getRatingColor(item.ageRating || item.age_label) }}
                                    aria-label={`Возрастной рейтинг ${item.ageRating || item.age_label}`}
                                >
                                    <div className="font-poppins font-bold text-[12px] leading-none text-white">
                                        {item.ageRating || item.age_label || 'N/A'}
                                    </div>
                                </div>
                            </article>
                        ))
                    )}
                </div>
            </div>
        </aside>
    )
}

export default HistorySidebar
