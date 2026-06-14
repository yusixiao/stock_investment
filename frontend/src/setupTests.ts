import '@testing-library/jest-dom';

// jsdom 在本项目的 vitest 环境下未完整实现 Storage(localStorage.getItem 缺失),
// 这里注入一个最小内存版 localStorage / sessionStorage,供 zustand store 初始化等使用。
function createStorageMock(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
    get length() {
      return Object.keys(store).length;
    },
  } as Storage;
}

Object.defineProperty(globalThis, 'localStorage', {
  writable: true,
  value: createStorageMock(),
});

Object.defineProperty(globalThis, 'sessionStorage', {
  writable: true,
  value: createStorageMock(),
});

class IntersectionObserverMock implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = '';
  readonly thresholds = [0];

  disconnect() {}

  observe() {}

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  unobserve() {}
}

Object.defineProperty(globalThis, 'IntersectionObserver', {
  writable: true,
  value: IntersectionObserverMock,
});
