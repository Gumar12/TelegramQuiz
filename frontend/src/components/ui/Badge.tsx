import type { HTMLAttributes, ReactNode } from 'react';

type BadgeTone = 'neutral' | 'pink' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: BadgeTone;
};

const toneClass: Record<BadgeTone, string> = {
  neutral: 'border-gray-200 bg-gray-50 text-gray-700',
  pink: 'border-[#f5b8cd] bg-[#FCE7F0] text-[#E85D8F]',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-700',
  danger: 'border-red-200 bg-red-50 text-red-700',
  info: 'border-blue-200 bg-blue-50 text-blue-700',
  violet: 'border-violet-200 bg-violet-50 text-violet-700',
};

export function Badge({ children, className = '', tone = 'neutral', ...props }: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex min-h-6 items-center rounded-md border px-2 py-0.5 text-xs font-semibold leading-none',
        toneClass[tone],
        className,
      ].join(' ')}
      {...props}
    >
      {children}
    </span>
  );
}
