/* Minimal markdown renderer for the agent's assessment.
 *
 * Deliberately not a library. The agent emits a narrow, known subset -
 * headings, bold, inline code, bullets, horizontal rules - and this streams
 * token by token, so it re-renders on every chunk. A full parser would be
 * ~40KB and slower per keystroke for syntax we never use.
 *
 * Inline code gets the mono treatment, which matters here: it is how IPs,
 * usernames, and hostnames read as telemetry rather than prose.
 */

/* Split on the inline constructs, keeping delimiters so they can be wrapped. */
function inline(text, keyPrefix) {
  const out = [];
  // `code` | **bold** | *italic*
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|(?<!\*)\*(?!\*)[^*]+\*(?!\*))/g;
  let last = 0;
  let m;
  let i = 0;

  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-i${i++}`;

    if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="md-code mono">
          {tok.slice(1, -1)}
        </code>
      );
    } else if (tok.startsWith("**")) {
      out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text, className = "" }) {
  if (!text) return null;

  const lines = String(text).split("\n");
  const blocks = [];
  let list = null; // accumulating bullet items

  const flushList = () => {
    if (!list) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="md-list">
        {list.map((item, i) => (
          <li key={i}>{inline(item, `l${blocks.length}-${i}`)}</li>
        ))}
      </ul>
    );
    list = null;
  };

  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      return;
    }

    // Horizontal rule
    if (/^(-{3,}|_{3,}|\*{3,})$/.test(trimmed)) {
      flushList();
      blocks.push(<hr key={`hr-${idx}`} className="md-rule" />);
      return;
    }

    // Heading. Level maps to our own scale, not h1-h6 - this sits inside a
    // card, so an <h1> here would be wrong for the document outline.
    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const depth = Math.min(heading[1].length, 4);
      blocks.push(
        <p key={`h-${idx}`} className={`md-h md-h${depth}`}>
          {inline(heading[2].replace(/\*\*/g, ""), `h${idx}`)}
        </p>
      );
      return;
    }

    // Bullet. The agent indents nested items; treat them as one flat list -
    // depth carries no meaning in these assessments.
    const bullet = trimmed.match(/^[*\-+]\s+(.*)$/);
    if (bullet) {
      (list ??= []).push(bullet[1]);
      return;
    }

    // Numbered item - rendered as a bullet with its marker preserved.
    const numbered = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
    if (numbered) {
      (list ??= []).push(`${numbered[1]}. ${numbered[2]}`);
      return;
    }

    flushList();
    blocks.push(
      <p key={`p-${idx}`} className="md-p">
        {inline(trimmed, `p${idx}`)}
      </p>
    );
  });

  flushList();

  return <div className={`md ${className}`}>{blocks}</div>;
}
