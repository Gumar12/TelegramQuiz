import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

type ButtonVariant = 'primary' | 'outline' | 'ghost' | 'subtle' | 'danger';
type ButtonSize = 'sm' | 'md';

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
};

const variantClass: Record<ButtonVariant, string> = {
  primary: 'border-[#E85D8F] bg-[#E85D8F] text-white shadow-sm shadow-pink-600/15 hover:border-[#d94a7d] hover:bg-[#d94a7d]',
  outline: 'border-[#E85D8F] bg-white text-[#E85D8F] hover:bg-[#FCE7F0]',
  ghost: 'border-transparent bg-transparent text-gray-700 hover:bg-gray-100',
  subtle: 'border-gray-200 bg-gray-50 text-gray-800 hover:bg-gray-100',
  danger: 'border-red-500 bg-white text-red-600 hover:bg-red-50',
};

const sizeClass: Record<ButtonSize, string> = {
  sm: 'min-h-9 px-3 text-sm',
  md: 'min-h-11 px-4 text-sm',
};

export function Button({
  children,
  className = '',
  disabled,
  icon,
  loading = false,
  size = 'md',
  type = 'button',
  variant = 'outline',
  ...props
}: ButtonProps) {
  return (
    <button
      className={[
        'inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E85D8F] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-55',
        variantClass[variant],
        sizeClass[size],
        className,
      ].join(' ')}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : icon}
      <span>{children}</span>
    </button>
  );
}
