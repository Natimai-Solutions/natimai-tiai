/**
 * A catalogue's shape with its texts widened to `string`: what the English
 * of a domain is typed against, so that a key present in French and missing
 * in English — or the reverse — does not compile.
 */
export type Translation<T> = {
  [K in keyof T]: T[K] extends string ? string : Translation<T[K]>;
};
