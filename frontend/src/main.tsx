import React from 'react'
import ReactDOM from 'react-dom/client'
import { AuthKitProvider } from '@workos-inc/authkit-react'
import App from './App.tsx'

const clientId = import.meta.env.VITE_WORKOS_CLIENT_ID as string
const redirectUri = import.meta.env.VITE_WORKOS_REDIRECT_URI as string
const apiHostname = import.meta.env.VITE_WORKOS_API_HOSTNAME as string | undefined

// NOTE: deliberately no onRedirectCallback. It previously did
// window.location.replace() — a full reload right after the code exchange that
// discarded the in-memory session and forced a fresh /bootstrap on every login,
// hammering WorkOS into a 429 + redirect loop. Post-callback navigation is now
// handled client-side (no reload) by the AuthCallback route, preserving the session.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthKitProvider
      clientId={clientId}
      redirectUri={redirectUri}
      apiHostname={apiHostname}
    >
      <App />
    </AuthKitProvider>
  </React.StrictMode>,
)
