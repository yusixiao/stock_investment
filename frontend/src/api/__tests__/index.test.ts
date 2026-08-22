import { describe, expect, it, vi } from 'vitest';

const { rejectResponse, useInterceptor } = vi.hoisted(() => ({
  rejectResponse: vi.fn(),
  useInterceptor: vi.fn(),
}));

vi.mock('axios', () => ({
  default: {
    create: () => ({
      interceptors: {
        response: {
          use: useInterceptor.mockImplementation((_resolve, reject) => {
            rejectResponse.mockImplementation(reject);
          }),
        },
      },
    }),
  },
}));

vi.mock('../error', () => ({
  attachParsedApiError: vi.fn(),
}));

import '../index';

describe('api client', () => {
  it('keeps 401 errors in the API flow without navigating to the removed login page', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { pathname: '/', search: '', assign },
    });
    const error = { response: { status: 401 } };

    await expect(rejectResponse(error)).rejects.toBe(error);

    expect(assign).not.toHaveBeenCalled();
  });
});
