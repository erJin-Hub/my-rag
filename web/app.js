const state = {
  conversationId: "",
  conversations: [],
  sending: false,
  creatingConversation: false,
};

const TITLE_MAX_CHARS = 18;

const els = {
  newChatButton: document.querySelector("#newChatButton"),
  openChatButton: document.querySelector("#openChatButton"),
  reloadHistoryButton: document.querySelector("#reloadHistoryButton"),
  conversationInput: document.querySelector("#conversationInput"),
  conversationList: document.querySelector("#conversationList"),
  currentTitle: document.querySelector("#currentTitle"),
  currentMeta: document.querySelector("#currentMeta"),
  messages: document.querySelector("#messages"),
  sources: document.querySelector("#sources"),
  usedMemories: document.querySelector("#usedMemories"),
  webSources: document.querySelector("#webSources"),
  webSearchToggle: document.querySelector("#webSearchToggle"),
  chatForm: document.querySelector("#chatForm"),
  queryInput: document.querySelector("#queryInput"),
  sendButton: document.querySelector("#sendButton"),
};

renderConversationList();
renderEmptyState();
refreshConversations();

els.newChatButton.addEventListener("click", createConversation);
els.openChatButton.addEventListener("click", openConversationFromInput);
els.reloadHistoryButton.addEventListener("click", () => {
  if (state.conversationId) {
    loadHistory(state.conversationId);
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = els.queryInput.value.trim();
  if (!query || state.sending) {
    return;
  }

  await sendMessage(query);
});

els.queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

function loadLocalConversations() {
  try {
    return JSON.parse(localStorage.getItem("my-rag-conversations") || "[]");
  } catch {
    return [];
  }
}

function saveLocalConversations() {
  localStorage.setItem("my-rag-conversations", JSON.stringify(state.conversations));
}

async function refreshConversations() {
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) {
      throw new Error(`读取会话列表失败：${response.status}`);
    }

    const data = await response.json();
    const remoteConversations = (data.items || []).map((item) => ({
      id: String(item.conversation_id),
      title: normalizeTitle(item.title, item.conversation_id) || "新对话",
      updatedAt: item.updated_at || "",
      messageCount: Number(item.message_count || 0),
    }));

    state.conversations = mergeConversations(remoteConversations, loadLocalConversations());
    saveLocalConversations();
    renderConversationList();
  } catch (error) {
    state.conversations = loadLocalConversations();
    renderConversationList();
  }
}

function mergeConversations(primary, fallback) {
  const merged = [];
  const seen = new Set();
  for (const item of [...primary, ...fallback]) {
    const id = String(item.id);
    if (seen.has(id)) {
      continue;
    }
    seen.add(id);
    merged.push({
      id,
      title: normalizeTitle(item.title, id) || "新对话",
      updatedAt: item.updatedAt || "",
      messageCount: Number(item.messageCount || 0),
    });
  }
  return sortConversationsByUpdatedAt(merged);
}

function rememberConversation(conversationId, title) {
  upsertConversation(conversationId, title, {
    updatedAt: new Date().toISOString(),
    moveToTop: true,
  });
}

function rememberConversationSnapshot(conversationId, title) {
  upsertConversation(conversationId, title, {
    moveToTop: false,
  });
}

function upsertConversation(conversationId, title, options = {}) {
  const id = String(conversationId);
  const normalizedTitle = normalizeTitle(title, id);
  const existing = state.conversations.find((item) => item.id === id);
  if (existing) {
    existing.title = normalizedTitle || existing.title;
    if (options.updatedAt) {
      existing.updatedAt = options.updatedAt;
    }
    existing.messageCount = Number(existing.messageCount || 0);
  } else {
    state.conversations.unshift({
      id,
      title: normalizedTitle || "新对话",
      updatedAt: options.updatedAt || "",
      messageCount: 0,
    });
  }
  if (options.moveToTop !== false) {
    state.conversations = sortConversationsByUpdatedAt(state.conversations);
  }
  saveLocalConversations();
  renderConversationList();
}

function sortConversationsByUpdatedAt(conversations) {
  return [...conversations].sort((a, b) => {
    return parseConversationTime(b.updatedAt) - parseConversationTime(a.updatedAt);
  });
}

function parseConversationTime(value) {
  if (!value) {
    return 0;
  }
  return Date.parse(String(value).replace(" ", "T")) || 0;
}

function normalizeTitle(title, conversationId) {
  const value = String(title || "").trim();
  if (!value || value === `会话 ${conversationId}` || value.includes(conversationId)) {
    return "";
  }
  return value.length > TITLE_MAX_CHARS ? value.slice(0, TITLE_MAX_CHARS) : value;
}

function getStoredConversationTitle(conversationId) {
  const conversation = state.conversations.find((item) => item.id === String(conversationId));
  return conversation ? conversation.title : "";
}

function getStoredConversation(conversationId) {
  return state.conversations.find((item) => item.id === String(conversationId));
}

function resolveConversationTitle(conversationId, title) {
  return normalizeTitle(title, conversationId) || getStoredConversationTitle(conversationId) || "新对话";
}

function isEmptyNewConversation(conversation) {
  if (!conversation || Number(conversation.messageCount || 0) !== 0) {
    return false;
  }
  const title = String(conversation.title || "").trim();
  return !title || title === "新对话" || title === `会话 ${conversation.id}` || title.includes(conversation.id);
}

function findEmptyNewConversation() {
  return state.conversations.find((conversation) => isEmptyNewConversation(conversation));
}

function forgetConversation(conversationId) {
  const id = String(conversationId);
  state.conversations = state.conversations.filter((item) => item.id !== id);
  saveLocalConversations();

  if (String(state.conversationId) === id) {
    state.conversationId = "";
    els.conversationInput.value = "";
    renderEmptyState();
  }
  renderConversationList();
}

function renderConversationList() {
  els.conversationList.innerHTML = "";
  if (state.conversations.length === 0) {
    const empty = document.createElement("div");
    empty.className = "page-meta";
    empty.textContent = "暂无本地会话";
    els.conversationList.appendChild(empty);
    return;
  }

  for (const conversation of state.conversations) {
    const item = document.createElement("div");
    item.className = "conversation-item";
    if (conversation.id === String(state.conversationId)) {
      item.classList.add("active");
    }

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "conversation-open";
    openButton.textContent = normalizeTitle(conversation.title, conversation.id) || "新对话";
    openButton.title = `conversation_id: ${conversation.id}`;
    openButton.addEventListener("click", () => loadHistory(conversation.id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "conversation-delete";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteConversation(conversation.id);
    });

    item.appendChild(openButton);
    item.appendChild(deleteButton);
    els.conversationList.appendChild(item);
  }
}

function renderEmptyState() {
  els.messages.innerHTML = "";
  appendMessage("system", "输入问题后会自动创建会话，也可以先点击“新对话”。");
  els.currentTitle.textContent = "新对话";
  els.currentMeta.textContent = "还没有选择会话";
  els.sources.textContent = "";
  renderUsedMemories([]);
  renderWebSources([]);
}

function setActiveConversation(conversationId, title) {
  state.conversationId = String(conversationId || "");
  els.currentTitle.textContent = normalizeTitle(title, state.conversationId) || "新对话";
  els.currentMeta.textContent = state.conversationId
    ? `conversation_id: ${state.conversationId}`
    : "还没有选择会话";
  renderConversationList();
}

async function createConversation() {
  const current = getStoredConversation(state.conversationId);
  const existingEmpty = isEmptyNewConversation(current) ? current : findEmptyNewConversation();
  if (existingEmpty) {
    setActiveConversation(existingEmpty.id, existingEmpty.title);
    els.messages.innerHTML = "";
    appendMessage("system", "当前已经是新对话。");
    return;
  }
  if (state.creatingConversation) {
    return;
  }

  state.creatingConversation = true;
  els.newChatButton.disabled = true;
  try {
    const response = await fetch("/api/conversations/new", { method: "POST" });
    if (!response.ok) {
      throw new Error(`创建会话失败：${response.status}`);
    }
    const data = await response.json();
    const title = resolveConversationTitle(data.conversation_id, data.title);
    rememberConversation(data.conversation_id, title);
    setActiveConversation(data.conversation_id, title);
    els.messages.innerHTML = "";
    appendMessage("system", "新会话已创建。");
  } catch (error) {
    appendMessage("error", error.message);
  } finally {
    state.creatingConversation = false;
    els.newChatButton.disabled = false;
  }
}

function openConversationFromInput() {
  const conversationId = els.conversationInput.value.trim();
  if (!conversationId) {
    return;
  }
  loadHistory(conversationId);
}

async function loadHistory(conversationId) {
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/history`);
    if (!response.ok) {
      throw new Error(`读取历史失败：${response.status}`);
    }
    const data = await response.json();
    const title = resolveConversationTitle(data.conversation_id, data.title);
    rememberConversationSnapshot(data.conversation_id, title);
    setActiveConversation(data.conversation_id, title);
    renderHistory(data.messages || []);
  } catch (error) {
    appendMessage("error", error.message);
  }
}

async function deleteConversation(conversationId) {
  const confirmed = window.confirm(`确定删除会话 ${conversationId} 吗？`);
  if (!confirmed) {
    return;
  }

  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(`删除会话失败：${response.status}`);
    }
    forgetConversation(conversationId);
  } catch (error) {
    appendMessage("error", error.message);
  }
}

function renderHistory(messages) {
  els.messages.innerHTML = "";
  if (messages.length === 0) {
    appendMessage("system", "这个会话还没有历史消息。");
    return;
  }
  for (const message of messages) {
    appendMessage(message.role === "assistant" ? "assistant" : "user", message.content);
  }
}

async function sendMessage(query) {
  state.sending = true;
  els.sendButton.disabled = true;
  els.queryInput.value = "";
  els.sources.textContent = "";
  renderUsedMemories([]);
  renderWebSources([]);

  appendMessage("user", query);
  const assistantNode = appendMessage("assistant", "");

  try {
    await streamChat(query, assistantNode);
  } catch (error) {
    assistantNode.classList.add("error");
    setMessageText(assistantNode, error.message);
  } finally {
    state.sending = false;
    els.sendButton.disabled = false;
    els.queryInput.focus();
  }
}

async function streamChat(query, assistantNode) {
  const payload = {
    query,
    conversation_id: state.conversationId,
    history_len: 10,
    enable_web_search: els.webSearchToggle.checked,
  };

  const response = await fetch("/api/chat/memory/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    throw new Error(`请求失败：${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const result = takeCompleteSseEvents(buffer);
    buffer = result.rest;

    for (const part of result.events) {
      handleSseEvent(part, assistantNode, query);
    }
  }

  if (buffer.trim()) {
    handleSseEvent(buffer, assistantNode, query);
  }
}

function takeCompleteSseEvents(buffer) {
  const events = [];
  let rest = buffer;

  while (true) {
    const match = rest.match(/\r?\n\r?\n/);
    if (!match || match.index === undefined) {
      return { events, rest };
    }

    const end = match.index;
    events.push(rest.slice(0, end));
    rest = rest.slice(end + match[0].length);
  }
}

function handleSseEvent(rawEvent, assistantNode, query) {
  const event = parseSseEvent(rawEvent);
  if (!event) {
    return;
  }

  if (event.event === "token") {
    setMessageText(assistantNode, getMessageText(assistantNode) + (event.data.token || ""));
    scrollMessagesToBottom();
    return;
  }

  if (event.event === "done") {
    const conversationId = event.data.conversation_id;
    if (conversationId) {
      const title = resolveConversationTitle(conversationId, event.data.title);
      rememberConversation(conversationId, title);
      const conversation = getStoredConversation(conversationId);
      if (conversation) {
        conversation.messageCount = Math.max(Number(conversation.messageCount || 0), 2);
        saveLocalConversations();
      }
      setActiveConversation(conversationId, title);
      refreshConversations();
    }
    renderSources(event.data.sources || []);
    renderUsedMemories(event.data.used_memories || []);
    const webSources = event.data.web_sources || [];
    if (webSources.length) {
      enableMessageCitations(assistantNode, webSources.length);
    }
    renderWebSources(webSources, assistantNode);
    return;
  }

  if (event.event === "error") {
    throw new Error(event.data.message || "流式响应出错");
  }
}

function parseSseEvent(rawEvent) {
  const lines = rawEvent.split(/\r?\n/);
  let eventName = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    return {
      event: eventName,
      data: JSON.parse(dataLines.join("\n")),
    };
  } catch {
    return null;
  }
}

function renderSources(sources) {
  els.sources.innerHTML = "";
  if (!sources.length) {
    return;
  }

  const label = document.createElement("span");
  label.textContent = "Sources: ";
  els.sources.appendChild(label);

  for (const source of sources) {
    const pill = document.createElement("span");
    pill.className = "source-pill";
    pill.textContent = source;
    els.sources.appendChild(pill);
  }
}

function renderUsedMemories(memories) {
  els.usedMemories.innerHTML = "";
  if (!memories.length) {
    return;
  }

  const header = document.createElement("div");
  header.className = "used-memory-title";
  header.textContent = `本轮命中长期记忆 ${memories.length} 条`;
  els.usedMemories.appendChild(header);

  const list = document.createElement("div");
  list.className = "used-memory-list";
  for (const memory of memories) {
    const item = document.createElement("div");
    item.className = "used-memory-item";

    const meta = document.createElement("div");
    meta.className = "used-memory-meta";
    const score = Number(memory.score || 0);
    meta.textContent = `#${memory.id} · ${formatMemoryCategory(memory.category)} · 重要度 ${memory.importance} · 相似度 ${score.toFixed(3)}`;

    const content = document.createElement("div");
    content.className = "used-memory-content";
    content.textContent = memory.content || "";

    item.appendChild(meta);
    item.appendChild(content);
    list.appendChild(item);
  }
  els.usedMemories.appendChild(list);
}

function renderWebSources(sources, targetNode = null) {
  if (!targetNode) {
    els.webSources.innerHTML = "";
  }
  if (!sources.length) {
    return;
  }

  const container = targetNode || els.webSources;
  const header = document.createElement("div");
  header.className = targetNode ? "message-source-summary" : "used-memory-title";
  header.textContent = targetNode ? `检索到 ${sources.length} 个网页` : `联网搜索来源 ${sources.length} 条`;
  container.appendChild(header);

  const list = document.createElement("div");
  list.className = targetNode ? "message-source-list" : "web-source-list";
  sources.forEach((source, index) => {
    const item = document.createElement("a");
    item.className = targetNode ? "message-source-card" : "web-source-item";
    item.href = source.url || "#";
    item.target = "_blank";
    item.rel = "noreferrer";

    const badge = document.createElement("span");
    badge.className = "message-source-index";
    badge.textContent = String(index + 1);

    const title = document.createElement("div");
    title.className = targetNode ? "message-source-title" : "web-source-title";
    title.textContent = compactText(source.title || source.url || "搜索结果", targetNode ? 38 : 80);

    const snippet = document.createElement("div");
    snippet.className = targetNode ? "message-source-snippet" : "web-source-snippet";
    snippet.textContent = compactText(source.snippet || "", targetNode ? 90 : 180);

    item.appendChild(badge);
    item.appendChild(title);
    if (snippet.textContent) {
      item.appendChild(snippet);
    }
    list.appendChild(item);
  });
  container.appendChild(list);
}

function formatMemoryCategory(category) {
  const labels = {
    preference: "偏好",
    profile: "用户信息",
    project: "项目背景",
    goal: "长期目标",
    fact: "事实",
    general: "通用",
  };
  const key = String(category || "general");
  return `${key}（${labels[key] || "未分类"}）`;
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  const body = document.createElement("div");
  body.className = "message-body";
  node.appendChild(body);
  setMessageText(node, text);
  els.messages.appendChild(node);
  scrollMessagesToBottom();
  return node;
}

function getMessageBody(node) {
  return node.querySelector(".message-body") || node;
}

function getMessageText(node) {
  return getMessageBody(node).dataset.rawText || "";
}

function setMessageText(node, text) {
  const body = getMessageBody(node);
  body.dataset.rawText = text || "";
  renderMessageText(body, text || "", node.dataset.showCitations === "true");
}

function enableMessageCitations(node, citationCount) {
  node.dataset.showCitations = "true";
  node.dataset.citationCount = String(citationCount || 0);
  setMessageText(node, getMessageText(node));
}

function renderMessageText(body, text, enableCitations) {
  body.innerHTML = "";
  if (!enableCitations) {
    body.textContent = text;
    return;
  }

  const parts = String(text).split(/(\[\d+\])/g);
  const citationCount = Number(body.parentElement?.dataset.citationCount || 0);
  for (const part of parts) {
    const match = part.match(/^\[(\d+)\]$/);
    const citationNumber = match ? Number(match[1]) : 0;
    if (match && citationNumber > 0 && citationNumber <= citationCount) {
      const marker = document.createElement("sup");
      marker.className = "citation-marker";
      marker.textContent = match[1];
      body.appendChild(marker);
    } else {
      body.appendChild(document.createTextNode(part));
    }
  }
}

function compactText(text, maxLength) {
  const normalized = String(text || "")
    .replace(/!\[[^\]]*]\([^)]+\)/g, "")
    .replace(/\[[^\]]+]\([^)]+\)/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trim()}...`;
}

function scrollMessagesToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}
