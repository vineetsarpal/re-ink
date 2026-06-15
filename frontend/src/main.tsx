import React from 'react'
import ReactDOM from 'react-dom/client'
import { AuthKitProvider } from '@workos-inc/authkit-react'
import App from './App.tsx'

const clientId = import.meta.env.VITE_WORKOS_CLIENT_ID as string
const redirectUri = import.meta.env.VITE_WORKOS_REDIRECT_URI as string

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthKitProvider clientId={clientId} redirectUri={redirectUri}>
      <App />
    </AuthKitProvider>
  </React.StrictMode>,
)
