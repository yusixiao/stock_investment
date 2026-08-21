import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Card } from '../Card';

describe('Card', () => {
  it('exposes the shared surface class for consistent page styling', () => {
    const { container } = render(<Card>Content</Card>);

    expect(container.firstElementChild).toHaveClass('surface-card');
  });
});
