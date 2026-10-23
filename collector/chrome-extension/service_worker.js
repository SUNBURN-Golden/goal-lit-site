/**
 * Goal Lit Chrome MV3 Service Worker (service_worker.js)
 *
 * 설계 원칙:
 * 1. 브라우저는 자료를 읽는 도구로만 동작하며, 대기열 관리·중복 제거·정규화는 로컬 작업기(127.0.0.1:8795)가 수행.
 * 2. Chrome 확장프로그램의 백그라운드 서비스워커는 언제든 종료될 수 있으므로(Service Worker Lifecycle),
 *    전송 큐(clipQueue)와 진행 위치(resumeCursor)를 chrome.storage.local에 영속 저장하고
 *    재기동/알람 시 중단 지점부터 즉시 재개한다.
 * 3. chrome.storage.local에 저장하기 전에도 반드시 1차 개인정보(PII) 필터를 거친다.
 */

const LOCAL_WORKER_BASE = "http://127.0.0.1:8795";
const ALARM_NAME = "goallit-flush-clip-queue";

function scrubPiiInBrowser(text) {
  if (!text) return "";
  return String(text)
    .replace(/\b\d{6}\s*[-~]\s*[1-8]\d{6}\b/g, "[REDACTED_RRN]")
    .replace(/(?:\+82[-\s]?10|01[016789]|02|0[3-6][1-5])[-\s.]?\d{3,4}[-\s.]?\d{4}\b/g, "[REDACTED_PHONE]")
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[REDACTED_EMAIL]")
    .replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, "[REDACTED_TOKEN]")
    .replace(/\b\d{1,4}동\s*\d{1,4}호\b/g, "[REDACTED_ADDRESS_UNIT]")
    .replace(/ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?/gi, "[UNTRUSTED_COMMAND_ISOLATED]")
    .replace(/이\s*명령을\s*실행하(?:고|라|세요)/g, "[UNTRUSTED_COMMAND_ISOLATED]");
}

function sanitizeClipPayload(raw) {
  return {
    brand: "goal-lit",
    url: scrubPiiInBrowser(raw.url || ""),
    title: scrubPiiInBrowser(raw.title || ""),
    outlet: scrubPiiInBrowser(raw.outlet || ""),
    published_at: scrubPiiInBrowser(raw.published_at || ""),
    target_work_slug: scrubPiiInBrowser(raw.target_work_slug || "general"),
    source_access_level: raw.source_access_level || "press_article",
    author_statement: scrubPiiInBrowser(raw.author_statement || ""),
    critical_thesis: scrubPiiInBrowser(raw.critical_thesis || ""),
    counter_argument: scrubPiiInBrowser(raw.counter_argument || ""),
    excerpt: scrubPiiInBrowser(raw.excerpt || "").slice(0, 600),
    evidence_locator: scrubPiiInBrowser(raw.evidence_locator || "activeTab_selection"),
    cursor_pos: scrubPiiInBrowser(raw.cursor_pos || `clipped_at_${Date.now()}`)
  };
}

async function getQueueState() {
  const data = await chrome.storage.local.get(["clipQueue", "resumeCursor"]);
  return {
    clipQueue: Array.isArray(data.clipQueue) ? data.clipQueue : [],
    resumeCursor: data.resumeCursor || 0
  };
}

async function saveQueueState(clipQueue, resumeCursor) {
  await chrome.storage.local.set({ clipQueue, resumeCursor, updatedAt: new Date().toISOString() });
}

async function flushQueueFromCursor() {
  const { clipQueue, resumeCursor } = await getQueueState();
  if (!clipQueue.length || resumeCursor >= clipQueue.length) {
    if (clipQueue.length && resumeCursor >= clipQueue.length) {
      await saveQueueState([], 0);
    }
    return { ok: true, flushed: 0, remaining: 0 };
  }

  let cursor = resumeCursor;
  let flushed = 0;

  while (cursor < clipQueue.length) {
    const item = sanitizeClipPayload(clipQueue[cursor]);
    try {
      const resp = await fetch(`${LOCAL_WORKER_BASE}/api/clip`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-GoalLit-Client": "chrome-mv3-clipper"
        },
        body: JSON.stringify(item)
      });
      if (!resp.ok) {
        break;
      }
      cursor += 1;
      flushed += 1;
      // 진행 위치(cursor)를 매 건마다 영속 저장하여 서비스워커가 중간에 종료되어도 중복/유실 없이 재개
      await saveQueueState(clipQueue, cursor);
    } catch (_err) {
      // 로컬 작업기가 일시 오프라인이면 현재 cursor를 유지하고 다음 알람/기동 시 재개
      break;
    }
  }

  if (cursor >= clipQueue.length) {
    await saveQueueState([], 0);
  }
  return { ok: true, flushed, remaining: Math.max(0, clipQueue.length - cursor) };
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  await flushQueueFromCursor();
});

chrome.runtime.onStartup.addListener(async () => {
  await flushQueueFromCursor();
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    await flushQueueFromCursor();
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "ENQUEUE_CLIP") {
    (async () => {
      const safeItem = sanitizeClipPayload(msg.payload || {});
      const { clipQueue, resumeCursor } = await getQueueState();
      clipQueue.push(safeItem);
      await saveQueueState(clipQueue, resumeCursor);
      const res = await flushQueueFromCursor();
      sendResponse({ ok: true, ...res });
    })();
    return true;
  }
  if (msg && msg.type === "RESUME_QUEUE") {
    (async () => {
      const res = await flushQueueFromCursor();
      sendResponse(res);
    })();
    return true;
  }
});
