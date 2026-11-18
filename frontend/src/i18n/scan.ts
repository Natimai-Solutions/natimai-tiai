import ts from 'typescript';
import { parse } from 'vue/compiler-sfc';
import { en, fr } from './messages';
import errorCodes from './messages/errorCodes';

/**
 * Finds interface text written in French outside the catalogues (plan
 * `dev/plan-console-bilingue.md`, I6): what an English reader would still
 * read in French.
 *
 * A heuristic, run by `noHardcodedFrench.spec.ts` over every source file:
 * comments are left out, then a string literal, an attribute value or a
 * template text counts as French when it holds a French letter or
 * punctuation (é, à, ç, «, »…), a French function word between spaces
 * (« de », « en », « par »…), or a word of the console's French that its
 * English never uses — the vocabulary of the catalogues themselves
 * (« Inventaire », « inconnues »), a lone word only when capitalised as a
 * label is. Identifiers, keys and CSS classes hold none of these. A line that must keep French text (a regular expression that
 * reads a French server message, say) says so with `i18n-ignore`.
 *
 * Sources are read by the parsers that compile them — Vue's for a `.vue`
 * file (every `<template>`, whatever its `lang`, attributes in any quoting),
 * TypeScript's for code — so that what the scan sees is what the reader does.
 */

const FRENCH_CHARS = /[àâäçéèêëîïôöûùüÿœæÀÂÇÉÈÊËÎÏÔÛÙÜŸŒÆ«»]/;
const FRENCH_WORDS =
  /(^|[\s'(«])(le|la|les|des|du|de|en|par|un|une|aucun|aucune|est|sont|pas|pour|avec|sans|dans|sur|sous|ou|et|au|aux|ce|cette|ces|qui|que|ne|plus|votre|vos|nous|vous|leur|leurs|mot|poste|postes|salle|salles|paquet|paquets|jour|jours|heure|heures|oui|non|enregistrer|annuler|supprimer|fermer|modifier|ajouter|chargement|erreur)(?=[\s.,;:!?)»]|$)/i;

// Words that stand alone as a label (« Postes », « Nom ») and are not English.
const FRENCH_LABELS = new Set(
  (
    'poste postes nom noms groupe groupes utilisateur utilisateurs logiciels logiciel paquet paquets ' +
    'salle salles emplacement emplacements commandes commande menaces menace fichiers fichier ' +
    'actualiser rechercher recherche filtres filtre colonnes exporter valider retour statut adresse ' +
    'compte comptes journal connexion oui non aucun aucune inconnu inconnue inconnus inconnues ' +
    'domaine fabricant stockage enregistrer annuler supprimer fermer modifier ajouter retirer ' +
    'choisir chargement erreur tous toutes heure jours mois semaine taille total affecter clore ' +
    'envoyer paramètres sélection effacer détails afficher masquer suivant précédent inventaire'
  ).split(' '),
);

type Tree = string | { [key: string]: Tree };

function words(tree: Tree, into: Set<string>): Set<string> {
  if (typeof tree === 'string') {
    // Placeholders ({count}) and the vue-i18n syntax are not words.
    for (const word of tree.replace(/\{[^}]*\}/g, ' ').match(/\p{L}+/gu) ?? [])
      into.add(word.toLowerCase());
  } else for (const value of Object.values(tree)) words(value, into);
  return into;
}

/**
 * The console's French vocabulary: the words of its French catalogues that
 * its English ones never use. Short words are left to `FRENCH_WORDS`, which
 * knows which of them are French; a longer one the two languages share
 * (« session ») is in the English catalogue too, and so not here.
 */
const FRENCH_VOCABULARY = (() => {
  const english = words(en, words(errorCodes.en, new Set()));
  const french = words(fr, words(errorCodes.fr, new Set()));
  return new Set([...french].filter((w) => w.length >= 4 && !english.has(w)));
})();

export interface Finding {
  line: number;
  text: string;
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split('\n').length;
}

/**
 * Whether a word is of the vocabulary, as written or as the singular — and
 * masculine — of what the catalogues write (« inconnues » of « inconnu »).
 */
function inVocabulary(word: string): boolean {
  return [word, word.replace(/s$/, ''), word.replace(/e?s?$/, '')].some(
    (w) => w.length >= 4 && FRENCH_VOCABULARY.has(w),
  );
}

/** A word of the text, without the punctuation around it. */
function bare(word: string): string {
  return word.replace(/^[^\p{L}]+|[^\p{L}]+$/gu, '').toLowerCase();
}

function french(text: string): boolean {
  const plain = text.trim();
  if (!plain) return false;
  if (FRENCH_CHARS.test(plain)) return true;
  if (/\s/.test(plain))
    return (
      FRENCH_WORDS.test(plain) ||
      plain.split(/\s+/).some((w) => /^\p{L}+[.,;:!?…]*$/u.test(w) && inVocabulary(bare(w)))
    );
  // A lone word: a label (« Inventaire »), not a key, a path or a class. A
  // word of the vocabulary counts when capitalised as a label is: lowercase,
  // it is as likely a key the code names (`'diagnostic'`).
  if (!/^\p{L}+[.:…]*$/u.test(plain)) return false;
  const word = bare(plain);
  return FRENCH_LABELS.has(word) || (/^\p{Lu}/u.test(plain) && inVocabulary(word));
}

/**
 * String literals of TypeScript code, template literals included (their
 * substitutions read as a blank), as TypeScript's own parser sees them:
 * comments, regular expressions and nested templates cannot mislead it.
 */
function scanCode(code: string, offset: number, source: string, found: Finding[]): void {
  const file = ts.createSourceFile('scan.ts', code, ts.ScriptTarget.Latest, true);
  const visit = (node: ts.Node): void => {
    let text: string | null = null;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) text = node.text;
    else if (ts.isTemplateExpression(node))
      text = [node.head.text, ...node.templateSpans.map((s) => s.literal.text)].join(' ');
    if (text !== null && french(text))
      found.push({ line: lineOf(source, offset + node.getStart(file)), text: node.getText(file) });
    ts.forEachChild(node, visit);
  };
  visit(file);
}

// What the template parser hands back, as far as the scan reads it
// (`NodeTypes` of `@vue/compiler-core`).
const ELEMENT = 1;
const TEXT = 2;
const SIMPLE_EXPRESSION = 4;
const INTERPOLATION = 5;
const ATTRIBUTE = 6;
const DIRECTIVE = 7;

interface Located {
  loc: { start: { offset: number }; source: string };
}
interface Expression extends Located {
  type: number;
  content: string;
}
interface Prop extends Located {
  type: number;
  name: string;
  value?: { content: string } & Located;
  exp?: Expression;
}
interface TemplateNode extends Located {
  type: number;
  content?: string | Expression;
  props?: Prop[];
  children?: TemplateNode[];
}

/** An expression of the template is code: its literals are scanned as such. */
function scanExpression(exp: Expression | undefined, source: string, found: Finding[]): void {
  if (exp?.type === SIMPLE_EXPRESSION) scanCode(exp.content, exp.loc.start.offset, source, found);
}

/**
 * Text between tags — a run of text and interpolations read as one, as the
 * reader sees it — and attribute values, of a Vue template.
 */
function scanTemplate(node: TemplateNode, source: string, found: Finding[]): void {
  if (node.type === ELEMENT)
    for (const prop of node.props ?? []) {
      if (prop.type === ATTRIBUTE && prop.value && french(prop.value.content))
        found.push({ line: lineOf(source, prop.loc.start.offset), text: prop.loc.source });
      // A bound attribute (:label="…"), an event or a slot is code.
      else if (prop.type === DIRECTIVE) scanExpression(prop.exp, source, found);
    }
  let run: { text: string; offset: number } | null = null;
  const flush = () => {
    if (run && french(run.text))
      found.push({ line: lineOf(source, run.offset), text: run.text.trim() });
    run = null;
  };
  for (const child of node.children ?? []) {
    if (child.type === TEXT || child.type === INTERPOLATION) {
      const text = child.type === TEXT ? (child.content as string) : ' ';
      if (run) run.text += text;
      // The line of the run's first word, not of the newline before it.
      else run = { text, offset: child.loc.start.offset + text.search(/\S|$/) };
      if (child.type === INTERPOLATION) scanExpression(child.content as Expression, source, found);
    } else {
      flush();
      scanTemplate(child, source, found);
    }
  }
  flush();
}

/** The French text of one source file, `.vue` or `.ts`. */
export function scanSource(source: string, path: string): Finding[] {
  const found: Finding[] = [];
  if (path.endsWith('.vue')) {
    const { descriptor } = parse(source, { filename: path });
    const ast = descriptor.template?.ast as unknown as TemplateNode | undefined;
    if (ast) scanTemplate(ast, source, found);
    for (const script of [descriptor.script, descriptor.scriptSetup])
      if (script) scanCode(script.content, script.loc.start.offset, source, found);
  } else {
    scanCode(source, 0, source, found);
  }
  const lines = source.split('\n');
  return found.filter((f) => !lines[f.line - 1]?.includes('i18n-ignore'));
}
