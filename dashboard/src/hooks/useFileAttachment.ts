import { useRef, useState } from 'react'
import { isImageFile } from '../components/chat/chatUtils'

export function useFileAttachment() {
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  function addFiles(incoming: File[]) {
    if (incoming.length === 0) return
    setFiles((prev) => [...prev, ...incoming])
    const newPreviews = incoming.map((f) =>
      isImageFile(f.name) ? URL.createObjectURL(f) : ''
    )
    setPreviews((prev) => [...prev, ...newPreviews])
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? [])
    addFiles(selected)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handlePaste(e: React.ClipboardEvent) {
    const imageFiles = Array.from(e.clipboardData.items)
      .filter((item) => item.type.startsWith('image/'))
      .map((item, i) => {
        const raw = item.getAsFile()
        if (!raw) return null
        const ext = item.type.split('/')[1]?.replace('jpeg', 'jpg') ?? 'png'
        return new File([raw], `paste_${Date.now()}_${i}.${ext}`, { type: item.type })
      })
      .filter((f): f is File => f !== null)
    if (imageFiles.length === 0) return
    e.preventDefault()
    addFiles(imageFiles)
  }

  function removeFile(idx: number) {
    if (previews[idx]) URL.revokeObjectURL(previews[idx])
    setFiles((prev) => prev.filter((_, i) => i !== idx))
    setPreviews((prev) => prev.filter((_, i) => i !== idx))
  }

  function clearFiles() {
    previews.forEach((p) => { if (p) URL.revokeObjectURL(p) })
    setFiles([])
    setPreviews([])
  }

  return { files, previews, fileInputRef, addFiles, handleFileChange, handlePaste, removeFile, clearFiles }
}
