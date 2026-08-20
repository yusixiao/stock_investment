import { beforeEach, describe, expect, it, vi } from 'vitest';
import { portfolioApi } from '../portfolio';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({ default: { get, post, delete: del } }));

describe('portfolio strategy API mapping', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    del.mockReset();
  });

  it('binds and unbinds strategy accounts through the v1 routes', async () => {
    post.mockResolvedValueOnce({ data: { id: 7, strategy_task_id: 'task-1' } });
    del.mockResolvedValueOnce({ data: { id: 7, strategy_task_id: null } });

    await portfolioApi.bindStrategy(7, 'task-1');
    await portfolioApi.unbindStrategy(7);

    expect(post).toHaveBeenCalledWith('/api/v1/portfolio/accounts/7/strategy', { task_id: 'task-1' });
    expect(del).toHaveBeenCalledWith('/api/v1/portfolio/accounts/7/strategy');
  });

  it('maps enriched snapshot fields without using the legacy portfolio route', async () => {
    get.mockResolvedValueOnce({
      data: {
        accounts: [{
          account_id: 7,
          positions: [{
            symbol: '600519.SH',
            target_quantity: 10,
            reference_price: 1500,
            remaining_quantity: 4,
            over_target_quantity: 0,
            target_status: 'active',
            alert_status: 'buy',
          }],
        }],
      },
    });

    const response = await portfolioApi.getSnapshot({ accountId: 7 });

    expect(response.accounts[0].positions[0]).toMatchObject({
      targetQuantity: 10,
      referencePrice: 1500,
      remainingQuantity: 4,
      overTargetQuantity: 0,
      targetStatus: 'active',
      alertStatus: 'buy',
    });
    expect(get.mock.calls[0][0]).toBe('/api/v1/portfolio/snapshot');
    expect(get.mock.calls[0][0]).not.toContain('/api/portfolio');
  });
});
