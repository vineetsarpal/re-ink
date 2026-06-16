import React from 'react'
import ReactDOM from 'react-dom/client'
import { AuthKitProvider } from '@workos-inc/authkit-react'
import App from './App.tsx'

const clientId = import.meta.env.VITE_WORKOS_CLIENT_ID as string
const redirectUri = import.meta.env.VITE_WORKOS_REDIRECT_URI as string
const apiHostname = import.meta.env.VITE_WORKOS_API_HOSTNAME as string | undefined

const fallbackRedirectPath = '/dashboard'

const safeRedirectPath = (value: unknown): string => {
  if (typeof value !== 'string') {
    return fallbackRedirectPath
  }

  if (
    !value.startsWith('/') ||
    value.startsWith('//') ||
    value.startsWith('/auth/callback') ||
    value.startsWith('/login')
  ) {
    return fallbackRedirectPath
  }

  return value
}

const handleRedirectCallback = ({
  state,
}: {
  state: Record<string, unknown> | null
}) => {
  window.location.replace(safeRedirectPath(state?.returnTo))
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthKitProvider
      clientId={clientId}
      redirectUri={redirectUri}
      apiHostname={apiHostname}
      onRedirectCallback={handleRedirectCallback}
    >
      <App />
    </AuthKitProvider>
  </React.StrictMode>,
)
