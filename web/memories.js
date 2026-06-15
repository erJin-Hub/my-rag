const state = {
  memories: [],
  saving: false,
  updatingEnabled: false,
  editorMode: "empty",
  page: 1,
  pageSize: 5,
  total: 0,
  totalPages: 1,
};

const els = {
  editorTitle: document.querySelector("#editorTitle"),
  editorSubtitle: document.querySelector("#editorSubtitle"),
  memoryEmptyState: document.querySelector("#memoryEmptyState"),
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
  resetFormButton: document.querySelector("#resetFormButton"),
  memoryKeyword: document.querySelector("#memoryKeyword"),
  searchMemoriesButton: document.querySelector("#searchMemoriesButton"),
  categoryFilter: document.querySelector("#categoryFilter"),
  includeDisabled: document.querySelector("#includeDisabled"),
  pageSizeSelect: document.querySelector("#pageSizeSelect"),
  paginationInfo: document.querySelector("#paginationInfo"),
  prevPageButton: document.querySelector("#prevPageButton"),
  nextPageButton: document.querySelector("#nextPageButton"),
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
els.categoryFilter.addEventListener("change", resetToFirstPageAndRefresh);
els.includeDisabled.addEventListener("change", resetToFirstPageAndRefresh);
els.memoryEnabled.addEventListener("change", () => updateSelectedMemoryEnabled(els.memoryEnabled.checked));
els.searchMemoriesButton.addEventListener("click", searchMemories);
els.pageSizeSelect.addEventListener("change", changePageSize);
els.prevPageButton.addEventListener("click", () => changePage(state.page - 1));
els.nextPageButton.addEventListener("click", () => changePage(state.page + 1));
els.memoryKeyword.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchMemories();
  }
});

setEditorMode("empty");
refreshMemories();

async function refreshMemories() {
  const params = new URLSearchParams();
  params.set("limit", String(state.pageSize));
  params.set("page", String(state.page));
  if (els.categoryFilter.value) {
    params.set("category", els.categoryFilter.value);
  }
  const keyword = els.memoryKeyword.value.trim();
  if (keyword) {
    params.set("keyword", keyword);
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
    state.total = Number(data.total || 0);
    state.page = Number(data.page || state.page);
    state.pageSize = Number(data.page_size || state.pageSize);
    state.totalPages = Number(data.total_pages || getTotalPages());
    if (state.total > 0 && state.page > state.totalPages) {
      state.page = state.totalPages;
      await refreshMemories();
      return;
    }
    renderMemoryList();
    updateSummary();
    renderPagination();
  } catch (error) {
    els.memorySummary.textContent = "长期记忆读取失败";
    els.memoryList.innerHTML = "";
    state.total = 0;
    state.totalPages = 1;
    renderPagination();
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

async function updateSelectedMemoryEnabled(enabled) {
  const memoryId = els.memoryId.value.trim();
  if (!memoryId || state.updatingEnabled) {
    return;
  }

  const currentMemory = state.memories.find((item) => String(item.id) === String(memoryId));
  const previous = currentMemory ? currentMemory.enabled !== false : !enabled;
  state.updatingEnabled = true;
  setEnabledControlsDisabled(true);
  applyMemoryEnabledState(memoryId, enabled);
  setStatus(enabled ? "正在启用记忆..." : "正在禁用记忆...");

  try {
    const response = await fetch(`/api/memories/${encodeURIComponent(memoryId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "更新记忆状态失败");
    }
    setStatus(enabled ? "记忆已启用" : "记忆已禁用");
    fillForm(data);
    await refreshMemories();
  } catch (error) {
    applyMemoryEnabledState(memoryId, previous);
    setStatus(error.message, true);
  } finally {
    state.updatingEnabled = false;
    setEnabledControlsDisabled(false);
  }
}

function searchMemories() {
  state.page = 1;
  refreshMemories();
}

function resetToFirstPageAndRefresh() {
  state.page = 1;
  refreshMemories();
}

function changePageSize() {
  state.pageSize = Number(els.pageSizeSelect.value || 5);
  state.page = 1;
  refreshMemories();
}

function changePage(page) {
  const totalPages = getTotalPages();
  const nextPage = Math.max(1, Math.min(page, totalPages));
  if (nextPage === state.page) {
    return;
  }
  state.page = nextPage;
  refreshMemories();
}

function getTotalPages() {
  return Math.max(1, state.totalPages || Math.ceil(state.total / state.pageSize));
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
    appendMemoryMeta(foot, memory.source_conversation_id ? `来源会话：${memory.source_conversation_id}` : "来源：手动创建");
    appendMemoryMeta(foot, `创建：${memory.created_at || "-"}`);
    appendMemoryMeta(foot, `更新：${memory.updated_at || "-"}`);
    appendMemoryMeta(foot, memory.enabled ? "状态：启用" : "状态：已禁用");

    head.appendChild(category);
    head.appendChild(meta);
    item.appendChild(head);
    item.appendChild(content);
    item.appendChild(foot);
    els.memoryList.appendChild(item);
  }
}

function fillForm(memory) {
  setEditorMode(memory.id ? "edit" : "create");
  els.memoryId.value = memory.id || "";
  els.memoryContent.value = memory.content || "";
  els.memoryCategory.value = memory.category || "general";
  els.memoryImportance.value = memory.importance || 3;
  els.memoryEnabled.checked = memory.enabled !== false;
  els.saveMemoryButton.textContent = memory.id ? "保存修改" : "保存记忆";
  renderMemoryList();
}

function resetForm() {
  els.memoryForm.reset();
  setEditorMode("create");
  els.memoryId.value = "";
  els.memoryCategory.value = "preference";
  els.memoryImportance.value = "3";
  els.memoryEnabled.checked = true;
  els.saveMemoryButton.textContent = "保存记忆";
  setStatus("");
  renderMemoryList();
  els.memoryContent.focus();
}

function setEditorMode(mode) {
  state.editorMode = mode;
  const isEmpty = mode === "empty";
  els.memoryEmptyState.classList.toggle("hidden", !isEmpty);
  els.memoryForm.classList.toggle("hidden", isEmpty);

  if (mode === "create") {
    els.editorTitle.textContent = "新建记忆";
    els.editorSubtitle.textContent = "手动添加一条跨会话长期记忆";
    els.resetFormButton.textContent = "新建";
  } else if (mode === "edit") {
    els.editorTitle.textContent = "编辑记忆";
    els.editorSubtitle.textContent = "修改右侧选中的长期记忆";
    els.resetFormButton.textContent = "新建";
  } else {
    els.editorTitle.textContent = "记忆条目";
    els.editorSubtitle.textContent = "选择右侧记忆进行编辑，或新建一条长期记忆";
    els.resetFormButton.textContent = "新建";
  }
}

function updateSummary() {
  const enabledCount = state.memories.filter((memory) => memory.enabled).length;
  els.memorySummary.textContent = `${state.total} 条记录 / 当前页 ${state.memories.length} 条 / ${enabledCount} 条启用`;
}

function renderPagination() {
  const totalPages = getTotalPages();
  els.paginationInfo.textContent = `第 ${state.page} / ${totalPages} 页`;
  els.prevPageButton.disabled = state.page <= 1;
  els.nextPageButton.disabled = state.page >= totalPages;
}

function formatCategory(category) {
  const key = String(category || "general");
  const label = CATEGORY_LABELS[key] || "未分类";
  return `${key}（${label}）`;
}

function appendMemoryMeta(parent, text) {
  const item = document.createElement("span");
  item.textContent = text;
  parent.appendChild(item);
}

function applyMemoryEnabledState(memoryId, enabled) {
  els.memoryEnabled.checked = enabled;
  const memory = state.memories.find((item) => String(item.id) === String(memoryId));
  if (memory) {
    memory.enabled = enabled;
  }
  renderMemoryList();
  updateSummary();
}

function setEnabledControlsDisabled(disabled) {
  els.memoryEnabled.disabled = disabled;
}

function setStatus(message, isError = false) {
  els.memoryStatus.textContent = message || "";
  els.memoryStatus.classList.toggle("error-text", isError);
}
