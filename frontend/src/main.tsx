import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import ClerkTokenBridge from './components/ClerkTokenBridge.tsx'
import Home from './pages/Home.tsx'
import About from './pages/About.tsx'
import Pricing from './pages/Pricing.tsx'
import Account from './pages/Account.tsx'
import BoardGrid from './pages/BoardGrid.tsx'
import SubjectGrid from './pages/SubjectGrid.tsx'
import PracticeChoice from './pages/PracticeChoice.tsx'
import BuildPaper from './pages/BuildPaper.tsx'
import BuildWorksheet from './pages/BuildWorksheet.tsx'
import {
  HomeRedirect,
  PastPapersRedirect,
  PracticeIndexRedirect,
} from './pages/Redirects.tsx'

const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { index: true, element: <Home /> },
      { path: 'about', element: <About /> },
      { path: 'pricing', element: <Pricing /> },
      // Where Stripe sends a payer back, as /account?upgraded=1.
      { path: 'account', element: <Account /> },

      // qualification -> exam board -> subject -> kind -> builder
      // The qualification picker lives on the homepage now.
      { path: 'practice', element: <HomeRedirect /> },
      { path: 'practice/:qualification', element: <BoardGrid /> },
      { path: 'practice/:qualification/:board', element: <SubjectGrid /> },
      {
        path: 'practice/:qualification/:board/:subject',
        element: <PracticeChoice />,
      },
      {
        path: 'practice/:qualification/:board/:subject/paper',
        element: <BuildPaper />,
      },
      {
        path: 'practice/:qualification/:board/:subject/worksheet',
        element: <BuildWorksheet />,
      },

      // Legacy entry points, kept so old links and bookmarks still resolve.
      { path: 'past-papers', element: <PracticeIndexRedirect /> },
      { path: 'past-papers/*', element: <PastPapersRedirect /> },
      { path: 'worksheets', element: <PracticeIndexRedirect /> },
      { path: 'worksheets/*', element: <PracticeIndexRedirect /> },

      { path: '*', element: <HomeRedirect /> },
    ],
  },
])

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!publishableKey) {
  // Fail loudly and early: without Clerk nobody can generate anything.
  throw new Error(
    'VITE_CLERK_PUBLISHABLE_KEY is not set — copy frontend/.env.example to ' +
      'frontend/.env and fill it in.',
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClerkProvider publishableKey={publishableKey} afterSignOutUrl="/">
      {/* Gives api.ts access to the session token. Renders nothing. */}
      <ClerkTokenBridge />
      <RouterProvider router={router} />
    </ClerkProvider>
  </StrictMode>,
)
