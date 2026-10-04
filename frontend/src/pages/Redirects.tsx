import { Navigate, useParams } from 'react-router-dom'
import { PRACTICE_PATH } from '../data/catalog'

// The flow used to be split across two entry points, /past-papers and
// /worksheets. Both now fold into /practice. Every hop replaces its history
// entry so the back button skips the redirect and lands where the user came
// from.

/** /past-papers/<rest> -> /practice/<rest>, renaming the builder's segment. */
export function PastPapersRedirect() {
  const rest = useParams()['*'] ?? ''
  const moved = rest.replace(/(^|\/)build$/, '$1paper')
  return (
    <Navigate to={moved ? `${PRACTICE_PATH}/${moved}` : PRACTICE_PATH} replace />
  )
}

/** Worksheets aren't built yet, so any depth lands on the practice index. */
export function PracticeIndexRedirect() {
  return <Navigate to={PRACTICE_PATH} replace />
}

/** Anything unrecognised: the front door. */
export function HomeRedirect() {
  return <Navigate to="/" replace />
}
