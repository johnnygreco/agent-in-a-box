// Every internal link and asset path goes through here, so the site works
// under its project base path (/agent-in-a-box/) as well as at a root.
const base = import.meta.env.BASE_URL.replace(/\/$/, "");

export function url(path: string): string {
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
