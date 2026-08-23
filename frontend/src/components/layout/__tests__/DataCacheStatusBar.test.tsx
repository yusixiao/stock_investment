import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import DataCacheStatusBar from '../DataCacheStatusBar';

const status = {
  A: { market: 'A', status: 'loaded', loaded: true, symbols: 10, valuation_count: 1, dividend_count: 1, financial_count: 1, loaded_at: 1, last_date: '2026-08-22', progress: { current: 10, total: 10, phase: 'done' }, error: null, elapsed: 1 },
  HK: { market: 'HK', status: 'idle', loaded: false, symbols: 0, valuation_count: 0, dividend_count: 0, financial_count: 0, loaded_at: 0, last_date: null, progress: { current: 0, total: 0, phase: '' }, error: null, elapsed: 0 },
  US: { market: 'US', status: 'failed', loaded: false, symbols: 0, valuation_count: 0, dividend_count: 0, financial_count: 0, loaded_at: 0, last_date: null, progress: { current: 0, total: 0, phase: '' }, error: 'failed', elapsed: 0 },
} as const;

const statusApi = vi.hoisted(() => ({ status: vi.fn(), load: vi.fn(), invalidate: vi.fn() }));

vi.mock('../../../api/backtestCache', () => ({ backtestCacheApi: statusApi }));
vi.mock('../../backtest/DataCacheModal', () => ({
  default: ({ isOpen }: { isOpen: boolean }) => (isOpen ? <div role="dialog">数据缓存弹窗</div> : null),
}));

describe('DataCacheStatusBar', () => {
  it('opens the cache modal from the top-row load button', async () => {
    statusApi.status.mockResolvedValue(status);
    render(<DataCacheStatusBar />);

    fireEvent.click(await screen.findByRole('button', { name: '打开数据缓存加载弹窗' }));

    expect(screen.getByRole('dialog')).toHaveTextContent('数据缓存弹窗');
  });
});
