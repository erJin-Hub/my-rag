const state = {
  memories: [],
  saving: false,
};

const els = {
  memorySummary: document.querySelector("#memorySummary"),
  memoryList: document.querySelector("#memoryList"),
  memoryForm: document.querySelector("#memoryForm"),
  memoryId: document.querySelector("#memoryId"),
  memoryContent: document.querySelector("#memoryContent"),
  memoryCategory: document.querySelector("#memoryCategory"),
  memoryImportance: document.querySelector("#memoryImportance"),
  memoryEnabled: document.querySelector("#memoryEnabled"),
  memoryStatus: document.querySelector("#memoryStatus"),
  saveMemoryButton: document.querySelector("#saveMemoryButton"),
  disableMemoryButton: document.querySelector("#disableMemoryButton"),
  resetFormButton: document.querySelector("#resetFormButton"),
  refreshMemoriesButton: document.querySelector("#refreshMemoriesButton"),
  categoryFilter: document.querySelector("#categoryFilter"),
  includeDisabled: document.querySelector("#includeDisabled"),
};

const CATEGORY_LABELS = {
  preference: "偏好",
  profile: "用户信息",
  project: "项目背景",
  goal: "长期目标",
  fact: "事实",
  general: "通用",
};

els.memoryForm.addEventListener("submit", saveMemory);
els.resetFormButton.addEventListener("click", resetForm);
els.disableMemoryButton.addEventListener("click", disableSelectedMemory);
els.refreshMemoriesButton.addEventListener("click", refreshMemories);
els.categoryFilter.addEventListener("change", refreshMemories);
els.includeDisabled.addEventListener("change", refreshMemories);

refreshMemories();

async function refreshMemories() {
  const params = new URLSearchParams();
  params.set("limit", "100");
  if (els.categoryFilter.value) {
    params.set("category", els.categoryFilter.value);
  }
  if (els.includeDisabled.checked) {
    params.set("include_disabled", "true");
  }

  try {
    const response = await fetch(`/api/memories?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`读取长期记忆失败：${response.status}`);
    }
    const data = await response.json();
    state.memories = data.items || [];
    renderMemoryList();
    updateSummary();
  } catch (error) {
    els.memorySummary.textContent = "长期记忆读取失败";
    els.memoryList.innerHTML = "";
    setStatus(error.message, true);
  }
}

async function saveMemory(event) {
  event.preventDefault();
  const content = els.memoryContent.value.trim();
  if (!content || state.saving) {
    if (!content) {
      setStatus("记忆内容不能为空", true);
    }
    return;
  }

  state.saving = true;
  els.saveMemoryButton.disabled = true;

  const memoryId = els.memoryId.value.trim();
  const payload = {
    content,
    category: els.memoryCategory.value,
    importance: Number(els.memoryImportance.value || 3),
  };
  if (memoryId) {
    payload.enabled = els.memoryEnabled.checked;
  }

  try {
    const response = await fetch(memoryId ? `/api/memories/${encodeURIComponent(memoryId)}` : "/api/memories", {
      method: memoryId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "保存记忆失败");
    }
    setStatus(memoryId ? "记忆已更新" : "记忆已新增");
    fillForm(data);
    await refreshMemories();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.saving = false;
    els.saveMemoryButton.disabled = false;
  }
}

async function disableSelectedMemory() {
  const memoryId = els.memoryId.value.trim();
  if (!memoryId) {
    return;
  }

  try {
    const response = await fetch(`/api/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "禁用记忆失败");
    }
    setStatus("记忆已禁用");
    els.memoryEnabled.checked = false;
    await refreshMemories();
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderMemoryList() {
  els.memoryList.innerHTML = "";
  if (state.memories.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-panel";
    empty.textContent = "还没有符合条件的长期记忆";
    els.memoryList.appendChild(empty);
    return;
  }

  for (const memory of state.memories) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "memory-item";
    if (!memory.enabled) {
      item.classList.add("disabled");
    }
    if (String(memory.id) === els.memoryId.value) {
      item.classList.add("selected");
    }
    item.addEventListener("click", () => fillForm(memory));

    const head = document.createElement("div");
    head.className = "memory-item-head";

    const category = document.createElement("span");
    category.className = "memory-category";
    category.textContent = formatCategory(memory.category);

    const meta = document.createElement("span");
    meta.className = "memory-meta";
    meta.textContent = `记忆编号 ${memory.id} · 重要度 ${memory.importance}`;

    const content = document.createElement("div");
    content.className = "memory-content";
    content.textContent = memory.content;

    const foot = document.createElement("div");
    foot.className = "memory-foot";
    foot.textContent = memory.enabled
      ? `北京时间 ${memory.updated_at} 更新`
      : `已禁用 · 北京时间 ${memory.updated_at} 更新`;

    head.appendChild(category);
    head.appendChild(meta);
    item.appendChild(head);
    item.appendChild(content);
    item.appendChild(foot);
    els.memoryList.appendChild(item);
  }
}

function fillForm(memory) {
  els.memoryId.value = memory.id || "";
  els.memoryContent.value = memory.content || "";
  els.memoryCategory.value = memory.category || "general";
  els.memoryImportance.value = memory.importance || 3;
  els.memoryEnabled.checked = memory.enabled !== false;
  els.disableMemoryButton.disabled = !memory.id || memory.enabled === false;
  els.saveMemoryButton.textContent = memory.id ? "保存修改" : "保存记忆";
  renderMemoryList();
}

function resetForm() {
  els.memoryForm.reset();
  els.memoryId.value = "";
  els.memoryCategory.value = "preference";
  els.memoryImportance.value = "3";
  els.memoryEnabled.checked = true;
  els.disableMemoryButton.disabled = true;
  els.saveMemoryButton.textContent = "保存记忆";
  setStatus("");
  renderMemoryList();
  els.memoryContent.focus();
}

function updateSummary() {
  const enabledCount = state.memories.filter((memory) => memory.enabled).length;
  els.memorySummary.textContent = `${state.memories.length} 条记录 / ${enabledCount} 条启用`;
}

function formatCategory(category) {
  const key = String(category || "general");
  const label = CATEGORY_LABELS[key] || "未分类";
  return `${key}（${label}）`;
}

function setStatus(message, isError = false) {
  els.memoryStatus.textContent = message || "";
  els.memoryStatus.classList.toggle("error-text", isError);
}
