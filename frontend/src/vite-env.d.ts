/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Clerk publishable key. Safe to ship to the browser; see frontend/.env. */
  readonly VITE_CLERK_PUBLISHABLE_KEY: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
