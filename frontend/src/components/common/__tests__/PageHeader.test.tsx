import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PageHeader } from '../PageHeader';

describe('PageHeader', () => {
  it('uses the shared page header surface', () => {
    render(<PageHeader title="设置" description="管理系统配置" />);

    expect(screen.getByRole('heading', { name: '设置' }).parentElement?.parentElement?.parentElement).toHaveClass(
      'page-header',
    );
  });
});
