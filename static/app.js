(() => {
  const micBtn = document.getElementById("mic-btn");
  const listeningEl = document.getElementById("listening");
  const phoneHelp = document.getElementById("phone-help");
  const textarea = document.getElementById("transcript");
  const submitBtn = document.getElementById("submit-btn");
  const statusEl = document.getElementById("status");
  const secretBox = document.getElementById("secret-box");
  const secretForm = document.getElementById("secret-form");
  const secretSavedEl = document.getElementById("secret-saved");
  const secretChangeBtn = document.getElementById("secret-change");
  const remoteSecretEl = document.getElementById("remote-secret");
  const secretSaveBtn = document.getElementById("secret-save");
  const SECRET_KEY = "voiceSharedSecret";
  const COOKIE_KEY = "vn_secret";

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  let recognition = null;
  let wantListen = false;
  let recognizing = false;
  let lastToggleAt = 0;
  let sessionBase = "";
  let mediaRecorder = null;
  let recordedChunks = [];
  let mediaStream = null;
  let recording = false;
  let transcribing = false;

  function isIOS() {
    const ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function canUseBrowserSpeech() {
    return Boolean(SpeechRecognition) && window.isSecureContext && !isIOS();
  }

  function cookieSecret() {
    const parts = document.cookie ? document.cookie.split(";") : [];
    for (let i = 0; i < parts.length; i += 1) {
      const piece = parts[i].trim();
      const eq = piece.indexOf("=");
      if (eq === -1) continue;
      if (piece.slice(0, eq) === COOKIE_KEY) {
        try {
          return decodeURIComponent(piece.slice(eq + 1));
        } catch (err) {
          return "";
        }
      }
    }
    return "";
  }

  function writeCookieSecret(value) {
    const secure = location.protocol === "https:" ? "; Secure" : "";
    if (!value) {
      document.cookie = COOKIE_KEY + "=; Max-Age=0; Path=/" + secure + "; SameSite=Lax";
      return;
    }
    document.cookie =
      COOKIE_KEY + "=" + encodeURIComponent(value) + "; Max-Age=31536000; Path=/" + secure + "; SameSite=Lax";
  }

  function storageGet() {
    try {
      return localStorage.getItem(SECRET_KEY) || "";
    } catch (err) {
      return "";
    }
  }

  function storageSet(value) {
    try {
      if (value) localStorage.setItem(SECRET_KEY, value);
      else localStorage.removeItem(SECRET_KEY);
    } catch (err) {
      /* Android の制限で localStorage が使えないことがある */
    }
  }

  function readSecret() {
    const stored = storageGet();
    if (stored) return stored;
    const fromCookie = cookieSecret();
    if (fromCookie) {
      storageSet(fromCookie);
      return fromCookie;
    }
    try {
      const legacy = sessionStorage.getItem(SECRET_KEY);
      if (legacy) {
        writeSecret(legacy);
        sessionStorage.removeItem(SECRET_KEY);
        return legacy;
      }
    } catch (err) {
      /* ignore */
    }
    return "";
  }

  function writeSecret(value) {
    storageSet(value);
    writeCookieSecret(value);
    try {
      sessionStorage.removeItem(SECRET_KEY);
    } catch (err) {
      /* ignore */
    }
  }

  function secretHeaders() {
    const headers = {};
    const secret = readSecret();
    if (secret) headers["X-Voice-Secret"] = secret;
    return headers;
  }

  function refreshSecretBox() {
    if (!secretBox) return;
    const saved = Boolean(readSecret());
    if (secretSavedEl) secretSavedEl.classList.toggle("hidden", !saved);
    if (secretForm) secretForm.classList.toggle("hidden", saved);
    secretBox.classList.toggle("hidden", saved);
    if (secretChangeBtn) secretChangeBtn.classList.toggle("hidden", !saved);
  }

  function buildApiHeaders() {
    return { "Content-Type": "application/json", ...secretHeaders() };
  }

  function setStatus(message, kind) {
    statusEl.textContent = message;
    statusEl.classList.remove("ok", "err");
    if (kind) statusEl.classList.add(kind);
  }

  function setListeningUi(on, label) {
    recognizing = on;
    listeningEl.textContent = label || "🎙 音声入力中…";
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

  function pickRecorderMime() {
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/aac"];
    if (!window.MediaRecorder) return "";
    for (let i = 0; i < types.length; i += 1) {
      if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return "";
  }

  function recorderExtension(mime) {
    if (mime.indexOf("mp4") !== -1) return ".mp4";
    if (mime.indexOf("aac") !== -1) return ".aac";
    if (mime.indexOf("mpeg") !== -1) return ".mp3";
    return ".webm";
  }

  function stopMediaStream() {
    if (!mediaStream) return;
    mediaStream.getTracks().forEach((track) => {
      try {
        track.stop();
      } catch (err) {
        /* ignore */
      }
    });
    mediaStream = null;
  }

  function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      setStatus("❌ このブラウザでは音声入力できません。スマホの Chrome で開いてください。", "err");
      return;
    }
    const mime = pickRecorderMime();
    recordedChunks = [];
    rememberSessionBase();
    setStatus("マイクを準備しています…");
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        mediaStream = stream;
        const options = mime ? { mimeType: mime } : {};
        mediaRecorder = mime ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (event) => {
          if (event.data && event.data.size) recordedChunks.push(event.data);
        };
        mediaRecorder.onerror = () => {
          recording = false;
          stopMediaStream();
          setListeningUi(false);
          setStatus("❌ 録音でエラーが発生しました", "err");
        };
        mediaRecorder.onstop = () => {
          stopMediaStream();
          uploadRecording(mediaRecorder.mimeType || mime || "audio/webm");
        };
        recording = true;
        mediaRecorder.start();
        setListeningUi(true, "🎙 録音中… 話し終わったらもう一度ボタンを押してください");
        setStatus("");
      })
      .catch((err) => {
        recording = false;
        setListeningUi(false);
        const name = err && err.name ? err.name : "";
        if (name === "NotAllowedError" || name === "PermissionDeniedError") {
          setStatus("❌ マイクを許可してください。", "err");
          return;
        }
        setStatus("❌ スマホの音声認識を開始できません。マイク許可を確認してください。", "err");
      });
  }

  function stopRecording() {
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
      recording = false;
      stopMediaStream();
      setListeningUi(false);
      return;
    }
    try {
      mediaRecorder.stop();
    } catch (err) {
      recording = false;
      stopMediaStream();
      setListeningUi(false);
    }
  }

  function uploadRecording(mime) {
    recording = false;
    const blob = new Blob(recordedChunks, { type: mime || "audio/webm" });
    recordedChunks = [];
    if (!blob.size) {
      setListeningUi(false);
      setStatus("❌ 声を認識できませんでした。もう一度話してください。", "err");
      return;
    }
    transcribing = true;
    setListeningUi(true, "🎙 文字にしています…");
    setStatus("音声を文字にしています…");
    const body = new FormData();
    body.append("audio", blob, `voice${recorderExtension(mime)}`);
    fetch("/api/speech-to-text", {
      method: "POST",
      headers: secretHeaders(),
      body,
    })
      .then(async (res) => {
        let data = {};
        try {
          data = await res.json();
        } catch (e) {
          data = {};
        }
        if (res.status === 401) {
          if (secretBox) {
            secretBox.classList.remove("hidden");
            secretBox.open = true;
          }
          setStatus("❌ 接続用パスワードを保存してから、もう一度話してください", "err");
          return;
        }
        if (res.ok && data.ok && data.text) {
          writeHeardText(data.text);
          rememberSessionBase();
          setStatus("✅ 文字にしました。内容を確認して Notionに登録 を押してください", "ok");
          return;
        }
        if (data.error === "empty_transcript") {
          setStatus("❌ 声を認識できませんでした。もう一度、はっきり話してください。", "err");
          return;
        }
        setStatus("❌ 音声を文字にできませんでした。もう一度試してください。", "err");
      })
      .catch(() => {
        setStatus("❌ 通信に失敗しました。電波を確認してもう一度試してください。", "err");
      })
      .finally(() => {
        transcribing = false;
        setListeningUi(false);
      });
  }

  function focusTranscript() {
    textarea.focus();
    const len = textarea.value.length;
    try {
      textarea.setSelectionRange(len, len);
    } catch (err) {
      /* some browsers reject setSelectionRange on an empty field */
    }
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
      if (event.error === "network") {
        wantListen = false;
        setListeningUi(false);
        startRecording();
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
          startRecording();
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
    setStatus("");
    rememberSessionBase();
    wantListen = true;
    setListeningUi(true);
    focusTranscript();
    try {
      if (!recognition) {
        recognition = createRecognition();
      }
      recognition.lang = "ja-JP";
      recognition.interimResults = true;
      recognition.continuous = true;
      recognition.maxAlternatives = 1;
      recognition.start();
    } catch (err) {
      wantListen = false;
      setListeningUi(false);
      startRecording();
    }
  }

  function stopVoiceInput() {
    wantListen = false;
    if (recording) {
      stopRecording();
      return;
    }
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
    if (transcribing) {
      return;
    }
    if (wantListen || recognizing || recording) {
      stopVoiceInput();
      return;
    }
    if (canUseBrowserSpeech()) {
      startLiveSpeech();
      return;
    }
    startRecording();
  }

  if (phoneHelp) {
    phoneHelp.classList.add("hidden");
  }

  secretSaveBtn?.addEventListener("click", () => {
    const value = (remoteSecretEl && remoteSecretEl.value ? remoteSecretEl.value : "").trim();
    if (!value) {
      setStatus("❌ パスワードを入力してから保存してください", "err");
      return;
    }
    writeSecret(value);
    fetch("/api/auth-check", { headers: secretHeaders() })
      .then((res) => {
        if (res.status === 401) {
          writeSecret("");
          refreshSecretBox();
          setStatus("❌ パスワードが違います。Render に入れた値をもう一度入れてください", "err");
          return;
        }
        if (remoteSecretEl) remoteSecretEl.value = "";
        refreshSecretBox();
        setStatus("✅ このスマホに保存しました。次回から入力は不要です", "ok");
      })
      .catch(() => {
        refreshSecretBox();
        setStatus("✅ このスマホに保存しました。次回から入力は不要です", "ok");
      });
  });

  secretChangeBtn?.addEventListener("click", () => {
    if (secretBox) secretBox.classList.remove("hidden");
    if (secretForm) secretForm.classList.remove("hidden");
    if (secretSavedEl) secretSavedEl.classList.add("hidden");
    secretChangeBtn.classList.add("hidden");
    if (remoteSecretEl) remoteSecretEl.focus();
  });

  refreshSecretBox();

  fetch("/api/config")
    .then((res) => res.json())
    .then((cfg) => {
      if (cfg && cfg.secret_required && secretBox) {
        secretBox.classList.remove("hidden");
        refreshSecretBox();
      }
    })
    .catch(() => {});

  micBtn.addEventListener("click", (event) => {
    event.preventDefault();
    focusTranscript();
    toggleVoiceInput();
  });

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
