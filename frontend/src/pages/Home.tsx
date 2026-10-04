import QualificationCards from '../components/QualificationCards'

export default function Home() {
  return (
    <div className="mx-auto max-w-5xl px-5 py-10">
      {/* Slim hero: the qualification cards have to stay above the fold on a
          1280x800 screen, so the spacing here is deliberately tight. */}
      <h1 className="max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
        Original exam-style papers on the topics you choose
      </h1>
      <p className="mt-3 max-w-xl text-lg text-[var(--muted)]">
        Every answer is checked automatically. Mark scheme included.
      </p>
      {/* Even gaps: subtitle -> heading -> cards. */}
      <h2 className="mt-4 text-xl font-semibold tracking-tight">
        Choose your qualification
      </h2>
      <div className="mt-4">
        <QualificationCards />
      </div>
    </div>
  )
}
