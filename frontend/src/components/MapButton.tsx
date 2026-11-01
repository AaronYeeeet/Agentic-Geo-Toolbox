import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface MapButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  side?: 'top' | 'right' | 'bottom' | 'left'
  pressed?: boolean
  children: ReactNode
}

/** Square icon button for the floating map panels; the label is both tooltip and accessible name. */
export function MapButton({ label, side = 'right', pressed, className, children, ...props }: MapButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          aria-pressed={pressed}
          className={cn(
            'grid size-10 shrink-0 place-items-center text-ink-2 transition-colors hover:bg-fog hover:text-ink',
            'disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-[18px]',
            pressed && 'bg-water-wash text-water-ink hover:bg-water-wash hover:text-water-ink',
            className,
          )}
          {...props}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side={side} sideOffset={6}>
        {label}
      </TooltipContent>
    </Tooltip>
  )
}

export function PanelDivider({ vertical = false }: { vertical?: boolean }) {
  return <div aria-hidden className={vertical ? 'w-px self-stretch bg-rule' : 'h-px w-full bg-rule'} />
}
