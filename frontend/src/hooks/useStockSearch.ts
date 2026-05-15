import { useState, useCallback, useRef, useEffect } from 'react';
import apiClient from '../api';
import type { StockSuggestion } from '../types/stockIndex';

export interface UseStockSearchResult {
  query: string;
  setQuery: (value: string) => void;
  suggestions: StockSuggestion[];
  isOpen: boolean;
  highlightedIndex: number;
  setHighlightedIndex: (index: number) => void;
  highlightPrevious: () => void;
  highlightNext: () => void;
  handleSelect: (suggestion: StockSuggestion) => void;
  close: () => void;
  reset: () => void;
  isComposing: boolean;
  setIsComposing: (composing: boolean) => void;
  loading: boolean;
}

const DEBOUNCE_MS = 200;
const MIN_LENGTH = 1;

const MARKET_MAP: Record<string, string> = { A: 'CN', HK: 'HK', US: 'US' };

export function useStockSearch(): UseStockSearchResult {
  const [query, setQueryState] = useState('');
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isComposing, setIsComposing] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (q.length < MIN_LENGTH) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }
    setLoading(true);
    try {
      const resp = await apiClient.get('/api/stocks/search', { params: { q, limit: 10 } });
      const items: StockSuggestion[] = (resp.data.results || []).map((r: { code: string; name: string | null; market: string }) => {
        const displayCode = r.code.includes('.') ? r.code.split('.')[0] : r.code;
        return {
          canonicalCode: r.code,
          displayCode,
          nameZh: r.name || r.code,
          market: MARKET_MAP[r.market] || r.market,
          matchType: 'prefix' as const,
          matchField: 'code' as const,
          score: 80,
        };
      });
      setSuggestions(items);
      setIsOpen(items.length > 0);
      setHighlightedIndex(-1);
    } catch {
      setSuggestions([]);
      setIsOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const setQuery = useCallback((value: string) => {
    setQueryState(value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => doSearch(value), DEBOUNCE_MS);
  }, [doSearch]);

  const handleSelect = useCallback((suggestion: StockSuggestion) => {
    setQueryState(suggestion.displayCode);
    setIsOpen(false);
    setSuggestions([]);
    setHighlightedIndex(-1);
  }, []);

  const highlightPrevious = useCallback(() => {
    setHighlightedIndex(prev => prev <= 0 ? suggestions.length - 1 : prev - 1);
  }, [suggestions.length]);

  const highlightNext = useCallback(() => {
    setHighlightedIndex(prev => prev >= suggestions.length - 1 ? 0 : prev + 1);
  }, [suggestions.length]);

  const close = useCallback(() => {
    setIsOpen(false);
    setHighlightedIndex(-1);
  }, []);

  const reset = useCallback(() => {
    setQueryState('');
    setSuggestions([]);
    setIsOpen(false);
    setHighlightedIndex(-1);
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  return {
    query,
    setQuery,
    suggestions,
    isOpen,
    highlightedIndex,
    setHighlightedIndex,
    highlightPrevious,
    highlightNext,
    handleSelect,
    close,
    reset,
    isComposing,
    setIsComposing,
    loading,
  };
}
