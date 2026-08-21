import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import DataCacheModal from '../DataCacheModal';

const { invalidate } = vi.hoisted(() => ({ invalidate: vi.fn() }));

vi.mock('../../../api/backtestCache', () => ({
  backtestCacheApi: {
    load: vi.fn(),
    invalidate,
  },
}));

describe('DataCacheModal', () => {
  it('confirms before clearing loaded market cache', () => {
    render(
      <DataCacheModal
        isOpen
        status={{
          A: { status: 'loaded', loaded: true, symbols: 10, valuation_count: 1, dividend_count: 1, financial_count: 1 },
          HK: { status: 'idle', loaded: false, symbols: 0, valuation_count: 0, dividend_count: 0, financial_count: 0 },
          US: { status: 'idle', loaded: false, symbols: 0, valuation_count: 0, dividend_count: 0, financial_count: 0 },
        }}
        onClose={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '清除缓存' }));
    expect(screen.getByText(/确认清除A 股缓存吗/)).toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '确认清除' }));
    expect(invalidate).toHaveBeenCalledWith('A');
  });
});
