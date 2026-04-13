-- One-off migration: move party role from parties.party_type to
-- contract_parties.role, since the same party can play different roles on
-- different contracts.
--
-- Apply once against any existing dev/prod DB. New deployments started from
-- scratch via Base.metadata.create_all will not need this.

BEGIN;

-- 1. Backfill contract_parties.role from the now-deprecated parties.party_type
--    where the association row has no role yet.
UPDATE contract_parties cp
SET role = p.party_type
FROM parties p
WHERE cp.party_id = p.id
  AND cp.role IS NULL
  AND p.party_type IS NOT NULL;

-- 2. Drop the parties.party_type column.
ALTER TABLE parties DROP COLUMN IF EXISTS party_type;

COMMIT;
