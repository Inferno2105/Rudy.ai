import { motion } from 'motion/react'
import { Tabs as TabsPrimitive } from 'radix-ui'
import { createContext, useContext, useId, type ComponentProps } from 'react'

import { cn } from '../../lib/utils'

/** The active value and a per-instance id, so the sliding pill animates
 * between this tab list's triggers only. */
const TabsState = createContext<{ value: string | undefined; layoutId: string }>({
  value: undefined,
  layoutId: 'tabs',
})

export function Tabs({ value, ...props }: ComponentProps<typeof TabsPrimitive.Root>) {
  const layoutId = useId()
  return (
    <TabsState.Provider value={{ value, layoutId }}>
      <TabsPrimitive.Root value={value} {...props} />
    </TabsState.Provider>
  )
}

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn('glass inline-flex max-w-full gap-1 overflow-x-auto rounded-xl p-1', className)}
      {...props}
    />
  )
}

export function TabsTrigger({
  className,
  children,
  value,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  const state = useContext(TabsState)
  const active = state.value === value
  return (
    <TabsPrimitive.Trigger
      value={value}
      className={cn(
        'text-muted hover:text-fg relative inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium whitespace-nowrap transition-colors',
        'data-[state=active]:text-fg [&_svg]:size-4',
        className,
      )}
      {...props}
    >
      {active ? (
        <motion.span
          layoutId={state.layoutId}
          aria-hidden
          className="bg-surface ring-strong-border absolute inset-0 rounded-lg shadow-sm ring-1 dark:bg-white/10"
          transition={{ type: 'spring', stiffness: 420, damping: 34 }}
        />
      ) : null}
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
    </TabsPrimitive.Trigger>
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn(
        'focus-visible:outline-ring animate-enter rounded-sm pt-6 focus-visible:outline-2',
        className,
      )}
      {...props}
    />
  )
}
