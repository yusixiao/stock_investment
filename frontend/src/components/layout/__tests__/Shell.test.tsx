import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { Shell } from '../Shell';

vi.mock('../DataCacheStatusBar', () => ({
  default: () => <div data-testid="data-cache-status-bar" />,
}));

describe('Shell', () => {
  it('renders the backtest platform header without legacy navigation', () => {
    render(
      <MemoryRouter>
        <Shell>
          <div>page content</div>
        </Shell>
      </MemoryRouter>,
    );

    expect(screen.getByText('回测平台')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切换主题' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '退出' })).not.toBeInTheDocument();
    expect(screen.getByTestId('data-cache-status-bar')).toBeInTheDocument();
  });
});
