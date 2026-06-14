/**
 * StockAutocomplete component tests.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StockAutocomplete } from '../StockAutocomplete';
import type { UseStockSearchResult } from '../../../../hooks/useStockSearch';
import type { StockSuggestion } from '../../../../types/stockIndex';

let searchHookImpl: () => UseStockSearchResult;

// Mock the single search hook the component depends on.
vi.mock('../../../../hooks/useStockSearch', () => ({
  useStockSearch: () => searchHookImpl(),
}));

const mockSuggestions: StockSuggestion[] = [
  {
    canonicalCode: "600519.SH",
    displayCode: "600519",
    nameZh: "贵州茅台",
    market: "CN",
    matchType: "exact" as const,
    matchField: "code" as const,
    score: 100,
  },
];

const hkSuggestion: StockSuggestion = {
  canonicalCode: "00700.HK",
  displayCode: "00700",
  nameZh: "腾讯控股",
  market: "HK",
  matchType: "exact" as const,
  matchField: "code" as const,
  score: 100,
};

const bseSuggestion: StockSuggestion = {
  canonicalCode: "920493.BJ",
  displayCode: "920493",
  nameZh: "示例北交所股票",
  market: "BSE",
  matchType: "exact" as const,
  matchField: "code" as const,
  score: 100,
};

function makeSearch(overrides: Partial<UseStockSearchResult> = {}): UseStockSearchResult {
  return {
    query: '',
    setQuery: vi.fn(),
    suggestions: mockSuggestions,
    isOpen: false,
    highlightedIndex: -1,
    setHighlightedIndex: vi.fn(),
    highlightPrevious: vi.fn(),
    highlightNext: vi.fn(),
    handleSelect: vi.fn(),
    close: vi.fn(),
    reset: vi.fn(),
    isComposing: false,
    setIsComposing: vi.fn(),
    loading: false,
    ...overrides,
  };
}

describe('StockAutocomplete', () => {
  const mockOnChange = vi.fn();
  const mockOnSubmit = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    searchHookImpl = () => makeSearch();
  });

  it('renders the input element', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByPlaceholderText(/输入股票代码或名称/);
    expect(input).toBeInTheDocument();
  });

  it('renders a custom placeholder', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        placeholder="请输入代码"
      />
    );

    const input = screen.getByPlaceholderText(/请输入代码/);
    expect(input).toBeInTheDocument();
  });

  it('renders the current value', () => {
    render(
      <StockAutocomplete
        value="600519"
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByDisplayValue('600519');
    expect(input).toBeInTheDocument();
  });

  it('supports the disabled state', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        disabled={true}
      />
    );

    const input = screen.getByRole('combobox');
    expect(input).toBeDisabled();
  });

  it('calls onChange when the input changes', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: '600519' } });

    expect(mockOnChange).toHaveBeenCalledWith('600519');
  });

  it('applies a custom class name', () => {
    const { container } = render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        className="custom-class"
      />
    );

    const input = container.querySelector('.custom-class');
    expect(input).toBeInTheDocument();
  });

  it('exposes the expected accessibility attributes', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('aria-autocomplete', 'none');
    expect(input).toHaveAttribute('role', 'combobox');
  });

  describe('IME support', () => {
    it('handles composition start and end events', () => {
      render(
        <StockAutocomplete
          value=""
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByRole('combobox');

      fireEvent.compositionStart(input);
      fireEvent.compositionEnd(input);

      // The events should be handled without throwing.
      expect(input).toBeInTheDocument();
    });
  });

  describe('keyboard submission', () => {
    it('submits the raw input when suggestions are open but nothing is highlighted', () => {
      searchHookImpl = () => makeSearch({ isOpen: true, highlightedIndex: -1 });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('6005');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnSubmit).toHaveBeenCalledWith('6005');
    });

    it('submits the highlighted suggestion when one is explicitly selected', () => {
      searchHookImpl = () => makeSearch({ isOpen: true, highlightedIndex: 0 });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('6005');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('600519');
      expect(mockOnSubmit).toHaveBeenCalledWith('600519.SH', '贵州茅台', 'autocomplete');
    });

    it('submits the highlighted HK suggestion using the canonical .HK code', () => {
      searchHookImpl = () => makeSearch({
        suggestions: [hkSuggestion],
        isOpen: true,
        highlightedIndex: 0,
      });

      render(
        <StockAutocomplete
          value="00700"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('00700');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('00700');
      expect(mockOnSubmit).toHaveBeenCalledWith('00700.HK', '腾讯控股', 'autocomplete');
    });

    it('submits the highlighted BSE suggestion using the canonical .BJ code', () => {
      searchHookImpl = () => makeSearch({
        suggestions: [bseSuggestion],
        isOpen: true,
        highlightedIndex: 0,
      });

      render(
        <StockAutocomplete
          value="920493"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('920493');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('920493');
      expect(mockOnSubmit).toHaveBeenCalledWith('920493.BJ', '示例北交所股票', 'autocomplete');
    });
  });

  describe('runtime boundary fallback', () => {
    it('falls back to the plain input when the autocomplete tree throws during render', () => {
      searchHookImpl = () => {
        throw new Error('Autocomplete render failed');
      };

      render(
        <StockAutocomplete
          value="META"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('META');
      expect(input).toHaveAttribute('data-autocomplete-mode', 'fallback');
    });

    it('submits manually when the fallback input receives Enter', () => {
      searchHookImpl = () => {
        throw new Error('Autocomplete render failed');
      };

      render(
        <StockAutocomplete
          value="600519"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('600519');
      expect(input).toHaveAttribute('data-autocomplete-mode', 'fallback');

      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnSubmit).toHaveBeenCalledWith('600519');
    });

    it('falls back to the plain input when a suggestion contains an unsupported market', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      searchHookImpl = () => makeSearch({
        suggestions: [
          {
            canonicalCode: 'TEST.OTC',
            displayCode: 'TEST',
            nameZh: '测试市场',
            market: 'OTC' as never,
            matchType: 'exact' as const,
            matchField: 'code' as const,
            score: 100,
          },
        ],
        isOpen: true,
        highlightedIndex: 0,
      });

      render(
        <StockAutocomplete
          value="TEST"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('TEST');
      fireEvent.focus(input);

      const fallbackInput = screen.getByDisplayValue('TEST');
      expect(fallbackInput).toHaveAttribute('data-autocomplete-mode', 'fallback');
      expect(consoleErrorSpy).toHaveBeenCalled();
      consoleErrorSpy.mockRestore();
    });
  });
});
