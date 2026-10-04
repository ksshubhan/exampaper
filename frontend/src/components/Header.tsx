import type { ComponentType, SVGProps } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { PRACTICE_PATH } from '../data/catalog'
import { useTheme } from '../hooks/useTheme'
import {
  AboutIcon,
  BracketsIcon,
  HomeIcon,
  MoonIcon,
  PricingIcon,
  SparkleIcon,
  SunIcon,
} from './icons'

type IconType = ComponentType<SVGProps<SVGSVGElement>>

interface NavItem {
  to: string
  label: string
  Icon: IconType
  isActive: (pathname: string) => boolean
}

const NAV: NavItem[] = [
  {
    to: '/',
    label: 'Home',
    Icon: HomeIcon,
    // The homepage is the practice entry point, so it owns those routes too.
    isActive: (p) =>
      p === '/' || p === PRACTICE_PATH || p.startsWith(`${PRACTICE_PATH}/`),
  },
  { to: '/pricing', label: 'Pricing', Icon: PricingIcon, isActive: (p) => p === '/pricing' },
  { to: '/about', label: 'About', Icon: AboutIcon, isActive: (p) => p === '/about' },
]

export default function Header() {
  const { pathname } = useLocation()
  const { theme, toggle } = useTheme()

  return (
    <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)]">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4">
        {/* Theme toggle */}
        <button
          type="button"
          onClick={toggle}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border)] text-[var(--text)] transition hover:bg-[var(--hover)] active:scale-95"
        >
          {theme === 'dark' ? (
            <SunIcon className="h-[18px] w-[18px]" />
          ) : (
            <MoonIcon className="h-[18px] w-[18px]" />
          )}
        </button>

        {/* Wordmark */}
        <Link to="/" className="flex items-center gap-2 pr-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text)]">
            <BracketsIcon className="h-4 w-4" />
          </span>
          <span className="text-lg font-semibold tracking-tight">ExamPaper</span>
        </Link>

        {/* Nav pills */}
        <nav className="ml-auto flex items-center gap-1 overflow-x-auto">
          {NAV.map(({ to, label, Icon, isActive }) => {
            const active = isActive(pathname)
            return (
              <Link
                key={to}
                to={to}
                aria-current={active ? 'page' : undefined}
                className={
                  'flex items-center gap-2 whitespace-nowrap rounded-full px-3.5 py-2 text-sm font-medium transition ' +
                  (active
                    ? 'bg-[var(--accent)] text-[var(--accent-text)]'
                    : 'text-[var(--text)] hover:bg-[var(--hover)]')
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            )
          })}
        </nav>

        {/* CTA */}
        <button
          type="button"
          className="ml-1 hidden items-center gap-2 whitespace-nowrap rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--hover)] active:scale-95 sm:flex"
        >
          <SparkleIcon className="h-4 w-4" />
          Sign up
        </button>
      </div>
    </header>
  )
}
