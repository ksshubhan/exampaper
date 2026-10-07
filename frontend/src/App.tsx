import { Link, Outlet } from 'react-router-dom'
import Header from './components/Header'

export default function App() {
  return (
    <div className="min-h-svh bg-[var(--bg)] text-[var(--text)]">
      <Header />
      <main>
        <Outlet />
      </main>
      <footer className="px-5 py-8 text-center text-sm text-[var(--muted)]">
        <Link
          to="/privacy"
          className="transition-colors hover:text-[var(--text)]"
        >
          Privacy
        </Link>
      </footer>
    </div>
  )
}
