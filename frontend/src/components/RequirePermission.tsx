import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@workos-inc/authkit-react';

/** Redirect users away from pages their current access token cannot authorize. */
export const RequirePermission: React.FC<{ permission: string }> = ({ permission }) => {
  const { permissions } = useAuth();
  const location = useLocation();

  if (!permissions.includes(permission)) {
    return <Navigate to="/dashboard" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
};
