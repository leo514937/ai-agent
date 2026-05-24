<template>
  <div class="assistant-markdown">
    <template v-for="(block, index) in blocks" :key="`${block.type}-${index}`">
      <h1 v-if="block.type === 'heading' && block.level === 1" class="assistant-markdown__h1" v-html="block.html" />
      <h2 v-else-if="block.type === 'heading' && block.level === 2" class="assistant-markdown__h2" v-html="block.html" />
      <h3 v-else-if="block.type === 'heading' && block.level === 3" class="assistant-markdown__h3" v-html="block.html" />

      <p v-else-if="block.type === 'paragraph'" class="assistant-markdown__p" v-html="block.html" />

      <blockquote v-else-if="block.type === 'quote'" class="assistant-markdown__quote" v-html="block.html" />

      <ul v-else-if="block.type === 'ul'" class="assistant-markdown__list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex" class="assistant-markdown__list-item" v-html="item.html" />
      </ul>

      <ol v-else-if="block.type === 'ol'" class="assistant-markdown__list assistant-markdown__list--ordered">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex" class="assistant-markdown__list-item" v-html="item.html" />
      </ol>

      <div v-else-if="block.type === 'code'" class="assistant-markdown__code">
        <div class="assistant-markdown__code-head">
          <span class="assistant-markdown__code-lang">{{ block.language || 'text' }}</span>
          <button class="assistant-markdown__copy" type="button" @click="copyCode(block.code)">
            {{ copiedKey === block.key ? '已复制' : '复制' }}
          </button>
        </div>
        <pre class="assistant-markdown__code-pre"><code>{{ block.code }}</code></pre>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  content: {
    type: String,
    default: '',
  },
});

const copiedKey = ref('');

const blocks = computed(() => parseMarkdown(props.content));

function escapeHtml(value = '') {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttribute(value = '') {
  return escapeHtml(value).replace(/`/g, '&#96;');
}

function sanitizeUrl(value = '') {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }

  if (/^(https?:\/\/|mailto:|\/|#)/i.test(raw)) {
    return raw;
  }

  return '';
}

function renderInline(value = '') {
  const tokens = [];
  let html = escapeHtml(value);

  html = html.replace(/`([^`]+)`/g, (_match, code) => {
    const token = `@@CODE_${tokens.length}@@`;
    tokens.push(`<code class="assistant-markdown__inline-code">${code}</code>`);
    return token;
  });

  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, url) => {
    const safeUrl = sanitizeUrl(url);
    if (!safeUrl) {
      return match;
    }

    const token = `@@LINK_${tokens.length}@@`;
    tokens.push(
      `<a class="assistant-markdown__link" href="${escapeAttribute(safeUrl)}" target="_blank" rel="noreferrer">${label}</a>`,
    );
    return token;
  });

  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
  html = html.replace(/@@(?:CODE|LINK)_(\d+)@@/g, (_match, index) => tokens[Number(index)] || '');
  html = html.replace(/\n/g, '<br />');

  return html;
}

function flushParagraph(blocksList, paragraph) {
  if (!paragraph.length) {
    return;
  }

  blocksList.push({
    type: 'paragraph',
    html: renderInline(paragraph.join('\n').trim()),
  });
  paragraph.length = 0;
}

function flushList(blocksList, listState) {
  if (!listState.items.length) {
    return;
  }

  blocksList.push({
    type: listState.type,
    items: listState.items.map((item) => ({ html: renderInline(item) })),
  });
  listState.items = [];
  listState.type = '';
}

function flushQuote(blocksList, quoteLines) {
  if (!quoteLines.length) {
    return;
  }

  blocksList.push({
    type: 'quote',
    html: renderInline(quoteLines.join('\n').trim()),
  });
  quoteLines.length = 0;
}

function parseMarkdown(content = '') {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n');
  const blocksList = [];
  const paragraph = [];
  const quoteLines = [];
  const listState = {
    type: '',
    items: [],
  };
  let codeBlock = null;

  const flushAll = () => {
    flushParagraph(blocksList, paragraph);
    flushList(blocksList, listState);
    flushQuote(blocksList, quoteLines);
  };

  for (const line of lines) {
    const trimmedEnd = line.replace(/\s+$/g, '');
    const trimmed = trimmedEnd.trim();

    if (codeBlock) {
      if (/^```/.test(trimmed)) {
        blocksList.push({
          type: 'code',
          key: `${codeBlock.language || 'text'}-${blocksList.length}`,
          language: codeBlock.language,
          code: codeBlock.lines.join('\n'),
        });
        codeBlock = null;
      } else {
        codeBlock.lines.push(trimmedEnd);
      }
      continue;
    }

    const fenceMatch = trimmed.match(/^```([^\s`]+)?\s*$/);
    if (fenceMatch) {
      flushAll();
      codeBlock = {
        language: fenceMatch[1] || '',
        lines: [],
      };
      continue;
    }

    if (!trimmed) {
      flushAll();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      flushAll();
      blocksList.push({
        type: 'heading',
        level: headingMatch[1].length,
        html: renderInline(headingMatch[2].trim()),
      });
      continue;
    }

    const unorderedMatch = trimmed.match(/^\s*[-*+]\s+(.*)$/);
    if (unorderedMatch) {
      flushParagraph(blocksList, paragraph);
      flushQuote(blocksList, quoteLines);
      if (listState.type && listState.type !== 'ul') {
        flushList(blocksList, listState);
      }
      listState.type = 'ul';
      listState.items.push(unorderedMatch[1].trim());
      continue;
    }

    const orderedMatch = trimmed.match(/^\s*\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph(blocksList, paragraph);
      flushQuote(blocksList, quoteLines);
      if (listState.type && listState.type !== 'ol') {
        flushList(blocksList, listState);
      }
      listState.type = 'ol';
      listState.items.push(orderedMatch[1].trim());
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph(blocksList, paragraph);
      flushList(blocksList, listState);
      quoteLines.push(quoteMatch[1]);
      continue;
    }

    flushList(blocksList, listState);
    flushQuote(blocksList, quoteLines);
    paragraph.push(trimmedEnd);
  }

  flushAll();

  if (codeBlock) {
    blocksList.push({
      type: 'code',
      key: `${codeBlock.language || 'text'}-${blocksList.length}`,
      language: codeBlock.language,
      code: codeBlock.lines.join('\n'),
    });
  }

  return blocksList;
}

async function copyCode(content) {
  const text = String(content || '').trim();
  if (!text) {
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    copiedKey.value = text;
    window.setTimeout(() => {
      if (copiedKey.value === text) {
        copiedKey.value = '';
      }
    }, 1200);
  } catch {
    copiedKey.value = '';
  }
}
</script>

<style scoped>
.assistant-markdown {
  display: grid;
  gap: 0.95rem;
  min-width: 0;
  color: var(--text);
  font-size: 17px;
  line-height: 1.7;
}

.assistant-markdown__h1,
.assistant-markdown__h2,
.assistant-markdown__h3,
.assistant-markdown__p,
.assistant-markdown__quote {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.assistant-markdown__h1 {
  font-size: 1.5rem; /* text-2xl */
  line-height: 1.2;
  font-weight: 700; /* font-bold */
}

.assistant-markdown__h2 {
  font-size: 1.25rem; /* text-xl */
  line-height: 1.25;
  font-weight: 700; /* font-bold */
}

.assistant-markdown__h3 {
  font-size: 1.125rem; /* text-lg */
  line-height: 1.35;
  font-weight: 600; /* font-semibold */
}

.assistant-markdown__p {
  font-size: 17px;
  line-height: 1.7;
  white-space: normal;
}

.assistant-markdown__quote {
  padding: 0.95rem 1rem;
  border-left: 4px solid var(--primary-soft);
  border-radius: 0 18px 18px 0;
  background: var(--surface-muted);
  color: var(--text-soft);
  font-size: 17px;
  line-height: 1.7;
  font-style: italic;
}

.assistant-markdown__list {
  margin: 0;
  padding-left: 1.4rem;
}

.assistant-markdown__list--ordered {
  padding-left: 1.5rem;
}

.assistant-markdown__list-item {
  margin: 0.28rem 0;
  padding-left: 0.1rem;
  font-size: 17px;
  line-height: 1.7;
}

.assistant-markdown__code {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface-strong);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.assistant-markdown__code-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent),
    var(--surface-muted);
}

.assistant-markdown__code-lang {
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 850;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.assistant-markdown__copy {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-soft);
  font-size: 0.76rem;
  font-weight: 800;
}

.assistant-markdown__copy:hover {
  color: var(--text);
}

.assistant-markdown__code-pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 14px 16px;
  background: var(--surface-strong);
}

.assistant-markdown__code-pre code {
  display: block;
  white-space: pre;
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 13px; /* text-[13px] */
  line-height: 1.625; /* leading-relaxed */
  font-weight: 400;
}

.assistant-markdown__inline-code {
  padding: 0.15rem 0.38rem;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--surface-muted);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 0.92em; /* text-[0.92em] */
  font-weight: 400;
}

.assistant-markdown__link {
  color: var(--primary-strong);
  font-weight: 700; /* font-bold */
  text-decoration: underline;
  text-decoration-color: rgba(31, 41, 55, 0.28);
  text-underline-offset: 0.18em;
}

.assistant-markdown__link:hover {
  text-decoration-color: currentColor;
}

.assistant-markdown :deep(strong) {
  font-weight: 900; /* font-black */
}

.assistant-markdown :deep(em) {
  font-style: italic;
}

/* Table styles */
.assistant-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem; /* text-sm */
  margin: 0.5rem 0;
}

.assistant-markdown :deep(th) {
  font-weight: 700;
  font-size: 11px;
  text-transform: uppercase;
  border-bottom: 2px solid var(--line);
  padding: 8px;
  text-align: left;
}

.assistant-markdown :deep(td) {
  padding: 8px;
  border-bottom: 1px solid var(--line);
}

@media (max-width: 720px) {
  .assistant-markdown {
    font-size: 16px;
  }

  .assistant-markdown__h1 {
    font-size: 1.4rem;
  }

  .assistant-markdown__h2 {
    font-size: 1.2rem;
  }
}
</style>
