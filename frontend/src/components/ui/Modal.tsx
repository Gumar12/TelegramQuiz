import type { ReactNode } from 'react';
import { X } from 'lucide-react';

type ModalProps = {
  children: ReactNode;
  footer?: ReactNode;
  isOpen: boolean;
  onClose: () => void;
  title: string;
};

export function Modal({ children, footer, isOpen, onClose, title }: ModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/25 p-4">
      <div className="w-full max-w-lg rounded-lg border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-gray-200 px-5 py-4">
          <h2 className="text-base font-bold text-gray-950">{title}</h2>
          <button
            aria-label="Закрыть"
            className="inline-flex size-9 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E85D8F]"
            onClick={onClose}
            type="button"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-4 text-sm leading-6 text-gray-700">{children}</div>
        {footer && <div className="flex justify-end gap-3 border-t border-gray-200 px-5 py-4">{footer}</div>}
      </div>
    </div>
  );
}
