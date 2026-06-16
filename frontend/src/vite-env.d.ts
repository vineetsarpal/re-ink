/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_WORKOS_CLIENT_ID?: string;
  readonly VITE_WORKOS_REDIRECT_URI?: string;
  readonly VITE_WORKOS_API_HOSTNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
