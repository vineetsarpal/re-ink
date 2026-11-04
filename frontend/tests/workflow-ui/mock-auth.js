// Test-only identity. This entry is never used by the production Vite build.
export const useAuth=()=>({permissions:new URLSearchParams(location.search).has('viewer')?[]:['document:upload','review:approve']});
