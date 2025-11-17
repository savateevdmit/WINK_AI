import { WinkLogo } from '../utils/icons'

const Header = ({
    onBack,
    children,
    showLogo = true,
    leftExtras = null,
    leftOrientation = 'row'
}) => {
    const positionClass = onBack
        ? 'top-[20px] left-[30px]'
        : 'top-[80px] left-[74px]'
    const hasLeftExtras = Boolean(leftExtras)
    const isColumnLayout = leftOrientation === 'column'
    const baseLeftClass = isColumnLayout ? 'flex flex-col items-start' : 'flex items-center'
    const leftGroupGapClass = isColumnLayout
        ? ''
        : hasLeftExtras && !showLogo
            ? 'gap-[30px]'
            : 'gap-3'
    const backButtonClass = isColumnLayout
        ? 'w-[40px] h-[40px] flex items-center justify-center mt-[10px]'
        : 'flex items-center justify-center'
    const extrasWrapperClass = isColumnLayout && !showLogo ? 'mt-[20px]' : ''

    return (
        <header className={`fixed ${positionClass} z-50 flex items-center justify-between`}>
            <div className={`${baseLeftClass} ${leftGroupGapClass}`}>
                {onBack && (
                    <button
                        onClick={onBack}
                        className={`${backButtonClass} text-white hover:text-wink-orange-light transition-colors`}
                        aria-label="Назад"
                    >
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M19 12H5" />
                            <path d="M12 19l-7-7 7-7" />
                        </svg>
                    </button>
                )}
                {showLogo && <WinkLogo className="w-[180px] h-[47px]" />}
                {isColumnLayout && !showLogo && leftExtras ? (
                    <div className={extrasWrapperClass}>
                        {leftExtras}
                    </div>
                ) : (
                    leftExtras
                )}
            </div>
            {children}
        </header>
    )
}

export default Header

