/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Sentry's public DSN for the web project. Unset means no error reports. */
  readonly VITE_SENTRY_DSN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
