(function () {
  var statusEl = document.getElementById("auth-status");
  var boxEl = document.getElementById("auth-box");
  if (!statusEl || !boxEl) return;
  var params = new URLSearchParams(window.location.search);
  if (params.get("welcome") === "1") {
    var nl = params.get("newsletter") === "1";
    statusEl.textContent = nl
      ? "가입과 주간 뉴스레터 구독 신청이 완료되었어요."
      : "가입이 완료되었어요. 원하실 때 언제든 뉴스레터 구독을 켤 수 있어요.";
  } else if (params.get("status") === "pending_config") {
    statusEl.textContent = "Google 로그인 연동 키를 연결하는 중이에요. 잠시 뒤 다시 시도해 주세요.";
  } else if (params.get("logged_out") === "1") {
    statusEl.textContent = "로그아웃되었어요.";
  }
  fetch("/api/auth/me", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || !data.member) return;
      var m = data.member;
      var checked = m.newsletter_opt_in ? " checked" : "";
      boxEl.innerHTML =
        '<div class="auth-member">' +
        '<p><strong>' + (m.email || "회원") + '</strong> 계정으로 로그인되어 있어요.</p>' +
        '<form method="POST" action="/api/auth/newsletter" class="auth-form">' +
        '<label class="auth-check"><input type="checkbox" name="newsletter" value="1"' + checked + '>' +
        '<span><strong>매주 화요일 &lsquo;한 작품·한 비평&rsquo; 뉴스레터 받기</strong></span></label>' +
        '<div class="cta-row"><button type="submit" class="cta cta-main auth-btn">구독 설정 저장</button></div>' +
        '</form>' +
        '<p class="muted auth-note"><a href="/api/auth/logout">로그아웃</a></p>' +
        '</div>';
    })
    .catch(function () {});
})();
