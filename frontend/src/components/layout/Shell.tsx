import type React from 'react';
import { Outlet } from 'react-router-dom';
import { ThemeToggle } from '../theme/ThemeToggle';
import DataCacheStatusBar from './DataCacheStatusBar';

type ShellProps = {
  children?: React.ReactNode;
};

export const Shell: React.FC<ShellProps> = ({ children }) => {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-background/84 backdrop-blur-xl">
        <div className="mx-auto flex h-14 w-full max-w-[1680px] items-center justify-between px-4 sm:px-6">
          <div>
            <p className="text-sm font-semibold tracking-wide text-foreground">回测平台</p>
            <p className="text-xs text-secondary-text">策略研究与结果分析工作区</p>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto min-h-[calc(100vh-3.5rem)] w-full max-w-[1680px] min-w-0 touch-pan-y px-3 py-3 sm:px-4 sm:py-4 lg:px-5">
          {children ?? <Outlet />}
      </main>

      <DataCacheStatusBar />
    </div>
  );
};
