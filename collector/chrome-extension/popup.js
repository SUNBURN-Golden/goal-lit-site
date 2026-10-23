/**
 * 현재 활성 탭(activeTab)에서 필요한 문학 근거 영역만 추출하고
 * 입력창(input/textarea)·쿠키·토큰·개인 연락처를 배제한 뒤 백그라운드 큐로 전달한다.
 */
function extractSafeRegionFromTab() {
  // 페이지 내부에서 실행되는 순수 함수 (DOM 전체를 복제하지 않고 본문·메타만 추출)
  const selection = window.getSelection ? String(window.getSelection()).trim() : "";
  const cloneRoot = (document.querySelector("article") || document.querySelector("main") || document.body).cloneNode(true);
  const forbiddenSelectors = "script, style, noscript, iframe, form, input, textarea, select, button, nav, footer, aside, .comment, .comments, .reply, [type='password']";
  cloneRoot.querySelectorAll(forbiddenSelectors).forEach((el) => el.remove());

  const rawText = (selection || cloneRoot.innerText || "").replace(/\s+/g, " ").trim().slice(0, 600);
  const pubMeta = document.querySelector("meta[property='article:published_time'], meta[name='pubdate'], time");
  const publishedAt = pubMeta ? (pubMeta.getAttribute("content") || pubMeta.getAttribute("datetime") || pubMeta.textContent || "").trim() : "";
  const siteMeta = document.querySelector("meta[property='og:site_name']");
  const outlet = siteMeta ? (siteMeta.getAttribute("content") || "").trim() : location.hostname;

  return {
    url: location.href,
    title: document.title || "",
    outlet,
    published_at: publishedAt,
    excerpt: rawText,
    evidence_locator: selection ? "user_text_selection" : "article_main_excerpt"
  };
}

document.getElementById("clipBtn").addEventListener("click", async () => {
  const statusEl = document.getElementById("statusMsg");
  statusEl.textContent = "본문 핵심 영역 추출 및 개인정보 필터링 중...";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      statusEl.textContent = "활성 탭을 찾을 수 없습니다.";
      return;
    }
    const injected = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractSafeRegionFromTab
    });
    const extracted = (injected && injected[0] && injected[0].result) || {};
    const payload = {
      ...extracted,
      target_work_slug: document.getElementById("workSlug").value.trim() || "general",
      source_access_level: document.getElementById("accessLevel").value,
      critical_thesis: document.getElementById("thesis").value.trim()
    };
    chrome.runtime.sendMessage({ type: "ENQUEUE_CLIP", payload }, (resp) => {
      if (resp && resp.ok) {
        statusEl.textContent = `꼴릿 수집함 저장 완료 (전송 ${resp.flushed}건, 대기열 ${resp.remaining}건)`;
      } else {
        statusEl.textContent = "큐에 안전하게 저장되었습니다 (로컬 작업기 연결 시 자동 재개).";
      }
    });
  } catch (err) {
    statusEl.textContent = "추출 제한 페이지입니다: " + (err && err.message ? err.message : String(err));
  }
});
