(() => {
  const micBtn = document.getElementById("mic-btn");
  const listeningEl = document.getElementById("listening");
  const phoneHelp = document.getElementById("phone-help");
  const textarea = document.getElementById("transcript");
  const submitBtn = document.getElementById("submit-btn");
  const statusEl = document.getElementById("status");
  const secretBox = document.getElementById("secret-box");
  const remoteSecretEl = document.getElementById("remote-secret");
  const secretSaveBtn = document.getElementById("secret-save");
  const SECRET_KEY = "voiceSharedSecret";

  function buildApiHeaders() {
    const headers = { "Content-Type": "application/json" };
    const secret = sessionStorage.getItem(SECRET_KEY);
    if (secret) headers["X-Voice-Secret"] = secret;
    return headers;
  }

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  let recognition = null;
  let wantListen = false;
  let recognizing = false;
  let lastToggleAt = 0;
  let sessionBase = "";

  function setStatus(message, kind) {
    statusEl.textContent = message;
    statusEl.classList.remove("ok", "err");
    if (kind) statusEl.classList.add(kind);
  }

  function setListeningUi(on) {
    recognizing = on;
    listeningEl.classList.toggle("hidden", !on);
    micBtn.classList.toggle("listening", on);
    micBtn.setAttribute("aria-pressed", on ? "true" : "false");
    micBtn.textContent = on ? "⏹ 音声入力を停止" : "🎤 音声入力開始";
  }

  function compactSpeech(text) {
    return String(text || "").replace(/\s+/g, "");
  }

  function mergeSpeechChunk(prev, next, breakIfDistinct) {
    const a = String(prev || "");
    const b = String(next || "");
    if (!b) return a;
    if (!a) return b;
    const aC = compactSpeech(a);
    const bC = compactSpeech(b);
    if (!aC) return b;
    if (!bC) return a;
    if (bC === aC) return b.length >= a.length ? b : a;
    if (bC.startsWith(aC)) return b;
    if (aC.startsWith(bC)) return a;
    if (bC.includes(aC)) return b;
    if (aC.includes(bC)) return a;
    const max = Math.min(aC.length, bC.length);
    for (let n = max; n >= 2; n -= 1) {
      if (aC.endsWith(bC.slice(0, n))) {
        return aC + bC.slice(n);
      }
    }
    if (breakIfDistinct) {
      const sep = /\n$/.test(a) || /^\n/.test(b) ? "" : "\n";
      return a + sep + b;
    }
    return a + b;
  }

  function collapseSpeechStutter(text) {
    const compact = compactSpeech(text);
    if (compact.length < 6) return text;
    for (let len = Math.min(16, Math.floor(compact.length / 2)); len >= 2; len -= 1) {
      const prefix = compact.slice(0, len);
      if (compact.slice(len, len * 2) === prefix && compact.length > len * 2) {
        return collapseSpeechStutter(compact.slice(len));
      }
    }
    return compact === compactSpeech(text) ? text : compact;
  }

  function heardFromResults(results) {
    let merged = "";
    for (let i = 0; i < results.length; i += 1) {
      merged = mergeSpeechChunk(merged, results[i][0].transcript, false);
    }
    return collapseSpeechStutter(merged);
  }

  function writeHeardText(sessionText) {
    textarea.value = mergeSpeechChunk(sessionBase, collapseSpeechStutter(sessionText), true);
  }

  function rememberSessionBase() {
    sessionBase = textarea.value || "";
    textarea.dataset.base = sessionBase;
  }

  function goSecureAndStart() {
    const url = new URL(location.href);
    url.protocol = "https:";
    url.searchParams.set("autostart", "1");
    location.replace(url.toString());
  }

  function bindRecognition(instance) {
    instance.lang = "ja-JP";
    instance.interimResults = true;
    instance.continuous = true;
    instance.maxAlternatives = 1;

    instance.onstart = () => {
      rememberSessionBase();
      setListeningUi(true);
    };

    instance.onresult = (event) => {
      writeHeardText(heardFromResults(event.results));
    };

    instance.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        wantListen = false;
        setListeningUi(false);
        setStatus("❌ マイクを許可してください。", "err");
        return;
      }
      if (event.error === "aborted") {
        return;
      }
      if (event.error !== "no-speech") {
        setStatus("❌ 音声認識でエラーが発生しました", "err");
      }
    };

    instance.onend = () => {
      rememberSessionBase();
      if (!wantListen) {
        setListeningUi(false);
        return;
      }
      window.setTimeout(() => {
        if (!wantListen) {
          setListeningUi(false);
          return;
        }
        try {
          instance.start();
        } catch (err) {
          wantListen = false;
          setListeningUi(false);
        }
      }, 120);
    };
  }

  function createRecognition() {
    const instance = new SpeechRecognition();
    bindRecognition(instance);
    return instance;
  }

  function startLiveSpeech() {
    if (!SpeechRecognition) {
      setStatus("❌ このブラウザでは自動音声入力を利用できません。", "err");
      return;
    }
    setStatus("");
    rememberSessionBase();
    wantListen = true;
    setListeningUi(true);
    try {
      if (!recognition) {
        recognition = createRecognition();
      }
      recognition.start();
    } catch (err) {
      wantListen = false;
      setListeningUi(false);
      setStatus("❌ 音声認識を開始できませんでした", "err");
    }
  }

  function stopVoiceInput() {
    wantListen = false;
    setListeningUi(false);
    if (recognition) {
      try {
        recognition.stop();
      } catch (err) {
        /* ignore */
      }
    }
  }

  function toggleVoiceInput() {
    const now = Date.now();
    if (now - lastToggleAt < 350) {
      return;
    }
    lastToggleAt = now;
    if (wantListen || recognizing) {
      stopVoiceInput();
      return;
    }
    if (!window.isSecureContext) {
      setStatus("音声入力を開始します…");
      goSecureAndStart();
      return;
    }
    startLiveSpeech();
  }

  if (phoneHelp) {
    phoneHelp.classList.add("hidden");
  }

  secretSaveBtn?.addEventListener("click", () => {
    const value = (remoteSecretEl && remoteSecretEl.value ? remoteSecretEl.value : "").trim();
    if (value) sessionStorage.setItem(SECRET_KEY, value);
    else sessionStorage.removeItem(SECRET_KEY);
    if (remoteSecretEl) remoteSecretEl.value = "";
    setStatus(value ? "✅ この端末にパスワードを保存しました" : "パスワードを消しました", value ? "ok" : "");
  });

  fetch("/api/config")
    .then((res) => res.json())
    .then((cfg) => {
      if (cfg && cfg.secret_required && secretBox) {
        secretBox.classList.remove("hidden");
        secretBox.open = true;
      }
    })
    .catch(() => {});

  const autostart = new URLSearchParams(location.search).get("autostart") === "1";
  if (autostart && window.isSecureContext && SpeechRecognition) {
    window.setTimeout(startLiveSpeech, 250);
  }

  micBtn.addEventListener("click", (event) => {
    event.preventDefault();
    toggleVoiceInput();
  });
  micBtn.addEventListener(
    "touchend",
    (event) => {
      event.preventDefault();
      toggleVoiceInput();
    },
    { passive: false }
  );

  submitBtn.addEventListener("click", async () => {
    const text = (textarea.value || "").trim();
    if (!text) {
      setStatus("❌ 登録する文章を入力してください", "err");
      return;
    }
    stopVoiceInput();
    submitBtn.disabled = true;
    setStatus("登録中…");
    try {
      const res = await fetch("/api/notion/add-task", {
        method: "POST",
        headers: buildApiHeaders(),
        body: JSON.stringify({ text }),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (e) {
        data = {};
      }
      if (res.ok && data.ok) {
        setStatus("✅ Notionに登録しました", "ok");
        textarea.value = "";
        delete textarea.dataset.base;
        const url = new URL(location.href);
        if (url.searchParams.has("autostart")) {
          url.searchParams.delete("autostart");
          history.replaceState({}, "", url.toString());
        }
      } else if (res.status === 401) {
        if (secretBox) secretBox.classList.remove("hidden");
        setStatus("❌ 接続用パスワードを保存してから、もう一度登録してください", "err");
      } else {
        setStatus("❌ Notionへの登録に失敗しました", "err");
      }
    } catch (err) {
      setStatus("❌ Notionへの登録に失敗しました", "err");
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
