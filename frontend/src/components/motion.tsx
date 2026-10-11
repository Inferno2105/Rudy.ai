import { animate, motion, useReducedMotion, type Variants } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'

import { EASE_OUT } from '../lib/easing'
import { formatFixed } from '../lib/format'

/**
 * A number that counts up to `value` when it first appears. The final value
 * is what assistive technology reads (the animation is presentation only).
 */
export function CountUp({
  value,
  digits = 0,
  suffix = '',
  className,
}: {
  value: number
  digits?: number
  suffix?: string
  className?: string
}) {
  const reduce = useReducedMotion()
  const [shown, setShown] = useState(reduce ? value : 0)

  useEffect(() => {
    if (reduce) return
    const controls = animate(0, value, {
      duration: 1.1,
      ease: EASE_OUT,
      onUpdate: (latest) => setShown(latest),
    })
    return () => controls.stop()
  }, [value, reduce])

  const final = `${formatFixed(value, digits)}${suffix}`
  return (
    <span className={className}>
      <span aria-hidden>{`${formatFixed(reduce ? value : shown, digits)}${suffix}`}</span>
      <span className="sr-only">{final}</span>
    </span>
  )
}

const listVariants: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.045 } },
}

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE_OUT } },
}

/** A list whose items rise in one after another on first render. */
export function StaggerList({
  children,
  className,
  as = 'ul',
  ...aria
}: {
  children: ReactNode
  className?: string
  as?: 'ul' | 'ol' | 'div'
  'aria-label'?: string
}) {
  const Component = as === 'ul' ? motion.ul : as === 'ol' ? motion.ol : motion.div
  return (
    <Component
      className={className}
      variants={listVariants}
      initial="hidden"
      animate="shown"
      {...aria}
    >
      {children}
    </Component>
  )
}

export function StaggerItem({
  children,
  className,
  as = 'li',
}: {
  children: ReactNode
  className?: string
  as?: 'li' | 'div'
}) {
  const Component = as === 'li' ? motion.li : motion.div
  return (
    <Component className={className} variants={itemVariants}>
      {children}
    </Component>
  )
}
