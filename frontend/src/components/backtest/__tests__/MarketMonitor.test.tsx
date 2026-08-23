import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MarketMonitor from '../MarketMonitor';

const monitoringApi = vi.hoisted(() => ({
  getCenter: vi.fn(),
  listStrategyMonitors: vi.fn(),
  createStrategyMonitor: vi.fn(),
  runStrategyMonitor: vi.fn(),
  listStrategyRuns: vi.fn(),
  deleteStrategyMonitor: vi.fn(),
  listStockMonitors: vi.fn(),
  createStockMonitor: vi.fn(),
  pauseStockMonitor: vi.fn(),
  resumeStockMonitor: vi.fn(),
  listStockEvents: vi.fn(),
  deleteStockMonitor: vi.fn(),
}));
const backtestEngineApi = vi.hoisted(() => ({ listStrategies: vi.fn() }));

vi.mock('../../../api/monitoring', () => ({ monitoringApi }));
vi.mock('../../../api/backtestEngine', () => ({ backtestEngineApi }));

const emptySnapshot = { strategies: [], strategy_runs: {}, stocks: [], stock_events: {}, generated_at: '' };

describe('MarketMonitor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    monitoringApi.getCenter.mockResolvedValue(emptySnapshot);
    backtestEngineApi.listStrategies.mockResolvedValue([{ filepath: 'strategies/value.py', className: 'ValueStrategy', name: '价值策略', strategyType: 'strategy', frequency: 'daily', frequencyOverridable: true, params: {} }]);
  });

  it('renders independent strategy and stock sections without portfolio account controls', async () => {
    render(<MarketMonitor />);

    expect(await screen.findByRole('heading', { name: '策略监控' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '股票价格监控' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '添加策略监控' }));
    fireEvent.click(screen.getByRole('button', { name: '添加股票监控' }));
    expect(screen.getByLabelText('策略名称')).toBeInTheDocument();
    expect(screen.getByLabelText('股票代码')).toBeInTheDocument();
    expect(screen.queryByLabelText(/账户|持仓/)).not.toBeInTheDocument();
    expect(screen.queryByText(/从策略选择股票/)).not.toBeInTheDocument();
  });

  it('loads the monitor center snapshot and binds aggregate errors to both sections', async () => {
    let rejectCenter!: (reason: unknown) => void;
    monitoringApi.getCenter.mockReturnValueOnce(new Promise((_, reject) => { rejectCenter = reject; }));

    render(<MarketMonitor />);

    await waitFor(() => {
      expect(monitoringApi.getCenter).toHaveBeenCalledTimes(1);
      expect(backtestEngineApi.listStrategies).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText('加载策略监控…')).toBeInTheDocument();
    expect(screen.getByText('加载股票监控…')).toBeInTheDocument();
    rejectCenter(new Error('monitor center unavailable'));
    expect(await screen.findByText('策略监控加载失败，请稍后重试')).toBeInTheDocument();
    expect(screen.getByText('股票价格监控加载失败，请稍后重试')).toBeInTheDocument();

    expect(monitoringApi.getCenter).toHaveBeenCalledTimes(1);
    expect(backtestEngineApi.listStrategies).toHaveBeenCalledTimes(1);
  });

  it('refreshes only strategy and stock monitor lists', async () => {
    render(<MarketMonitor />);
    await screen.findByRole('heading', { name: '策略监控' });
    fireEvent.click(screen.getByRole('button', { name: '刷新监控' }));

    await waitFor(() => expect(monitoringApi.getCenter).toHaveBeenCalledTimes(2));
    expect(backtestEngineApi.listStrategies).toHaveBeenCalledTimes(1);
  });

  it('requires market, symbol, and a positive threshold before creating stock monitor', async () => {
    render(<MarketMonitor />);
    await screen.findByRole('heading', { name: '股票价格监控' });

    fireEvent.click(screen.getByRole('button', { name: '添加股票监控' }));
    fireEvent.click(screen.getByRole('button', { name: '保存股票监控' }));

    expect((await screen.findAllByRole('alert')).find((element) => element.textContent === '请选择市场')).toBeInTheDocument();
    expect(screen.getByText('请输入股票代码')).toBeInTheDocument();
    expect(screen.getByText('请输入正数阈值')).toBeInTheDocument();
    expect(monitoringApi.createStockMonitor).not.toHaveBeenCalled();
  });

  it('shows stock creation failures as action errors without replacing the load error', async () => {
    monitoringApi.createStockMonitor.mockRejectedValueOnce(new Error('create failed'));
    render(<MarketMonitor />);
    await screen.findByRole('heading', { name: '股票价格监控' });

    fireEvent.click(screen.getByRole('button', { name: '添加股票监控' }));
    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: '600000' } });
    fireEvent.change(screen.getByLabelText('阈值价格'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('市场'), { target: { value: 'A' } });
    fireEvent.click(screen.getByRole('button', { name: '保存股票监控' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('股票价格监控创建失败，请检查配置');
    expect(screen.queryByText('股票价格监控加载失败，请稍后重试')).not.toBeInTheDocument();
  });

  it('shows stock state and confirms pause and delete actions', async () => {
    monitoringApi.getCenter.mockResolvedValue({
      ...emptySnapshot,
      stocks: [{
        id: 2, market: 'HK', symbol: '00005', name: '腾讯', threshold_price: 100,
        is_active: true, state: 'armed', last_price: 98, last_price_date: '2026-08-21',
        last_triggered_at: null, created_at: '2026-08-20', updated_at: '2026-08-21',
      }],
    });
    monitoringApi.pauseStockMonitor.mockResolvedValue({ id: 2, state: 'paused' });
    render(<MarketMonitor />);

    expect(await screen.findByText('00005')).toBeInTheDocument();
    expect(screen.getByText('当前价 98')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '暂停 00005' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(monitoringApi.pauseStockMonitor).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认' }));
    await waitFor(() => expect(monitoringApi.pauseStockMonitor).toHaveBeenCalledWith(2));
  });

  it('shows strategy run history separately from stock price events', async () => {
    monitoringApi.getCenter.mockResolvedValue({ ...emptySnapshot,
      strategies: [{ id: 1, name: '价值策略', strategy_class: 'ValueStrategy', filepath: 'value.py', params: {}, market: 'A', frequency: 'daily', symbols: ['600000'], is_active: true, next_run_date: '2026-08-22', last_run_at: '2026-08-21', last_run_status: 'success', last_error: null, created_at: '2026-08-20', updated_at: '2026-08-21' }],
      strategy_runs: { 1: [{ id: 11, monitor_id: 1, scheduled_date: '2026-08-21', started_at: '2026-08-21T09:00:00', finished_at: '2026-08-21T09:01:00', status: 'success', task_id: null, result: null, error: null }] },
      stocks: [{ id: 2, market: 'HK', symbol: '00005', name: null, threshold_price: 100, is_active: true, state: 'triggered', last_price: 98, last_price_date: '2026-08-21', last_triggered_at: '2026-08-21T10:00:00', created_at: '2026-08-20', updated_at: '2026-08-21' }],
      stock_events: { 2: [{ id: 21, monitor_id: 2, market: 'HK', symbol: '00005', observed_price: 98, threshold_price: 100, observed_date: '2026-08-21', triggered_at: '2026-08-21T10:00:00', status: 'recorded' }] },
    });

    render(<MarketMonitor />);

    expect(await screen.findByText('运行历史')).toBeInTheDocument();
    expect(screen.getAllByText('2026-08-21').length).toBeGreaterThan(0);
    expect(screen.getByText('成功')).toBeInTheDocument();
    expect(await screen.findByText('价格事件')).toBeInTheDocument();
    expect(screen.getByText('98')).toBeInTheDocument();
  });

  it('does not send an empty strategy symbol list', async () => {
    monitoringApi.createStrategyMonitor.mockResolvedValue({ id: 3, name: '全市场策略' });
    render(<MarketMonitor />);
    await screen.findByRole('heading', { name: '策略监控' });
    fireEvent.click(screen.getByRole('button', { name: '添加策略监控' }));
    fireEvent.change(screen.getByLabelText('策略名称'), { target: { value: '价值策略' } });
    fireEvent.click(screen.getByRole('button', { name: '保存策略监控' }));

    await waitFor(() => expect(monitoringApi.createStrategyMonitor).toHaveBeenCalled());
    expect(monitoringApi.createStrategyMonitor.mock.calls[0][0].symbols).toBeUndefined();
    expect(monitoringApi.createStrategyMonitor.mock.calls[0][0]).toMatchObject({ name: '价值策略', strategy_class: 'ValueStrategy', filepath: 'strategies/value.py' });
  });

  it('renders strategy creation failures in a separate action error slot', async () => {
    monitoringApi.createStrategyMonitor.mockRejectedValueOnce(new Error('create failed'));
    render(<MarketMonitor />);
    await screen.findByRole('heading', { name: '策略监控' });
    fireEvent.click(screen.getByRole('button', { name: '添加策略监控' }));
    fireEvent.change(screen.getByLabelText('策略名称'), { target: { value: '价值策略' } });
    fireEvent.click(screen.getByRole('button', { name: '保存策略监控' }));

    const actionError = await screen.findByText('策略监控创建失败，请检查配置');
    expect(actionError).toHaveClass('mb-3', 'text-xs', 'text-danger');
    expect(screen.getByText('暂无策略监控')).toBeInTheDocument();
  });

  it('blocks strategy creation when the executable strategy directory fails to load', async () => {
    backtestEngineApi.listStrategies.mockRejectedValueOnce(new Error('directory unavailable'));
    render(<MarketMonitor />);
    expect(await screen.findByRole('alert')).toHaveTextContent('策略目录加载失败');
    fireEvent.click(screen.getByRole('button', { name: '添加策略监控' }));
    expect(screen.getByRole('button', { name: '保存策略监控' })).toBeDisabled();
  });

  it('reports run failures and refreshes strategy history after a successful run', async () => {
    monitoringApi.getCenter.mockResolvedValue({ ...emptySnapshot, strategies: [{ id: 1, name: '价值策略', strategy_class: 'ValueStrategy', filepath: 'value.py', params: {}, market: 'A', frequency: 'daily', symbols: null, is_active: true, next_run_date: null, last_run_at: null, last_run_status: 'pending', last_error: null, created_at: '', updated_at: '' }] });
    monitoringApi.runStrategyMonitor.mockResolvedValue({ id: 11 });
    render(<MarketMonitor />);
    fireEvent.click(await screen.findByRole('button', { name: '立即运行' }));
    await waitFor(() => expect(monitoringApi.runStrategyMonitor).toHaveBeenCalledWith(1, expect.any(String)));
    await waitFor(() => expect(monitoringApi.getCenter).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('运行失败')).not.toBeInTheDocument();
  });

  it('refreshes strategy history and shows an error when a run fails', async () => {
    monitoringApi.getCenter.mockResolvedValue({ ...emptySnapshot, strategies: [{ id: 1, name: '价值策略', strategy_class: 'ValueStrategy', filepath: 'value.py', params: {}, market: 'A', frequency: 'daily', symbols: null, is_active: true, next_run_date: null, last_run_at: null, last_run_status: 'pending', last_error: null, created_at: '', updated_at: '' }] });
    monitoringApi.runStrategyMonitor.mockRejectedValueOnce(new Error('execution failed'));
    render(<MarketMonitor />);
    fireEvent.click(await screen.findByRole('button', { name: '立即运行' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('运行策略监控失败');
    await waitFor(() => expect(monitoringApi.getCenter).toHaveBeenCalledTimes(1));
  });

  it('shows an action error when pausing a stock monitor fails', async () => {
    monitoringApi.getCenter.mockResolvedValue({ ...emptySnapshot, stocks: [{ id: 2, market: 'HK', symbol: '00005', name: null, threshold_price: 100, is_active: true, state: 'armed', last_price: null, last_price_date: null, last_triggered_at: null, created_at: '', updated_at: '' }] });
    monitoringApi.pauseStockMonitor.mockRejectedValueOnce(new Error('pause failed'));
    render(<MarketMonitor />);
    fireEvent.click(await screen.findByRole('button', { name: '暂停 00005' }));
    fireEvent.click(screen.getByRole('button', { name: '确认' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('暂停股票监控失败');
  });
});
