import {
  ArrowRight,
  AudioLines,
  BarChart3,
  FileText,
  HardDrive,
  Languages,
  ListChecks,
  Lock,
  Mic,
  ShieldCheck,
  Sparkles,
  Users,
  Wand2,
} from 'lucide-react'
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { useAuthStatus } from '../api/queries'
import { SunsetScene, WaveRule } from '../components/art'
import { Reveal } from '../components/motion'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { BrandMark, Waveform } from '../components/visuals'
import { EASE_OUT } from '../lib/easing'
import { useDocumentTitle } from '../lib/utils'

function useSignedIn(): boolean {
  return Boolean(useAuthStatus().data?.user)
}

function PrimaryCta({ className }: { className?: string }) {
  const signedIn = useSignedIn()
  return (
    <Button asChild variant="primary" className={className}>
      <Link to={signedIn ? '/meetings' : '/login'}>
        {signedIn ? 'Open your meetings' : 'Get started'} <ArrowRight aria-hidden />
      </Link>
    </Button>
  )
}

function TopBar() {
  const signedIn = useSignedIn()
  return (
    <header className="sticky top-0 z-40">
      <div className="glass mx-auto mt-3 flex max-w-6xl items-center justify-between gap-4 rounded-2xl px-4 py-2.5 sm:px-5">
        <Link to="/" className="flex items-center gap-2.5 rounded-lg">
          <BrandMark />
          <span className="font-display text-fg font-semibold" translate="no">
            RuDy.ai
          </span>
        </Link>
        <nav aria-label="Sections" className="hidden items-center gap-6 text-sm md:flex">
          <a href="#how" className="text-muted hover:text-fg transition-colors">
            How it works
          </a>
          <a href="#features" className="text-muted hover:text-fg transition-colors">
            Features
          </a>
          <a href="#privacy" className="text-muted hover:text-fg transition-colors">
            Privacy
          </a>
        </nav>
        <div className="flex items-center gap-2">
          {signedIn ? null : (
            <Button asChild variant="ghost" size="sm">
              <Link to="/login">Sign in</Link>
            </Button>
          )}
          <PrimaryCta className="h-9" />
        </div>
      </div>
    </header>
  )
}

function ScrollProgress() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 140, damping: 30, mass: 0.3 })
  return (
    <motion.div
      aria-hidden
      className="bg-brand fixed inset-x-0 top-0 z-50 h-1 origin-left"
      style={{ scaleX }}
    />
  )
}

/**
 * Holds a SunsetScene below its section's text, never behind it, so headlines
 * and copy always sit on the plain background. The height follows the width
 * (the scene is drawn 1200x640 and cropped from the top), so wide windows do not
 * cut into the sun; the top edge fades out instead of ending in a hard line.
 */
const SCENE_BOX =
  'pointer-events-none relative h-[clamp(300px,34vw,720px)] [mask-image:linear-gradient(to_bottom,transparent,black_28%)]'

function Hero() {
  const ref = useRef<HTMLElement>(null)
  const reduce = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  // Parallax: the scene sinks and fades slower than the page scrolls.
  const sceneY = useTransform(scrollYProgress, [0, 1], ['0%', reduce ? '0%' : '22%'])
  const textY = useTransform(scrollYProgress, [0, 1], ['0%', reduce ? '0%' : '-30%'])
  const fade = useTransform(scrollYProgress, [0, 0.8], [1, reduce ? 1 : 0])
  return (
    <section ref={ref} className="relative -mt-16 overflow-hidden pt-16">
      <motion.div
        className="relative z-10 mx-auto flex max-w-4xl flex-col items-center px-5 pt-20 text-center sm:pt-28"
        style={{ y: textY, opacity: fade }}
      >
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE_OUT }}
          className="glass text-muted inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
        >
          <Sparkles className="text-accent size-3.5" aria-hidden /> Hindi · English · Hinglish
        </motion.p>
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.1, ease: EASE_OUT }}
          className="text-brand mt-6 text-5xl leading-[1.05] font-semibold tracking-tight text-balance sm:text-7xl"
        >
          Every voice in your meeting, understood.
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.25, ease: EASE_OUT }}
          className="text-muted mt-6 max-w-2xl text-lg text-pretty"
        >
          Record or upload a meeting. Get a transcript that knows who spoke when and in which
          language, a clean Hinglish version, a summary and the action items, all on your own
          machine.
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4, ease: EASE_OUT }}
          className="mt-9 flex flex-wrap justify-center gap-3"
        >
          <PrimaryCta className="h-12 px-6 text-base" />
          <Button asChild variant="secondary" className="h-12 px-6 text-base">
            <a href="#how">See how it works</a>
          </Button>
        </motion.div>
      </motion.div>
      <motion.div className={`${SCENE_BOX} -mt-4`} style={{ y: sceneY }}>
        <SunsetScene />
      </motion.div>
    </section>
  )
}

const STEPS = [
  { icon: Mic, title: 'Capture', text: 'Upload a recording or record live from the microphone.' },
  { icon: AudioLines, title: 'Transcribe', text: 'Whisper large-v3 turns speech into text.' },
  { icon: Users, title: 'Who spoke', text: 'pyannote separates the speakers across the meeting.' },
  {
    icon: Languages,
    title: 'Languages',
    text: 'Each line is tagged Hindi, English or code-mixed.',
  },
  { icon: Wand2, title: 'Understand', text: 'Hinglish text, a summary and the action items.' },
]

function HowItWorks() {
  const ref = useRef<HTMLOListElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start 85%', 'end 45%'] })
  const line = useSpring(scrollYProgress, { stiffness: 120, damping: 30 })
  return (
    <section id="how" className="relative mx-auto max-w-6xl scroll-mt-24 px-5 py-28">
      <Reveal className="mx-auto max-w-2xl text-center">
        <p className="text-accent text-xs font-semibold tracking-[0.18em] uppercase">
          How it works
        </p>
        <h2 className="text-fg mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
          From sound to decisions
        </h2>
        <WaveRule className="mx-auto mt-5" />
      </Reveal>
      <ol ref={ref} className="relative mt-16 grid gap-6 md:grid-cols-5">
        {/* The connecting line draws itself as the steps scroll into view. */}
        <motion.span
          aria-hidden
          className="bg-brand absolute top-7 right-[10%] left-[10%] hidden h-0.5 origin-left rounded-full md:block"
          style={{ scaleX: line }}
        />
        {STEPS.map(({ icon: Icon, title, text }, index) => (
          <Reveal key={title} as="li" delay={index * 0.12} className="relative text-center">
            <div>
              <span className="bg-cta text-cta-fg glow relative mx-auto grid size-14 place-items-center rounded-2xl">
                <Icon className="size-6" aria-hidden />
              </span>
              <p className="text-faint mt-4 font-mono text-xs">0{index + 1}</p>
              <h3 className="text-fg mt-1 text-lg font-semibold">{title}</h3>
              <p className="text-muted mt-2 text-sm">{text}</p>
            </div>
          </Reveal>
        ))}
      </ol>
    </section>
  )
}

const FEATURES: { icon: typeof Mic; title: string; text: string }[] = [
  {
    icon: Users,
    title: 'Speaker diarization',
    text: 'A coloured timeline of who spoke when; click anywhere to jump the audio there.',
  },
  {
    icon: Languages,
    title: 'Code-mixed by design',
    text: 'Built for real Indian meetings that switch between Hindi and English mid-sentence.',
  },
  {
    icon: FileText,
    title: 'Two scripts, one click',
    text: 'Read the original Devanagari or a normalized Romanized Hinglish version.',
  },
  {
    icon: ListChecks,
    title: 'Summary & action items',
    text: 'Who must do what, by when, drafted by a local language model.',
  },
  {
    icon: Mic,
    title: 'Live transcription',
    text: 'Watch the transcript build while you speak, with speakers tracked across the session.',
  },
  {
    icon: BarChart3,
    title: 'Measured, not guessed',
    text: 'Every result records the exact code and settings behind it, and an evaluation suite scores accuracy.',
  },
]

function Features() {
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
      <Reveal className="max-w-2xl">
        <p className="text-accent text-xs font-semibold tracking-[0.18em] uppercase">Features</p>
        <h2 className="text-fg mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
          Everything a meeting leaves behind
        </h2>
      </Reveal>
      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }, index) => (
          <Reveal key={title} delay={(index % 3) * 0.1}>
            <Card interactive className="group relative h-full overflow-hidden p-6">
              <div
                aria-hidden
                className="bg-brand pointer-events-none absolute -top-16 -right-16 size-40 rounded-full opacity-0 blur-3xl transition-opacity duration-500 group-hover:opacity-25"
              />
              <span className="bg-accent-soft text-accent ring-accent/25 grid size-11 place-items-center rounded-xl ring-1 ring-inset">
                <Icon className="size-5" aria-hidden />
              </span>
              <h3 className="text-fg mt-5 text-lg font-semibold">{title}</h3>
              <p className="text-muted mt-2 text-sm leading-relaxed">{text}</p>
            </Card>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

const SCRIPT_LINES = [
  { label: 'Original script', lang: 'hi', text: 'release Friday को होगा, testing कल तक' },
  { label: 'Hinglish', lang: 'hi-Latn', text: 'release Friday ko hoga, testing kal tak' },
]

function ScriptDemo() {
  const reduce = useReducedMotion()
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (reduce) return
    const timer = setInterval(() => setIndex((i) => (i + 1) % SCRIPT_LINES.length), 2800)
    return () => clearInterval(timer)
  }, [reduce])
  const line = SCRIPT_LINES[index]!
  return (
    <section className="mx-auto max-w-6xl px-5 py-24">
      <Reveal>
        <Card className="relative overflow-hidden p-8 sm:p-12">
          <div
            aria-hidden
            className="bg-brand pointer-events-none absolute -bottom-32 -left-24 size-96 rounded-full opacity-15 blur-3xl"
          />
          <div className="relative grid items-center gap-10 lg:grid-cols-2">
            <div>
              <p className="text-accent text-xs font-semibold tracking-[0.18em] uppercase">
                Code-mixed speech
              </p>
              <h2 className="text-fg mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                Hindi and English in one sentence? Naturally.
              </h2>
              <p className="text-muted mt-4">
                Each line keeps its language tag, and you can read it in the script it was spoken in
                or in Romanized Hinglish.
              </p>
            </div>
            <div className="glass rounded-2xl p-6">
              <div className="mb-4 flex items-center gap-2 text-xs">
                <span className="bg-subtle text-muted rounded-md px-2 py-0.5 font-mono">0:07</span>
                <span className="rounded-md bg-sky-500/15 px-2 py-0.5 font-medium text-sky-600 dark:text-sky-300">
                  Speaker 00
                </span>
                <span className="rounded-md bg-purple-500/15 px-2 py-0.5 font-semibold text-purple-700 dark:text-purple-300">
                  MIX
                </span>
              </div>
              <AnimatePresence mode="wait" initial={false}>
                <motion.p
                  key={line.label}
                  lang={line.lang}
                  initial={{ opacity: 0, y: 12, filter: 'blur(6px)' }}
                  animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                  exit={{ opacity: 0, y: -12, filter: 'blur(6px)' }}
                  transition={{ duration: 0.45, ease: EASE_OUT }}
                  className="font-display text-fg min-h-16 text-2xl"
                >
                  {line.text}
                </motion.p>
              </AnimatePresence>
              <p className="text-faint mt-3 text-xs" aria-live="polite">
                Showing: {line.label}
              </p>
              <Waveform active={!reduce} bars={40} className="mt-6 h-10 opacity-80" />
            </div>
          </div>
        </Card>
      </Reveal>
    </section>
  )
}

function PrivacyPoint({
  icon,
  title,
  children,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <div className="flex gap-4">
      <span className="text-accent mt-0.5 [&_svg]:size-6" aria-hidden>
        {icon}
      </span>
      <div>
        <h3 className="text-fg font-semibold">{title}</h3>
        <p className="text-muted mt-1 text-sm">{children}</p>
      </div>
    </div>
  )
}

function Privacy() {
  return (
    <section id="privacy" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
      <div className="grid gap-12 lg:grid-cols-2">
        <Reveal>
          <p className="text-accent text-xs font-semibold tracking-[0.18em] uppercase">Privacy</p>
          <h2 className="text-fg mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
            Your meetings never leave your machine
          </h2>
          <p className="text-muted mt-4 max-w-md">
            Speech recognition, speaker detection and the language model all run locally. Nothing is
            uploaded to a cloud service.
          </p>
        </Reveal>
        <div className="space-y-8">
          <Reveal delay={0.05}>
            <PrivacyPoint icon={<HardDrive />} title="Local models">
              Whisper, pyannote and Ollama run on this computer, even offline.
            </PrivacyPoint>
          </Reveal>
          <Reveal delay={0.15}>
            <PrivacyPoint icon={<Lock />} title="Accounts and sessions">
              Hashed passwords and a secure session cookie protect every transcript.
            </PrivacyPoint>
          </Reveal>
          <Reveal delay={0.25}>
            <PrivacyPoint icon={<ShieldCheck />} title="Traceable results">
              Every run records the code, settings and models that produced it.
            </PrivacyPoint>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

function FinalCta() {
  return (
    <section className="relative overflow-hidden">
      <Reveal className="relative mx-auto max-w-3xl px-5 pt-24 text-center">
        <h2 className="text-brand text-4xl font-semibold tracking-tight text-balance sm:text-6xl">
          Ready for your next meeting?
        </h2>
        <p className="text-muted mt-5 text-lg">
          Sign in and drop in a recording. It takes a minute.
        </p>
        <div className="mt-9 flex justify-center">
          <PrimaryCta className="h-12 px-7 text-base" />
        </div>
      </Reveal>
      <div className={`${SCENE_BOX} opacity-90`}>
        <SunsetScene bubbles={false} />
      </div>
    </section>
  )
}

export function LandingPage() {
  useDocumentTitle(null)
  return (
    <div className="overflow-x-clip">
      <a
        href="#main"
        className="bg-accent text-accent-fg sr-only z-50 rounded-md px-3 py-2 focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2"
      >
        Skip to content
      </a>
      <ScrollProgress />
      <div className="px-3">
        <TopBar />
      </div>
      <main id="main">
        <Hero />
        <HowItWorks />
        <Features />
        <ScriptDemo />
        <Privacy />
        <FinalCta />
      </main>
      <footer className="border-border border-t">
        <div className="text-faint mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-sm">
          <span className="flex items-center gap-2">
            <BrandMark className="size-6" /> RuDy.ai
          </span>
          <span>A final-year capstone · Hindi–English meeting intelligence</span>
        </div>
      </footer>
    </div>
  )
}
