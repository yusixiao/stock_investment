import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Drawer } from '../Drawer';

describe('Drawer', () => {
  it('focuses the dialog, closes on Escape, and restores focus', () => {
    const onClose = vi.fn();
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();

    const { rerender } = render(
      <Drawer isOpen title="详情" onClose={onClose}>
        内容
      </Drawer>,
    );

    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(screen.getByRole('dialog'));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();

    rerender(
      <Drawer isOpen={false} title="详情" onClose={onClose}>
        内容
      </Drawer>,
    );

    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});
