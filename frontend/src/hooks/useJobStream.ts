import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Job, JobProgress } from '../api/types'

const TERMINAL = new Set(['done', 'error', 'canceled'])

/**
 * 작업 하나를 SSE 로 따라간다. 세션 쿠키가 같은 출처로 실려가므로 인증이 그대로 걸린다.
 * 완료/실패하면 서버가 스트림을 닫고, EventSource 의 자동 재연결도 여기서 끊는다.
 */
export function useJobStream(initial: Job): Job {
  const [job, setJob] = useState<Job>(initial)

  useEffect(() => {
    if (TERMINAL.has(initial.status)) {
      setJob(initial)
      return
    }

    const source = new EventSource(`/api/jobs/${initial.id}/events`)
    let closed = false

    const close = () => {
      if (!closed) {
        closed = true
        source.close()
      }
    }

    source.addEventListener('state', (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as { job: Job }
      setJob(payload.job)
      if (TERMINAL.has(payload.job.status)) close()
    })

    source.addEventListener('progress', (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as {
        progress: JobProgress
      }
      setJob((current) => ({ ...current, progress: payload.progress }))
    })

    source.onerror = () => {
      // 스트림이 끊기면 최종 상태를 한 번 직접 확인한다 (완료 후 정상 종료 포함)
      close()
      api.getJob(initial.id).then(setJob, () => undefined)
    }

    return close
  }, [initial])

  return job
}
