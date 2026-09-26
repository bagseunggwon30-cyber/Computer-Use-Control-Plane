export interface CucpResponse {
  schema: "cucp.response/v1";
  id: string;
  command: string;
  status: "ok" | "partial" | "error" | "blocked";
  data: Record<string, unknown>;
  errors: { code: string; message: string }[];
  duration_ms: number;
}

export class CucpFailure extends Error {
  constructor(public readonly response: CucpResponse) {
    super(`${response.command}: ${response.status}: ${response.errors.map(e => `${e.code}: ${e.message}`).join("; ") || "Operation did not fully complete"}`);
    this.name = "CucpFailure";
  }
}

export function parseResponse(line: string, id: string, command: string): CucpResponse {
  const value: unknown = JSON.parse(line);
  if (!value || typeof value !== "object") throw new Error("CUCP returned a non-object response");
  const r = value as CucpResponse;
  if (r.schema !== "cucp.response/v1" || r.id !== id || r.command !== command ||
      !["ok", "partial", "error", "blocked"].includes(r.status) ||
      !r.data || typeof r.data !== "object" || Array.isArray(r.data) ||
      !Array.isArray(r.errors) || !r.errors.every(e => e && typeof e.code === "string" && typeof e.message === "string") ||
      typeof r.duration_ms !== "number" || !Number.isFinite(r.duration_ms) || r.duration_ms < 0) {
    throw new Error("CUCP returned an invalid or mismatched response envelope");
  }
  return r;
}

type Content = { type: "text"; text: string } | { type: "image"; mimeType: string; data: string };

/** Send image bytes as image content, never as base64 text in the model context. */
export function toToolResult(response: CucpResponse): { content: Content[]; details: unknown } {
  const images: Content[] = [];
  const seenImages = new Set<string>();
  const scrub = (value: unknown, key = ""): unknown => {
    if (Array.isArray(value)) return value.map(v => scrub(v));
    if (!value || typeof value !== "object") return value;
    const obj = value as Record<string, unknown>;
    if (key === "image" && typeof obj.data === "string") {
      const mime = obj.mime_type;
      if (typeof mime !== "string" || !["image/png", "image/jpeg", "image/webp"].includes(mime) ||
          obj.data.length > 20 * 1024 * 1024 || !/^[A-Za-z0-9+/]*={0,2}$/.test(obj.data) || obj.data.length % 4 !== 0) {
        throw new Error("CUCP returned an invalid image payload");
      }
      if (!seenImages.has(obj.data)) {
        images.push({ type: "image", mimeType: mime, data: obj.data });
        seenImages.add(obj.data);
      }
      const { data: _, ...metadata } = obj;
      return { ...metadata, delivered_as: "image_content" };
    }
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, scrub(v, k)]));
  };
  const details = scrub(response);
  return { content: [{ type: "text", text: JSON.stringify(details) }, ...images], details };
}
