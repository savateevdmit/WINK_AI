import { useState, useRef, useMemo, useCallback } from 'react'
import HistorySidebar from './HistorySidebar'
import HistoryButton from './HistoryButton'
import { UploadDocIcon, CloseIcon, WinkLogo, photoBackImg } from '../utils/icons'

const UploadPage = ({ onFileUpload, history, onHistorySelect }) => {
    const [selectedFile, setSelectedFile] = useState(null)
    const [isDragging, setIsDragging] = useState(false)
    const [isHistoryOpen, setIsHistoryOpen] = useState(false)
    const [errorMessage, setErrorMessage] = useState('')
    const fileInputRef = useRef(null)

    const validTypes = useMemo(() => ([
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]), [])

    const isValidFile = useCallback((file) => {
        if (!file) return false
        if (validTypes.includes(file.type)) return true
        const extension = file.name?.split('.').pop()?.toLowerCase()
        return extension ? ['pdf', 'docx'].includes(extension) : false
    }, [validTypes])

    const handleFileAccepted = (file) => {
        setSelectedFile(file)
        setErrorMessage('')
    }

    const handleFileRejected = () => {
        setSelectedFile(null)
        setErrorMessage('Поддерживаются только файлы .pdf, .docx')
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const handleFileSelect = (event) => {
        const file = event.target.files?.[0]
        if (isValidFile(file)) {
            handleFileAccepted(file)
        } else if (file) {
            handleFileRejected()
        }
    }

    const handleDragOver = (event) => {
        event.preventDefault()
        setIsDragging(true)
    }

    const handleDragLeave = (event) => {
        event.preventDefault()
        setIsDragging(false)
    }

    const handleDrop = (event) => {
        event.preventDefault()
        setIsDragging(false)
        const file = event.dataTransfer.files?.[0]
        if (isValidFile(file)) {
            handleFileAccepted(file)
        } else if (file) {
            handleFileRejected()
        }
    }

    const triggerFileDialog = () => {
        fileInputRef.current?.click()
    }

    const handleRemoveFile = () => {
        setSelectedFile(null)
        setErrorMessage('')
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const handleAnalyze = () => {
        if (selectedFile) {
            onFileUpload(selectedFile)
        } else {
            triggerFileDialog()
        }
    }

    const handleHistorySelect = (item) => {
        if (onHistorySelect) {
            onHistorySelect(item)
        }
        setIsHistoryOpen(false)
    }

    const layoutStyle = {
        position: 'absolute',
        top: '150px',
        left: '70px',
        right: isHistoryOpen ? '390px' : '70px',
        bottom: '80px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'stretch'
    }

    const logoStyle = {
        position: 'absolute',
        top: '80px',
        left: '70px'
    }

    const historyButtonStyle = {
        position: 'absolute',
        top: '88px',
        right: isHistoryOpen ? '390px' : '70px'
    }

    return (
        <div
            className="min-h-screen bg-wink-black"
            style={{
                width: '100%',
                maxWidth: '100vw',
                overflow: 'hidden',
                backgroundImage: `url(${photoBackImg})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                backgroundRepeat: 'no-repeat'
            }}
        >
            <div className="relative mx-auto h-screen w-full max-w-[1440px]">
                <div style={logoStyle}>
                    <WinkLogo className="w-[180px] h-[47px]" />
                </div>

                {!isHistoryOpen && (
                    <HistoryButton
                        onClick={() => setIsHistoryOpen(true)}
                        style={historyButtonStyle}
                    />
                )}

                <HistorySidebar
                    history={history}
                    onSelect={handleHistorySelect}
                    isOpen={isHistoryOpen}
                    onClose={() => setIsHistoryOpen(false)}
                />

                <div style={layoutStyle}>
                    <div className="flex flex-col gap-6 w-full" style={{ width: '100%', height: '100%' }}>
                        <section
                            className={`glass-effect flex flex-col gap-6 px-16 py-24 w-full min-h-[420px] items-center justify-center rounded-[20px] transition-all cursor-pointer ${isDragging ? 'ring-2 ring-wink-orange-light ring-opacity-50' : ''}`}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                            onClick={triggerFileDialog}
                            role="region"
                            aria-label="Область загрузки файла"
                            style={{ flex: 1 }}
                        >
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept=".pdf,.docx"
                                onChange={handleFileSelect}
                                className="hidden"
                                aria-label="Выбрать файл"
                            />
                            {selectedFile ? (
                                <div className="flex flex-col items-center gap-4">
                                    <UploadDocIcon />
                                    <div className="flex items-center gap-3">
                                        <button
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                handleRemoveFile()
                                            }}
                                            className="text-wink-orange hover:text-wink-orange-light transition-colors"
                                            aria-label="Удалить файл"
                                        >
                                            <CloseIcon className="w-5 h-5" />
                                        </button>
                                        <span className="text-white font-poppins font-extrabold text-[20px] leading-tight">{selectedFile.name}</span>
                                    </div>
                                </div>
                            ) : (
                                <>
                                    <UploadDocIcon />
                                    <div className="text-center">
                                        <p className="text-[#ffffffcc] text-[12px] font-poppins font-normal leading-relaxed">
                                            Поддерживаются форматы: pdf, docx
                                        </p>
                                        <p className="text-white font-poppins font-extrabold text-[12px] leading-relaxed mt-1">
                                            Выберите файл или перетащите его сюда
                                        </p>
                                    </div>
                                </>
                            )}
                            {errorMessage && (
                                <p className="text-wink-orange text-[12px] font-poppins mt-4">
                                    {errorMessage}
                                </p>
                            )}
                        </section>

                        <button
                            onClick={handleAnalyze}
                            className="h-[100px] gradient-orange flex items-center justify-center rounded-[20px] hover:opacity-90 transition-opacity"
                            style={{ width: '100%' }}
                            aria-label={selectedFile ? 'Анализировать файл' : 'Выбрать файл для загрузки'}
                        >
                            <span className="text-white font-unbounded font-bold text-[36px] leading-none tracking-[0.08em] uppercase">
                                {selectedFile ? 'АНАЛИЗИРОВАТЬ' : 'ВЫБРАТЬ ФАЙЛ'}
                            </span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default UploadPage
