// Manifest schema v1 — shared contract between save (serialize) and
// load (hydrate). Splats today; meshes + lights are wired in parallel
// by Agent A but already deserialized here.

export const MANIFEST_SCHEMA_VERSION = 1;

export type ObjectKind = "splat" | "mesh" | "light_directional";

export interface Vec3 {
  0: number;
  1: number;
  2: number;
  length: 3;
}

export type Vec3Tuple = [number, number, number];
export type Vec4Tuple = [number, number, number, number];

export interface ManifestTransform {
  position: Vec3Tuple;
  rotation: Vec4Tuple; // quaternion (x, y, z, w)
  scale: Vec3Tuple;
}

export interface ManifestAsset {
  url: string;
  sha256: string;
  size: number;
}

export interface ManifestLight {
  color: Vec3Tuple;
  intensity: number;
}

export interface ManifestObject {
  id: string;
  kind: ObjectKind;
  name: string;
  visible: boolean;
  transform: ManifestTransform;
  asset: ManifestAsset | null;
  light: ManifestLight | null;
}

export interface SceneManifest {
  schema: number;
  name: string;
  objects: ManifestObject[];
}

export function emptyManifest(name = "Untitled"): SceneManifest {
  return { schema: MANIFEST_SCHEMA_VERSION, name, objects: [] };
}

// Euler degrees → quaternion (XYZ intrinsic, matches three.js / renderer
// convention). Used when the editor exposes rotation as deg but the
// manifest stores quats.
export function eulerDegToQuat(degXYZ: Vec3Tuple): Vec4Tuple {
  const [dx, dy, dz] = degXYZ;
  const cx = Math.cos((dx * Math.PI) / 360);
  const sx = Math.sin((dx * Math.PI) / 360);
  const cy = Math.cos((dy * Math.PI) / 360);
  const sy = Math.sin((dy * Math.PI) / 360);
  const cz = Math.cos((dz * Math.PI) / 360);
  const sz = Math.sin((dz * Math.PI) / 360);
  // XYZ order
  const x = sx * cy * cz + cx * sy * sz;
  const y = cx * sy * cz - sx * cy * sz;
  const z = cx * cy * sz + sx * sy * cz;
  const w = cx * cy * cz - sx * sy * sz;
  return [x, y, z, w];
}

export function quatToEulerDeg(q: Vec4Tuple): Vec3Tuple {
  const [x, y, z, w] = q;
  // XYZ intrinsic.
  const sinp = 2 * (w * y - z * x);
  const py = Math.abs(sinp) >= 1 ? Math.sign(sinp) * (Math.PI / 2) : Math.asin(sinp);
  const px = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
  const pz = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  const r2d = 180 / Math.PI;
  return [px * r2d, py * r2d, pz * r2d];
}

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const view = new Uint8Array(digest);
  let out = "";
  for (const b of view) out += b.toString(16).padStart(2, "0");
  return out;
}

// File extension from a name (no dot). Lowercased. Defaults to "bin".
export function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  if (i < 0 || i === name.length - 1) return "bin";
  return name.slice(i + 1).toLowerCase();
}
