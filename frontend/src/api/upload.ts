import type { UploadResult } from '@/types'

export function uploadPdf(
  file: File,
  onProgress: (pct: number) => void,
  onSuccess: (data: UploadResult) => void,
  onError: (msg: string) => void,
): XMLHttpRequest {
  const xhr = new XMLHttpRequest()
  const formData = new FormData()
  formData.append('file', file)

  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      onProgress(Math.round((e.loaded / e.total) * 100))
    }
  })

  xhr.addEventListener('load', () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        const resp = JSON.parse(xhr.responseText)
        if (resp.code === 200) {
          onSuccess(resp.data as UploadResult)
        } else {
          onError(resp.message || '上传失败')
        }
      } catch {
        onError('解析响应失败')
      }
    } else {
      onError('服务器错误: ' + xhr.status)
    }
  })

  xhr.addEventListener('error', () => {
    onError('网络错误，请检查服务是否运行')
  })

  xhr.open('POST', '/api/upload')
  xhr.send(formData)
  return xhr
}
