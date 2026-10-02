export async function checkService(origin, path, fetcher = fetch) {
  try {
    const response = await fetcher(new URL(path, origin), {
      cache: "no-store", signal: AbortSignal.timeout(4000)
    });
    if (!response.ok) return "unavailable";
    const data = await response.json();
    return data.service === "pamati-api" && ["ok", "ready"].includes(data.status)
      ? "available" : "unavailable";
  } catch {
    return "unavailable";
  }
}
