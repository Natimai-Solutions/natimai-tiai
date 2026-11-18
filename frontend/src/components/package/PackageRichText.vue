<template>
  <!-- A catalogue sentence with some of its placeholders shown in bold or as
       code: the words around them follow the language, the marked values
       stay as they are (a publisher, a GPO value). -->
  <span>
    <template v-for="(part, i) in parts" :key="i">
      <b v-if="part.tag === 'b'">{{ part.text }}</b>
      <code v-else-if="part.tag === 'code'">{{ part.text }}</code>
      <template v-else>{{ part.text }}</template>
    </template>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';

const props = defineProps<{
  /** The catalogue key of the sentence. */
  path: string;
  /** Placeholders filled with plain text. */
  named?: Record<string, unknown>;
  /** Placeholders shown in bold. */
  bold?: Record<string, string>;
  /** Placeholders shown as code. */
  code?: Record<string, string>;
  /** The number that chooses the plural form, when the sentence has several. */
  plural?: number;
}>();

interface Part {
  tag: 'b' | 'code' | null;
  text: string;
}

// A marker no sentence holds: each marked placeholder becomes MARK + name +
// MARK, then the sentence is cut there.
const MARK = '\u0001';

const parts = computed<Part[]>(() => {
  const marks: Record<string, { tag: 'b' | 'code'; text: string }> = {};
  for (const [name, text] of Object.entries(props.bold ?? {})) marks[name] = { tag: 'b', text };
  for (const [name, text] of Object.entries(props.code ?? {})) marks[name] = { tag: 'code', text };
  const named: Record<string, unknown> = { ...props.named };
  for (const name of Object.keys(marks)) named[name] = `${MARK}${name}${MARK}`;
  const sentence =
    props.plural === undefined ? t(props.path, named) : t(props.path, named, props.plural);
  return sentence.split(MARK).map((piece, i) => {
    const mark = i % 2 === 1 ? marks[piece] : undefined;
    return mark ? { tag: mark.tag, text: mark.text } : { tag: null, text: piece };
  });
});
</script>
