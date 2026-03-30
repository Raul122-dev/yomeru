/**
 * Attempts to extract usable data from a partial/incomplete JSON string
 * as it's being streamed token by token from the model.
 *
 * Strategy:
 * 1. Try JSON.parse on the raw string (succeeds when complete)
 * 2. Try closing unclosed brackets/strings then parse
 * 3. Extract individual fields with regex as a last resort
 */

export interface PartialPageData {
  page_summary?: string;
  panel_count?: number;
  dialogues?: {
    panel_index: number;
    speaker_id: string | null;
    text: string;
    tone: string;
    bubble_type: string;
  }[];
  characters_seen?: {
    id: string;
    description: string;
    emotional_state: string;
    last_action: string;
    last_seen_page: number;
  }[];
  scene?: { location: string; mood: string; narrative_beat: string };
  reading_order?: number[];
}

export function parsePartialJson(raw: string): PartialPageData | null {
  if (!raw.trim()) return null;

  // strip model noise
  let s = raw
    .replace(/```json\n?/g, "")
    .replace(/```$/g, "")
    .replace(/<\|endoftext\|>.*/s, "")
    .replace(/<think>.*?<\/think>/gs, "")
    .trim();

  // try full parse first
  try {
    const parsed = JSON.parse(s);
    if (typeof parsed === "object" && parsed !== null)
      return parsed as PartialPageData;
  } catch {}

  // try closing the JSON structurally
  const closed = closeJson(s);
  if (closed) {
    try {
      const parsed = JSON.parse(closed);
      if (typeof parsed === "object" && parsed !== null)
        return parsed as PartialPageData;
    } catch {}
  }

  // fallback: extract individual fields via regex
  const result: PartialPageData = {};
  let found = false;

  const summary = extractString(s, "page_summary");
  if (summary) {
    result.page_summary = summary;
    found = true;
  }

  const mood = extractNestedString(s, "scene", "mood");
  const location = extractNestedString(s, "scene", "location");
  const beat = extractNestedString(s, "scene", "narrative_beat");
  if (mood || location || beat) {
    result.scene = {
      mood: mood ?? "",
      location: location ?? "",
      narrative_beat: beat ?? "",
    };
    found = true;
  }

  const panelCount = extractNumber(s, "panel_count");
  if (panelCount !== null) {
    result.panel_count = panelCount;
    found = true;
  }

  // try to extract completed dialogues
  const dialogues = extractDialogues(s);
  if (dialogues && dialogues.length > 0) {
    result.dialogues = dialogues;
    found = true;
  }

  return found ? result : null;
}

function extractString(s: string, key: string): string | undefined {
  const re = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`);
  const m = s.match(re);
  return m ? m[1].replace(/\\n/g, "\n").replace(/\\"/g, '"') : undefined;
}

function extractNestedString(
  s: string,
  obj: string,
  key: string,
): string | undefined {
  // find the object first, then extract key within it
  const objRe = new RegExp(`"${obj}"\\s*:\\s*\\{([^}]*)`);
  const objMatch = s.match(objRe);
  if (!objMatch) return undefined;
  return extractString(objMatch[1], key);
}

function extractNumber(s: string, key: string): number | null {
  const re = new RegExp(`"${key}"\\s*:\\s*(\\d+)`);
  const m = s.match(re);
  return m ? parseInt(m[1]) : null;
}

function extractDialogues(s: string): PartialPageData["dialogues"] {
  const results: NonNullable<PartialPageData["dialogues"]> = [];
  // find complete dialogue objects {...} within the dialogues array
  const arrMatch = s.match(/"dialogues"\s*:\s*\[([\s\S]*)/);
  if (!arrMatch) return results;

  const arr = arrMatch[1];
  // find fully closed objects
  let depth = 0,
    start = -1;
  for (let i = 0; i < arr.length; i++) {
    if (arr[i] === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (arr[i] === "}") {
      depth--;
      if (depth === 0 && start !== -1) {
        try {
          const obj = JSON.parse(arr.slice(start, i + 1));
          results.push({
            panel_index: obj.panel_index ?? 0,
            speaker_id: obj.speaker_id ?? null,
            text: obj.text ?? obj.text_verbatim ?? "",
            tone: obj.tone ?? "neutral",
            bubble_type: obj.bubble_type ?? "speech",
          });
        } catch {}
        start = -1;
      }
    }
  }
  return results;
}

function closeJson(s: string): string | null {
  // track stack of open brackets and string state
  const stack: string[] = [];
  let inStr = false;
  let escaped = false;

  for (const ch of s) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === "\\" && inStr) {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inStr = !inStr;
      continue;
    }
    if (inStr) continue;
    if (ch === "{" || ch === "[") stack.push(ch);
    else if (ch === "}") {
      if (stack[stack.length - 1] === "{") stack.pop();
    } else if (ch === "]") {
      if (stack[stack.length - 1] === "[") stack.pop();
    }
  }

  if (stack.length === 0 && !inStr) return null; // already valid (or fixable differently)

  let result = s.trim().replace(/,\s*$/, ""); // strip trailing comma
  if (inStr) result += '"';
  for (let i = stack.length - 1; i >= 0; i--) {
    result += stack[i] === "{" ? "}" : "]";
  }
  return result;
}
