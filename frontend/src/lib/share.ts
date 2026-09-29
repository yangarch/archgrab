import type { JobFile } from '../api/types'

/**
 * 웹에서 iOS 사진 앱에 직접 쓰는 API 는 없다. 대신 공유 시트를 열면 거기에
 * "비디오 저장" / "이미지 저장" 항목이 있어 한 번의 탭으로 갤러리에 들어간다.
 *
 * 제약이 둘 있다:
 *  1. 파일 전체가 브라우저 메모리를 거친다. 큰 영상은 탭이 죽을 수 있어
 *     크기로 걸러야 한다.
 *  2. iOS 는 사용자 탭 직후에만 공유 시트를 허용한다. 파일을 받아오는 사이
 *     그 권한이 풀리면 NotAllowedError 가 난다.
 */

/** 이 크기를 넘으면 공유를 권하지 않는다.
 *
 * 실측값이 아니라 보수적인 판단이다 — 기기 메모리에 따라 다르고 저사양
 * 아이폰에서 더 낮을 수 있다. 넘는 파일은 기존 다운로드로 안내한다. */
export const SHARE_SIZE_LIMIT = 100 * 1024 * 1024

export type ShareOutcome =
  | 'shared'
  | 'cancelled'
  | 'retry'        // 제스처 권한이 풀렸다 — 다시 누르면 캐시 덕에 대개 성공한다
  | 'too-large'
  | 'unsupported'
  | 'failed'

/* Navigator 를 확장하지 않는다 — 최신 DOM 타입에는 canShare 가 필수로
   선언돼 있어 선택적으로 넓히면 tsc 가 거부한다. 런타임에는 없을 수 있으므로
   구조적 타입으로 본다. */
type MaybeFileShare = {
  share?: (data: ShareData) => Promise<void>
  canShare?: (data?: ShareData) => boolean
}

const fileShare = () => navigator as unknown as MaybeFileShare

/** 파일 공유를 지원하는 환경인가.
 *
 * 데스크톱 크롬은 navigator.share 가 있어도 **파일**은 공유하지 못한다.
 * 그래서 share 존재 여부가 아니라 canShare({files}) 로 확인해야 한다 —
 * 안 되는 곳에 버튼만 띄우고 눌러도 아무 일 없으면 더 나쁘다. */
export function canShareFiles(): boolean {
  const nav = fileShare()
  if (typeof nav.share !== 'function' || typeof nav.canShare !== 'function') return false
  try {
    const probe = new File([new Blob([new Uint8Array(1)])], 'probe.jpg', { type: 'image/jpeg' })
    return nav.canShare({ files: [probe] }) === true
  } catch {
    return false
  }
}

export function isShareable(file: JobFile): boolean {
  // zip 은 사진 앱이 받지 않는다 — 공유해도 갤러리로 가지 않는다
  if (file.name.endsWith('.zip')) return false
  return file.size <= SHARE_SIZE_LIMIT && canShareFiles()
}

export async function shareFile(file: JobFile): Promise<ShareOutcome> {
  if (!canShareFiles()) return 'unsupported'
  if (file.size > SHARE_SIZE_LIMIT) return 'too-large'

  let payload: File
  try {
    const response = await fetch(`/api/files/${file.token}`, { credentials: 'same-origin' })
    if (!response.ok) return 'failed'
    const blob = await response.blob()
    payload = new File([blob], file.name, { type: file.content_type || blob.type })
  } catch {
    return 'failed'
  }

  try {
    await fileShare().share!({ files: [payload] })
    return 'shared'
  } catch (error) {
    const name = (error as { name?: string })?.name
    if (name === 'AbortError') return 'cancelled'
    // 파일을 받는 동안 탭 권한이 풀린 경우. 이제 브라우저 캐시에 있으니
    // 다시 누르면 즉시 공유된다.
    if (name === 'NotAllowedError') return 'retry'
    return 'failed'
  }
}
