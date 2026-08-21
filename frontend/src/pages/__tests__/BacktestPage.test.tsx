import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BacktestPage from '../BacktestPage';

vi.mock('../../components/backtest/BacktestAnalysis', () => ({ default: () => <div>analysis</div> }));
vi.mock('../../components/backtest/StrategyRadar', () => ({ default: () => <div>radar</div> }));
vi.mock('../../components/backtest/MarketMonitor', () => ({ default: () => <div>monitor</div> }));
vi.mock('../../components/backtest/BacktestHistoryView', () => ({ default: () => <div>history</div> }));

describe('BacktestPage', () => {
  it('exposes tab semantics for the strategy workspaces', () => {
    render(<BacktestPage />);

    expect(screen.getByRole('tablist')).toBeInTheDocument();
    const analysisTab = screen.getByRole('tab', { name: /策略回测/ });
    expect(analysisTab).toHaveAttribute('aria-selected', 'true');
    expect(analysisTab).toHaveAttribute('aria-controls', 'panel-backtest');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('analysis');
    expect(screen.getByRole('tabpanel')).not.toHaveAttribute('tabindex');

    fireEvent.click(screen.getByRole('tab', { name: /策略雷达/ }));

    const radarTab = screen.getByRole('tab', { name: /策略雷达/ });
    expect(radarTab).toHaveAttribute('aria-selected', 'true');
    expect(radarTab).toHaveAttribute('aria-controls', 'panel-radar');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'tab-radar');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('radar');
    expect(analysisTab).not.toHaveAttribute('aria-controls');
  });
});
