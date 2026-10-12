import { cn } from '../../lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
  disabled?: boolean
}

/**
 * A row of mutually exclusive choices drawn as one control. Native radio
 * buttons underneath, so arrow keys move between options and assistive
 * technology announces it as a group.
 */
export function Segmented<T extends string>({
  name,
  legend,
  value,
  options,
  onChange,
  className,
}: {
  name: string
  legend: string
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <fieldset className={cn('bg-subtle inline-flex flex-wrap rounded-md p-0.5', className)}>
      <legend className="sr-only">{legend}</legend>
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            'has-[:focus-visible]:outline-ring rounded px-2.5 py-1 text-xs font-medium transition-colors has-[:focus-visible]:outline-2',
            option.disabled
              ? 'text-faint cursor-not-allowed'
              : value === option.value
                ? 'bg-surface text-fg cursor-pointer shadow-xs'
                : 'text-muted hover:text-fg cursor-pointer',
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={option.disabled}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  )
}
