import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./pages/BacktestPage', () => ({
  default: () => (
    <div role="tablist" aria-label="回测工作区标签">
      <button type="button" role="tab">策略回测</button>
      <button type="button" role="tab">策略雷达</button>
      <button type="button" role="tab">盘面监控</button>
      <button type="button" role="tab">历史记录</button>
    </div>
  ),
}));

vi.mock('./components/layout/DataCacheStatusBar', () => ({
  default: () => <div data-testid="data-cache-status-bar" />,
}));

const renderAppAt = (path: string) =>
  (() => {
    window.history.pushState({}, '', path);
    return render(<App />);
  })();

describe('App', () => {
  it('redirects the root route to the backtest workbench', async () => {
    renderAppAt('/');

    expect(await screen.findByRole('tab', { name: '策略回测' })).toBeInTheDocument();
  });

  it('redirects unknown routes and does not render removed product navigation', async () => {
    renderAppAt('/unknown');

    expect(await screen.findByRole('tab', { name: '策略回测' })).toBeInTheDocument();
    expect(screen.queryByText('首页')).not.toBeInTheDocument();
    expect(screen.queryByText('持仓')).not.toBeInTheDocument();
    expect(screen.queryByText('问股')).not.toBeInTheDocument();
    expect(screen.queryByText('设置')).not.toBeInTheDocument();
    expect(screen.queryByText('退出')).not.toBeInTheDocument();
  });

  it('keeps the data cache status bar mounted in the workbench shell', () => {
    renderAppAt('/backtest');

    expect(screen.getByTestId('data-cache-status-bar')).toBeInTheDocument();
  });
});
