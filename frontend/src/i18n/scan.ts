/**
 * Finds interface text written in French outside the catalogues (plan
 * `dev/plan-console-bilingue.md`, I6): what an English reader would still
 * read in French.
 *
 * A heuristic, run by `noHardcodedFrench.spec.ts` over every source file:
 * comments are stripped, then a string literal or a template text counts as
 * French when it holds a French letter or punctuation (é, à, ç, «, »…) or a
 * French function word between spaces. Identifiers, keys and CSS classes hold
 * neither. A line that must keep French text (a regular expression that reads
 * a French server message, say) says so with `i18n-ignore`.
 */

const FRENCH_CHARS = /[àâäçéèêëîïôöûùüÿœæÀÂÇÉÈÊËÎÏÔÛÙÜŸŒÆ«»]/;
const FRENCH_WORDS =
  /(^|[\s'(«])(le|la|les|des|du|un|une|aucun|aucune|est|sont|pas|pour|avec|sans|dans|sur|ou|et|au|aux|ce|cette|ces|qui|que|ne|plus|votre|vos|nous|vous|poste|postes|salle|salles|paquet|paquets|jour|jours|heure|heures|oui|non|enregistrer|annuler|supprimer|fermer|modifier|ajouter|chargement|erreur)(?=[\s.,;:!?)»]|$)/i;

// Words that stand alone as a label (« Postes », « Nom ») and are not English.
const FRENCH_LABELS = new Set(
  (
    'poste postes nom noms groupe groupes utilisateur utilisateurs logiciels logiciel paquet paquets ' +
    'salle salles emplacement emplacements commandes commande menaces menace fichiers fichier ' +
    'actualiser rechercher recherche filtres filtre colonnes exporter valider retour statut adresse ' +
    'compte comptes journal connexion oui non aucun aucune inconnu inconnue domaine fabricant ' +
    'stockage enregistrer annuler supprimer fermer modifier ajouter retirer choisir chargement ' +
    'erreur tous toutes heure jours mois semaine taille total affecter clore envoyer ' +
    'paramètres sélection effacer détails afficher masquer suivant précédent'
  ).split(' '),
);

export interface Finding {
  line: number;
  text: string;
}

/** Blank out comments, keeping line numbers and string contents. */
function stripComments(source: string, html: boolean): string {
  let out = '';
  let i = 0;
  let quote: string | null = null;
  while (i < source.length) {
    const c = source[i]!;
    const next = source[i + 1];
    if (quote) {
      out += c;
      if (c === '\\') {
        out += next ?? '';
        i += 2;
        continue;
      }
      if (c === quote) quote = null;
      i += 1;
      continue;
    }
    if (html && source.startsWith('<!--', i)) {
      const end = source.indexOf('-->', i + 4);
      const stop = end === -1 ? source.length : end + 3;
      out += source.slice(i, stop).replace(/[^\n]/g, ' ');
      i = stop;
      continue;
    }
    if (!html && c === '/' && next === '/') {
      const end = source.indexOf('\n', i);
      const stop = end === -1 ? source.length : end;
      out += ' '.repeat(stop - i);
      i = stop;
      continue;
    }
    if (!html && c === '/' && next === '*') {
      const end = source.indexOf('*/', i + 2);
      const stop = end === -1 ? source.length : end + 2;
      out += source.slice(i, stop).replace(/[^\n]/g, ' ');
      i = stop;
      continue;
    }
    if (!html && (c === "'" || c === '"' || c === '`')) quote = c;
    out += c;
    i += 1;
  }
  return out;
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length;
}

function french(text: string): boolean {
  const plain = text.trim();
  if (!plain) return false;
  if (FRENCH_CHARS.test(plain)) return true;
  if (plain.includes(' ')) return FRENCH_WORDS.test(plain);
  return FRENCH_LABELS.has(plain.replace(/[.:…]+$/, '').toLowerCase());
}

/** String literals of TypeScript code (template literals included). */
function scanCode(code: string, offset: number, source: string, found: Finding[]): void {
  const literal = /'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g;
  for (const match of code.matchAll(literal)) {
    const body = match[0].slice(1, -1).replace(/\$\{[^}]*\}/g, ' ');
    if (french(body)) found.push({ line: lineOf(source, offset + match.index), text: match[0] });
  }
}

/** Text between tags, and quoted attribute values, of a Vue template. */
function scanTemplate(template: string, offset: number, source: string, found: Finding[]): void {
  for (const match of template.matchAll(/>([^<]+)</g)) {
    // Interpolations are code: their literals are scanned as such.
    const text = match[1]!.replace(/\{\{[\s\S]*?\}\}/g, ' ');
    if (french(text))
      found.push({ line: lineOf(source, offset + match.index + 1), text: text.trim() });
    for (const inner of match[1]!.matchAll(/\{\{([\s\S]*?)\}\}/g))
      scanCode(inner[1]!, offset + match.index + 1 + inner.index + 2, source, found);
  }
  // Static attributes (label="…"); a bound one (:label="…") is code.
  for (const match of template.matchAll(/(\s)([:@#]?)([\w.-]+)="([^"]*)"/g)) {
    const [, , bound, , value] = match;
    const at = offset + match.index;
    if (bound) scanCode(value!, at + match[0].indexOf('"') + 1, source, found);
    else if (french(value!)) found.push({ line: lineOf(source, at), text: match[0].trim() });
  }
}

/** The French text of one source file, `.vue` or `.ts`. */
export function scanSource(source: string, path: string): Finding[] {
  const found: Finding[] = [];
  if (path.endsWith('.vue')) {
    const template = /<template>([\s\S]*)<\/template>/.exec(source);
    if (template) {
      const start = template.index + '<template>'.length;
      scanTemplate(stripComments(template[1]!, true), start, source, found);
    }
    for (const script of source.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) {
      const start = script.index + script[0].indexOf('>') + 1;
      scanCode(stripComments(script[1]!, false), start, source, found);
    }
  } else {
    scanCode(stripComments(source, false), 0, source, found);
  }
  const lines = source.split('\n');
  return found.filter((f) => !lines[f.line - 1]?.includes('i18n-ignore'));
}
