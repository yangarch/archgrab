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
