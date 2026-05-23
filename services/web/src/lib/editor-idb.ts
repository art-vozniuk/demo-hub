// Tiny IDB wrapper for the login-redirect detour. Single object store
// "editor-restore" with two keys: "scene-meta" (manifest minus asset
// URLs) and "scene-bytes" (Map<objectId, ArrayBuffer>).

import type { SceneManifest } from "./scene-manifest";

const DB_NAME = "meme-fusion-editor";
const DB_VERSION = 1;
const STORE = "editor-restore";

const META_KEY = "scene-meta";
const BYTES_KEY = "scene-bytes";

export type SceneBytesMap = Record<string, ArrayBuffer>;

export interface RestorePayload {
  manifest: SceneManifest;
  bytes: SceneBytesMap;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx(db: IDBDatabase, mode: IDBTransactionMode) {
  return db.transaction(STORE, mode).objectStore(STORE);
}

function put(store: IDBObjectStore, key: string, value: unknown): Promise<void> {
  return new Promise((resolve, reject) => {
    const r = store.put(value, key);
    r.onsuccess = () => resolve();
    r.onerror = () => reject(r.error);
  });
}

function get<T>(store: IDBObjectStore, key: string): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const r = store.get(key);
    r.onsuccess = () => resolve(r.result as T | undefined);
    r.onerror = () => reject(r.error);
  });
}

function clearAll(store: IDBObjectStore): Promise<void> {
  return new Promise((resolve, reject) => {
    const r = store.clear();
    r.onsuccess = () => resolve();
    r.onerror = () => reject(r.error);
  });
}

export async function saveRestorePayload(payload: RestorePayload): Promise<void> {
  const db = await openDb();
  try {
    const store = tx(db, "readwrite");
    await put(store, META_KEY, payload.manifest);
    await put(store, BYTES_KEY, payload.bytes);
  } finally {
    db.close();
  }
}

export async function loadRestorePayload(): Promise<RestorePayload | null> {
  const db = await openDb();
  try {
    const store = tx(db, "readonly");
    const manifest = await get<SceneManifest>(store, META_KEY);
    const bytes = (await get<SceneBytesMap>(store, BYTES_KEY)) ?? {};
    if (!manifest) return null;
    return { manifest, bytes };
  } finally {
    db.close();
  }
}

export async function clearRestorePayload(): Promise<void> {
  const db = await openDb();
  try {
    await clearAll(tx(db, "readwrite"));
  } finally {
    db.close();
  }
}
