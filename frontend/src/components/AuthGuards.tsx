/**
 * Authentication routing helpers built on WorkOS AuthKit.
 *
 * - `RequireAuth`   gate for protected route groups; bounces logged-out users
 *                   into the hosted AuthKit sign-in.
 * - `AuthCallback`  the `/auth/callback` landing route; the AuthKit provider
 *                   completes the code exchange, then we route onward.
 * - `AuthBridge`    wires the in-React `getAccessToken`/`signIn` into the
 *                   module-level axios client (see services/api.ts).
 */
import React, { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@workos-inc/authkit-react';
import { registerAuth } from '@/services/api';

const Loading: React.FC<{ label: string }> = ({ label }) => (
  <div
    style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: 'var(--text-secondary, #888)',
    }}
  >
    {label}
  </div>
);

/** Gate a protected route group: redirect to hosted sign-in when unauthenticated. */
export const RequireAuth: React.FC = () => {
  const { isLoading, user, signIn } = useAuth();
  const location = useLocation();
  const signInStartedRef = React.useRef(false);

  useEffect(() => {
    if (!isLoading && !user && !signInStartedRef.current) {
      signInStartedRef.current = true;
      void signIn({
        state: {
          returnTo: `${location.pathname}${location.search}${location.hash}`,
        },
      });
    }
  }, [isLoading, location.hash, location.pathname, location.search, user, signIn]);

  if (isLoading || !user) {
    return <Loading label="Loading…" />;
  }
  return <Outlet />;
};

/** WorkOS sign-in endpoint route; starts hosted auth when WorkOS lands here. */
export const LoginRoute: React.FC = () => {
  const { isLoading, user, signIn } = useAuth();
  const navigate = useNavigate();
  const signInStartedRef = React.useRef(false);

  useEffect(() => {
    if (isLoading) {
      return;
    }

    if (user) {
      navigate('/dashboard', { replace: true });
      return;
    }

    if (!signInStartedRef.current) {
      signInStartedRef.current = true;
      void signIn({ state: { returnTo: '/dashboard' } });
    }
  }, [isLoading, user, navigate, signIn]);

  return <Loading label="Redirecting…" />;
};

/** Landing route for the WorkOS redirect URI; routes onward once auth resolves. */
export const AuthCallback: React.FC = () => {
  const { isLoading, user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoading) {
      navigate(user ? '/dashboard' : '/', { replace: true });
    }
  }, [isLoading, user, navigate]);

  return <Loading label="Signing you in…" />;
};

/** Feeds the AuthKit token getter + re-auth callback to the axios client. */
export const AuthBridge: React.FC = () => {
  const { getAccessToken, signIn } = useAuth();

  useEffect(() => {
    registerAuth(
      async () => {
        try {
          return await getAccessToken();
        } catch {
          // No active session — request proceeds without a token.
          return undefined;
        }
      },
      () => {
        signIn();
      },
    );
  }, [getAccessToken, signIn]);

  return null;
};
