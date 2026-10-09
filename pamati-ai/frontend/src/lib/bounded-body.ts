/** Stop reading as soon as the limit is exceeded, including chunked requests. */
export class BodyError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function boundedBody(request: Request): Promise<string> {
  const maximum = 32768;
  const declared = request.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > maximum)) {
    throw new BodyError(/^\d+$/.test(declared) ? 413 : 400, "Invalid request size");
  }
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximum) {
        await reader.cancel();
        throw new BodyError(413, "Request too large");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new BodyError(400, "Invalid request encoding"); }
}
