type ProgressProps = {
  value: number;
  label?: string;
};

export function Progress({ label, value }: ProgressProps) {
  const boundedValue = Math.max(0, Math.min(100, Math.round(value)));

  return (
    <div className="space-y-2">
      {label && (
        <div className="flex items-center justify-between gap-3 text-xs font-semibold text-gray-500">
          <span>{label}</span>
          <span>{boundedValue}%</span>
        </div>
      )}
      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
        <div className="h-full rounded-full bg-[#E85D8F] transition-[width]" style={{ width: `${boundedValue}%` }} />
      </div>
    </div>
  );
}
