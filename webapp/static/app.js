const el = (id) => document.getElementById(id);

const modelEl = el("model");
const systemEl = el("system");
const tempEl = el("temperature");
const topPEl = el("top_p");
const maxTokensEl = el("max_tokens");
const keepTurnsEl = el("keep_turns");
const showUsageEl = el("show_usage");
const showReasoningEl = el("show_reasoning");

const messagesEl = el("messages");
const inputEl = el("input");
const sendBtn = el("send");
const resetBtn = el("reset");
const statusEl = el("status");
const usageEl = el("usage");
const totalEl = el("total");
const refreshBtn = el("refreshModels");

let chatMessages = [];     // 多轮对话记忆栈（前端保存即可）
let totalUsage = {};       // 累计 usage

function setStatus(s) { statusEl.textContent = s; }

function escapeHtml(s) {
  return (s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function renderMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role === "user" ? "you" : "ai"}`;
  div.innerHTML = `
    <div class="meta">${role === "user" ? "You" : "AI"}</div>
    <div class="content">${escapeHtml(text)}</div>
  `;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function ensureSystem() {
  const sys = systemEl.value.trim();
  // 规则：如果 sys 有内容，就强制 chatMessages[0] 是 system；否则删除 system
  if (sys) {
    if (chatMessages.length && chatMessages[0].role === "system") {
      chatMessages[0].content = sys;
    } else {
      chatMessages.unshift({ role: "system", content: sys });
    }
  } else {
    if (chatMessages.length && chatMessages[0].role === "system") {
      chatMessages.shift();
    }
  }
}

function updateUsage(usage) {
  if (!usage) return;
  for (const [k, v] of Object.entries(usage)) {
    if (Number.isInteger(v)) totalUsage[k] = (totalUsage[k] || 0) + v;
  }
}

function usageLine(obj) {
  if (!obj) return "(no usage)";
  return Object.entries(obj).map(([k,v]) => `${k}=${v}`).join("  ");
}

async function refreshModels() {
  try {
    const r = await fetch("/api/models");
    const data = await r.json();
    const models = data.models || ["deepseek-chat", "deepseek-reasoner"];
    const cur = modelEl.value;

    modelEl.innerHTML = "";
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      modelEl.appendChild(opt);
    }
    if (cur && models.includes(cur)) modelEl.value = cur;

    setStatus(`models: ${models.length}`);
  } catch (e) {
    setStatus("models refresh failed");
  }
}

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;

  inputEl.value = "";
  renderMsg("user", text);

  ensureSystem();
  chatMessages.push({ role: "user", content: text });

  setStatus("thinking…");
  sendBtn.disabled = true;

  const req = {
    messages: chatMessages,
    model: modelEl.value || "deepseek-chat",
    temperature: parseFloat(tempEl.value || "0.7"),
    top_p: parseFloat(topPEl.value || "0.9"),
    max_tokens: parseInt(maxTokensEl.value || "1200", 10),
    keep_turns: parseInt(keepTurnsEl.value || "20", 10),
  };

  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req)
    });

    if (!r.ok) {
      const t = await r.text();
      throw new Error(`HTTP ${r.status}: ${t}`);
    }

    const data = await r.json();
    renderMsg("assistant", data.content || "");
    chatMessages.push({ role: "assistant", content: data.content || "" });

    if (showReasoningEl.checked && data.reasoning_content) {
      renderMsg("assistant", "[reasoning_content]\n" + data.reasoning_content);
    }

    if (showUsageEl.checked) {
      usageEl.textContent = "[usage] " + usageLine(data.usage);
      updateUsage(data.usage);
      totalEl.textContent = "[total] " + usageLine(totalUsage);
    } else {
      usageEl.textContent = "";
      totalEl.textContent = "";
    }

    setStatus("ok");
  } catch (e) {
    setStatus("error: " + e.message);
  } finally {
    sendBtn.disabled = false;
  }
}

function resetChat() {
  chatMessages = [];
  totalUsage = {};
  messagesEl.innerHTML = "";
  usageEl.textContent = "";
  totalEl.textContent = "";
  setStatus("reset ok");
  ensureSystem(); // 如果 system 非空，会重新插入为首条
}

sendBtn.addEventListener("click", send);
resetBtn.addEventListener("click", resetChat);
refreshBtn.addEventListener("click", refreshModels);

// Enter 发送，Shift+Enter 换行
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

// 默认 system
systemEl.value = "你是一个严谨但不无聊的计算机导师。回答要结构清晰，必要时给例子。";
ensureSystem();
refreshModels();
setStatus("ready");
