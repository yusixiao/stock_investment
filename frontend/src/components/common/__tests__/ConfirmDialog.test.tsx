import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../ConfirmDialog';

describe('ConfirmDialog', () => {
  it('exposes dialog semantics, closes on Escape, and restores focus', () => {
    const onCancel = vi.fn();
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();

    const { rerender } = render(
      <ConfirmDialog
        isOpen
        title="删除记录"
        message="确认删除吗？"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(screen.getByRole('dialog'));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledOnce();

    rerender(
      <ConfirmDialog
        isOpen={false}
        title="删除记录"
        message="确认删除吗？"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});
