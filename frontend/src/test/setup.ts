import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

// globals:true 를 쓰지 않으면 Testing Library 의 자동 cleanup 이 등록되지 않는다.
// 없으면 렌더가 테스트 간에 누적되어 쿼리가 중복 요소를 찾는다.
afterEach(cleanup)
