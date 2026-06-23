const els = {
  docSummary: document.querySelector("#docSummary"),
  docList: document.querySelector("#docList"),
  fileInput: document.querySelector("#fileInput"),
  uploadButton: document.querySelector("#uploadButton"),
  uploadStatus: document.querySelector("#uploadStatus"),
  refreshDocsButton: document.querySelector("#refreshDocsButton"),
  dropZone: document.querySelector("#dropZone"),
};

const SUPPORTED_SUFFIXES = [".txt", ".md", ".pdf", ".docx"];

let uploading = false;

els.uploadButton.addEventListener("click", () => {
  if (!uploading) {
    els.fileInput.click();
  }
});

els.fileInput.addEventListener("change", async () => {
  await uploadFiles(Array.from(els.fileInput.files || []));
  els.fileInput.value = "";
});

els.refreshDocsButton.addEventListener("click", refreshDocList);

els.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  els.dropZone.classList.add("dragging");
});

els.dropZone.addEventListener("dragleave", () => {
  els.dropZone.classList.remove("dragging");
});

els.dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  els.dropZone.classList.remove("dragging");
  await uploadFiles(Array.from(event.dataTransfer.files || []));
});

els.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.fileInput.click();
  }
});

refreshDocList();

async function uploadFiles(files) {
  const validFiles = files.filter((file) => SUPPORTED_SUFFIXES.includes(getSuffix(file.name)));
  if (uploading || validFiles.length === 0) {
    if (files.length > 0 && validFiles.length === 0) {
      setStatus(`只支持 ${SUPPORTED_SUFFIXES.join(" / ")} 文件`, true);
    }
    return;
  }

  uploading = true;
  els.uploadButton.disabled = true;
  els.refreshDocsButton.disabled = true;

  try {
    let completed = 0;
    for (const file of validFiles) {
      setStatus(`正在上传 ${file.name}（${completed + 1}/${validFiles.length}）`);
      await uploadOneFile(file);
      completed += 1;
    }
    setStatus(`已上传 ${completed} 个文件`);
    await refreshDocList();
  } catch (error) {
    setStatus(error.message || "上传失败", true);
  } finally {
    uploading = false;
    els.uploadButton.disabled = false;
    els.refreshDocsButton.disabled = false;
  }
}

async function uploadOneFile(file) {
  const form = new FormData();
  form.append("file", file);

  const resp = await fetch("/api/documents/upload", { method: "POST", body: form });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || `上传 ${file.name} 失败`);
  }
  return data;
}

async function refreshDocList() {
  try {
    const resp = await fetch("/api/documents/list");
    if (!resp.ok) {
      throw new Error(`读取文档列表失败：${resp.status}`);
    }
    const data = await resp.json();
    const files = data.files || [];

    els.docSummary.textContent = `${files.length} 个文件 / ${data.total_chunks || 0} 个文档块`;
    renderDocList(files);
  } catch (error) {
    els.docSummary.textContent = "文档列表读取失败";
    els.docList.innerHTML = "";
    setStatus(error.message, true);
  }
}

function renderDocList(files) {
  els.docList.innerHTML = "";
  if (files.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-panel";
    empty.textContent = "还没有文档";
    els.docList.appendChild(empty);
    return;
  }

  for (const file of files) {
    const item = document.createElement("div");
    item.className = "document-item";

    const name = document.createElement("div");
    name.className = "document-name";
    name.textContent = file.filename;
    name.title = file.filename;

    const meta = document.createElement("div");
    meta.className = "document-meta";
    meta.textContent = `${file.chunks} 个文档块`;

    item.appendChild(name);
    item.appendChild(meta);
    els.docList.appendChild(item);
  }
}

function setStatus(message, isError = false) {
  els.uploadStatus.textContent = message || "";
  els.uploadStatus.classList.toggle("error-text", isError);
}

function getSuffix(filename) {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}
