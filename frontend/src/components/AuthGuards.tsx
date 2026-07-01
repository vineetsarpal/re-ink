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
import { registerAuth, onboardingApi } from '@/services/api';

const center = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: 'var(--text-secondary, #888)',
} as const;

const Loading: React.FC<{ label: string }> = ({ label }) => (
  <div style={center}>{label}</div>
);

// Loop breaker: the per-mount ref resets on reload, so a failing sign-in could
// redirect forever. Persist the attempt; if we return still unauthenticated
// within the window, stop and show an error instead of redirecting again.
const SIGNIN_ATTEMPT_KEY = 'reink:signin-attempt-at';
const SIGNIN_LOOP_WINDOW_MS = 20_000;

const recentSignInFailed = (): boolean => {
  const at = Number(sessionStorage.getItem(SIGNIN_ATTEMPT_KEY) || 0);
  return at > 0 && Date.now() - at < SIGNIN_LOOP_WINDOW_MS;
};
const markSignInAttempt = () =>
  sessionStorage.setItem(SIGNIN_ATTEMPT_KEY, String(Date.now()));
const clearSignInAttempt = () => sessionStorage.removeItem(SIGNIN_ATTEMPT_KEY);

const AuthError: React.FC = () => (
  <div style={center}>
    <div style={{ textAlign: 'center', maxWidth: 420 }}>
      <p>We couldn’t complete sign-in. This can happen briefly if the
        authentication service is rate-limited — please wait a moment and retry.</p>
      <button
        className="btn btn-primary"
        onClick={() => {
          clearSignInAttempt();
          window.location.assign('/login');
        }}
      >
        Try again
      </button>
    </div>
  </div>
);

/** Gate a protected route group: redirect to hosted sign-in when unauthenticated. */
export const RequireAuth: React.FC = () => {
  const { isLoading, user, signIn, organizationId, switchToOrganization } = useAuth();
  const location = useLocation();
  const signInStartedRef = React.useRef(false);
  const [looped, setLooped] = React.useState(false);
  const provisionStartedRef = React.useRef(false);
  const [provisionFailed, setProvisionFailed] = React.useState(false);

  useEffect(() => {
    if (isLoading) return;
    if (user) {
      clearSignInAttempt(); // authenticated → reset the loop guard
      return;
    }
    if (signInStartedRef.current) return;
    if (recentSignInFailed()) {
      // Returned from a sign-in still unauthenticated → stop, don't re-redirect.
      setLooped(true);
      return;
    }
    signInStartedRef.current = true;
    markSignInAttempt();
    void signIn({
      state: {
        returnTo: `${location.pathname}${location.search}${location.hash}`,
      },
    });
  }, [isLoading, location.hash, location.pathname, location.search, user, signIn]);

  // A signed-in user with no organization gets a dedicated one provisioned, then
  // switches into it so the token becomes org-scoped. Runs once per mount.
  useEffect(() => {
    if (isLoading || !user || organizationId) return;
    if (provisionStartedRef.current) return;
    provisionStartedRef.current = true;
    void (async () => {
      try {
        const { organization_id } = await onboardingApi.provisionOrganization();
        await switchToOrganization({ organizationId: organization_id });
      } catch {
        setProvisionFailed(true);
      }
    })();
  }, [isLoading, user, organizationId, switchToOrganization]);

  if (looped) {
    return <AuthError />;
  }
  if (isLoading || !user) {
    return <Loading label="Loading…" />;
  }
  if (provisionFailed) {
    return <AuthError />;
  }
  if (!organizationId) {
    return <Loading label="Setting up your workspace…" />;
  }
  return <Outlet />;
};

/** WorkOS sign-in endpoint route; starts hosted auth when WorkOS lands here. */
export const LoginRoute: React.FC = () => {
  const { isLoading, user, signIn } = useAuth();
  const navigate = useNavigate();
  const signInStartedRef = React.useRef(false);
  const [looped, setLooped] = React.useState(false);

  useEffect(() => {
    if (isLoading) return;
    if (user) {
      clearSignInAttempt();
      navigate('/dashboard', { replace: true });
      return;
    }
    if (signInStartedRef.current) return;
    if (recentSignInFailed()) {
      setLooped(true);
      return;
    }
    signInStartedRef.current = true;
    markSignInAttempt();
    void signIn({ state: { returnTo: '/dashboard' } });
  }, [isLoading, user, navigate, signIn]);

  if (looped) {
    return <AuthError />;
  }
  return <Loading label="Redirecting…" />;
};

/** Landing route for the WorkOS redirect URI; routes onward once auth resolves. */
export const AuthCallback: React.FC = () => {
  const { isLoading, user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLoading) return;
    if (user) {
      clearSignInAttempt(); // successful exchange → reset the loop guard
    }
    navigate(user ? '/dashboard' : '/', { replace: true });
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
