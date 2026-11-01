import { ChevronDown, CircleAlert, CircleCheck, CircleSlash, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import type { ToolStep } from '@/store/chatStore'

function StepIcon({ status, className }: { status: ToolStep['status']; className?: string }) {
  if (status === 'running') return <LoaderCircle className={cn('animate-spin text-water', className)} aria-hidden />
  if (status === 'error') return <CircleAlert className={cn('text-danger', className)} aria-hidden />
  if (status === 'stopped') return <CircleSlash className={cn('text-ink-3', className)} aria-hidden />
  return <CircleCheck className={cn('text-ok', className)} aria-hidden />
}

function duration(ms: number | undefined, lang: string) {
  if (ms === undefined) return ''
  return ms < 1000
    ? `${ms} ms`
    : `${new Intl.NumberFormat(lang === 'de' ? 'de-DE' : 'en-US', { maximumFractionDigits: 1 }).format(ms / 1000)} s`
}

/** The agent's steps as a compact log (running, done, error), collapsible per answer. */
export function ToolSteps({ steps }: { steps: ToolStep[] }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(true)
  if (steps.length === 0) return null
  const overall: ToolStep['status'] = steps.some((s) => s.status === 'running')
    ? 'running'
    : steps.some((s) => s.status === 'error')
      ? 'error'
      : steps.some((s) => s.status === 'stopped')
        ? 'stopped'
        : 'ok'
  const statusLabel = {
    running: t('chat.stepRunning'),
    error: t('chat.stepError'),
    stopped: t('chat.stopped'),
    ok: t('chat.stepDone'),
  }[overall]

  return (
    <div className="rounded-lg border border-rule bg-paper text-[12.5px]" data-testid="tool-steps">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-ink-2 hover:text-ink"
      >
        <StepIcon status={overall} className="size-3.5 shrink-0" />
        <span className="font-medium">{t('chat.steps', { count: steps.length })}</span>
        <span className="text-ink-3">{statusLabel}</span>
        <ChevronDown className={cn('ml-auto size-3.5 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <ol className="space-y-1 border-t border-rule/70 px-2.5 py-2">
          {steps.map((step) => (
            <li key={step.id} className="flex items-start gap-2">
              <StepIcon status={step.status} className="mt-0.5 size-3.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-ink">{step.label}</p>
                {step.summary && (
                  <p className={cn(step.status === 'error' ? 'text-danger' : 'text-ink-3')}>{step.summary}</p>
                )}
              </div>
              <span className="shrink-0 pt-px text-ink-3 tabular-nums">{duration(step.durationMs, i18n.language)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
