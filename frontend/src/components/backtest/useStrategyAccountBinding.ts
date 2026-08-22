import { useCallback, useRef, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import type { TaskListItem } from '../../api/backtestEngine';
import { extractStrategyName } from './historyTaskAdapter';

interface Options {
  refresh: () => Promise<void>;
}

interface StrategyAccountBinding {
  bindingId: string | null;
  bindingError: ParsedApiError | null;
  clearBindingError: () => void;
  bindTask: (item: TaskListItem) => Promise<void>;
}

export function useStrategyAccountBinding({ refresh }: Options): StrategyAccountBinding {
  const [bindingId, setBindingId] = useState<string | null>(null);
  const [bindingError, setBindingError] = useState<ParsedApiError | null>(null);
  const bindingRequestToken = useRef(0);

  const clearBindingError = useCallback(() => setBindingError(null), []);

  const bindTask = useCallback(async (item: TaskListItem) => {
    if (item.status !== 'success' || item.deleted || item.execution_status === 'active') return;
    const requestToken = ++bindingRequestToken.current;
    setBindingId(item.task_id);
    setBindingError(null);
    try {
      const accounts = (await portfolioApi.getAccounts(false)).accounts;
      const candidates = accounts.filter((account) => !account.strategyTaskId);
      const eligibleAccounts = await Promise.all(candidates.map(async (account) => {
        const snapshot = await portfolioApi.getSnapshot({ accountId: account.id });
        const hasHoldings = snapshot.accounts.some((snapshotAccount) =>
          snapshotAccount.positions.some((position) => position.quantity > 0),
        );
        return hasHoldings ? null : account;
      }));
      const account = eligibleAccounts.find((candidate) => candidate != null);
      if (account) {
        await portfolioApi.bindStrategy(account.id, item.task_id);
      } else {
        const market = String(item.pipeline_info?.market || 'A').toLowerCase();
        await portfolioApi.createAccount({
          name: `${extractStrategyName(item)}策略账户`,
          market: market === 'hk' || market === 'us' ? market : 'cn',
          baseCurrency: market === 'us' ? 'USD' : market === 'hk' ? 'HKD' : 'CNY',
          strategyTaskId: item.task_id,
        });
      }
      if (requestToken === bindingRequestToken.current) {
        await refresh();
      }
    } catch (err) {
      if (requestToken === bindingRequestToken.current) {
        setBindingError(getParsedApiError(err));
      }
    } finally {
      if (requestToken === bindingRequestToken.current) {
        setBindingId(null);
      }
    }
  }, [refresh]);

  return { bindingId, bindingError, clearBindingError, bindTask };
}
