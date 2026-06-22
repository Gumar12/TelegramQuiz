import type { ReactNode } from 'react';
import { ChevronRight, Loader2 } from 'lucide-react';
import { appRoutes, brandIcon as BrandIcon, getRoute, type AppRouteId } from '../../app/routes';
import { Button } from '../ui/Button';

type AppShellProps = {
  activeRoute: AppRouteId;
  activeAccountName?: string;
  children: ReactNode;
  currentStep?: string;
  isLocked?: boolean;
  onAccountChange: () => void;
  onNavigate: (routeId: AppRouteId) => void;
};

export function AppShell({
  activeRoute,
  activeAccountName = 'Нет аккаунта',
  children,
  currentStep,
  isLocked = false,
  onAccountChange,
  onNavigate,
}: AppShellProps) {
  const route = getRoute(activeRoute);

  return (
    <div className="min-h-screen overflow-x-hidden bg-gray-50 text-gray-950 antialiased">
      <div className="flex min-h-screen min-w-0 flex-col lg:flex-row">
        <aside className="flex min-w-0 shrink-0 flex-col overflow-hidden border-b border-gray-200 bg-white lg:min-h-screen lg:w-64 lg:border-b-0 lg:border-r">
          <div className="flex min-w-0 items-center gap-3 px-4 py-4 lg:px-5 lg:py-5">
            <BrandIcon className="size-6 text-gray-950" aria-hidden="true" />
            <span className="truncate text-lg font-bold tracking-normal text-gray-950">QuizBot Platform</span>
          </div>

          <nav className="flex w-full min-w-0 gap-1 overflow-x-auto px-2 pb-3 lg:flex-1 lg:flex-col lg:overflow-visible lg:px-3 lg:py-1">
            {appRoutes.map((item) => {
              const Icon = item.icon;
              const isActive = item.id === activeRoute;

              return (
                <button
                  className={[
                    'relative flex h-11 shrink-0 items-center gap-3 rounded-md px-3 text-left text-sm font-semibold transition-colors lg:min-w-0 lg:shrink',
                    isActive
                      ? 'bg-[#FCE7F0] text-[#E85D8F]'
                      : 'text-gray-700 hover:bg-gray-50 hover:text-gray-950',
                  ].join(' ')}
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  type="button"
                >
                  {isActive && <span className="absolute left-0 top-2 h-7 w-1 rounded-r-full bg-[#E85D8F]" />}
                  <Icon className="size-4 shrink-0" aria-hidden="true" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex min-h-16 flex-col justify-center gap-3 border-b border-gray-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <span>Панель</span>
                <ChevronRight className="size-4" aria-hidden="true" />
                <span className="truncate">{route.label}</span>
              </div>
              {isLocked && currentStep && (
                <div className="mt-1 flex items-center gap-2 text-xs font-semibold text-amber-700">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                  <span className="truncate">{currentStep}</span>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end">
              <Button onClick={onAccountChange} size="sm" variant="subtle">
                {activeAccountName}
              </Button>
            </div>
          </header>

          <main className="min-w-0 flex-1 bg-gray-50 px-4 py-5 sm:px-6 lg:px-7">
            <div className="mx-auto max-w-[1440px]">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}
