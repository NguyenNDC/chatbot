export function cx(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function formatBytes(value?: number | null) {
  if (!value) {
    return "n/a";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString([], {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(value?: string | null) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function initials(value: string) {
  const parts = value
    .split(/\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return "AI";
  }
  return parts
    .slice(0, 2)
    .map((item) => item[0]?.toUpperCase() ?? "")
    .join("");
}

export function statusTone(status?: string | null) {
  if (status === "processed" || status === "completed" || status === "ok" || status === "active") {
    return "success";
  }
  if (status === "queued" || status === "processing" || status === "running" || status === "degraded") {
    return "live";
  }
  return "danger";
}

export function progressCounter(current?: number | null, total?: number | null) {
  if (typeof current === "number" && typeof total === "number" && total > 0) {
    return `${current}/${total}`;
  }
  return null;
}
