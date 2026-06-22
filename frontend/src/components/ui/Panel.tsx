import type { HTMLAttributes, ReactNode } from 'react';

type PanelProps = HTMLAttributes<HTMLElement> & {
  as?: 'section' | 'article' | 'div';
  children: ReactNode;
};

export function Panel({ as: Component = 'section', children, className = '', ...props }: PanelProps) {
  return (
    <Component
      className={[
        'rounded-lg border border-gray-200 bg-white shadow-sm shadow-gray-950/[0.03]',
        className,
      ].join(' ')}
      {...props}
    >
      {children}
    </Component>
  );
}

export function PanelHeader({
  action,
  children,
  className = '',
  description,
  title,
}: {
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  description?: string;
  title: string;
}) {
  return (
    <div className={['flex items-start justify-between gap-4 px-4 pt-4 sm:px-5 sm:pt-5', className].join(' ')}>
      <div className="min-w-0">
        <h2 className="text-base font-bold tracking-normal text-gray-950">{title}</h2>
        {description && <p className="mt-1 text-sm leading-6 text-gray-500">{description}</p>}
        {children}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function PanelBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={['p-4 sm:p-5', className].join(' ')}>{children}</div>;
}
