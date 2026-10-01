/**
 * A browser's User-Agent header, as a person recognises their own device in
 * « Sessions ouvertes » : « Firefox sur Windows », « Safari sur iOS ».
 *
 * Coarse on purpose — no versions: the point is to tell « my office PC » from
 * « a phone I never use », not to fingerprint anything. The header is whatever
 * the client chose to send, so this is a hint, never a proof; the IP address
 * shown beside it says more about where a session really comes from.
 */

// Order matters: Edge and Opera announce Chrome too, and Chrome announces
// Safari — the most specific token has to be tried first.
const BROWSERS: [RegExp, string][] = [
  [/Edg(e|A|iOS)?\//, 'Edge'],
  [/OPR\/|Opera/, 'Opera'],
  [/Firefox\/|FxiOS\//, 'Firefox'],
  [/Chrome\/|CriOS\//, 'Chrome'],
  [/Safari\//, 'Safari'],
];

// iOS before macOS (an iPad may say « like Mac OS X »), Android before Linux.
const SYSTEMS: [RegExp, string][] = [
  [/Windows/, 'Windows'],
  [/iPhone|iPad|iPod/, 'iOS'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/Android/, 'Android'],
  [/CrOS/, 'ChromeOS'],
  [/Linux/, 'Linux'],
];

function firstMatch(value: string, table: [RegExp, string][]): string | null {
  return table.find(([pattern]) => pattern.test(value))?.[1] ?? null;
}

export function describeUserAgent(userAgent: string | null | undefined): string {
  if (!userAgent) return 'Appareil inconnu';
  const browser = firstMatch(userAgent, BROWSERS);
  const system = firstMatch(userAgent, SYSTEMS);
  if (browser && system) return `${browser} sur ${system}`;
  if (browser) return browser;
  if (system) return `Navigateur sur ${system}`;
  return 'Appareil inconnu';
}
