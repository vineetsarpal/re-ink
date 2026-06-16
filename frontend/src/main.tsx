import React from 'react'
import ReactDOM from 'react-dom/client'
import { AuthKitProvider } from '@workos-inc/authkit-react'
import App from './App.tsx'

const clientId = import.meta.env.VITE_WORKOS_CLIENT_ID as string
const redirectUri = import.meta.env.VITE_WORKOS_REDIRECT_URI as string
const apiHostname = import.meta.env.VITE_WORKOS_API_HOSTNAME as string | undefined

// No onRedirectCallback: a full-page reload there dropped the session and looped
// /bootstrap. The AuthCallback route navigates client-side instead.
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
