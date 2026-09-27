import type { MediaInfo, MediaItem } from '../api/types'

export function makeItem(
  id: string,
  type: 'image' | 'video' = 'image',
  overrides: Partial<MediaItem> = {},
): MediaItem {
  const ext = type === 'video' ? 'mp4' : 'jpg'
  return {
    id,
    index: Number(id),
    type,
    thumbnail: type === 'image' ? `/api/thumb/token-${id}` : null,
    width: 1080,
    height: 1350,
    formats: [
      {
        id: 'original',
        ext,
        width: 1080,
        height: 1350,
        note: '원본',
        label: `1080×1350 · ${ext} · 원본`,
      },
    ],
    ...overrides,
  }
}

export function makeInfo(items: MediaItem[], overrides: Partial<MediaInfo> = {}): MediaInfo {
  return {
    platform: 'instagram',
    kind: 'post',
    source_url: 'https://www.instagram.com/p/AAA/',
    key: 'AAA',
    title: '캡션',
    uploader: 'someone',
    items,
    engine: 'instagram-web',
    used_cookies: false,
    missing_items: 0,
    ...overrides,
  }
}

/** 유튜브처럼 화질이 여러 개인 항목 */
export function makeMultiFormatItem(id = '0'): MediaItem {
  const spec: Array<[string, number, string, string]> = [
    ['401', 2160, 'mp4', '3840×2160 · mp4 · ~232.5MB · 음성 합침'],
    ['137', 1080, 'mp4', '1920×1080 · mp4 · ~80.5MB · 음성 합침'],
    ['134', 360, 'mp4', '640×360 · mp4 · ~11.3MB · 음성 합침'],
    ['140', 0, 'm4a', 'm4a · 3.3MB · 오디오만'],
  ]
  return {
    id,
    index: Number(id),
    type: 'video',
    thumbnail: null,
    width: 3840,
    height: 2160,
    formats: spec.map(([fid, height, ext, label]) => ({
      id: fid,
      ext,
      width: height ? (height * 16) / 9 : null,
      height: height || null,
      label,
      needs_mux: ext !== 'm4a',
    })),
  }
}
