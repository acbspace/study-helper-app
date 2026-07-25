/**
 * UUIDv4 generation.
 *
 * Sessions, events, and tasks get their ids on the device so they can be created offline
 * and synced later without renumbering — the client id *is* the server id, which is what
 * makes sync idempotent.
 */

import * as Crypto from 'expo-crypto';

export function newUuid(): string {
  return Crypto.randomUUID();
}
