(() => {
  const fileInput = document.getElementById("file-input");
  const sampleSelect = document.getElementById("sample-select");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const paperMeta = document.getElementById("paper-meta");
  const questionNav = document.getElementById("question-nav");
  const emptyState = document.getElementById("empty-state");
  const questionView = document.getElementById("question-view");

  /** @type {{ questions: any[], validation?: any, title?: string } | null} */
  let paper = null;
  let index = 0;
  /** @type {Record<number, string>} */
  let selections = {};
  /** @type {{ id: string, table: any }[]} */
  let pendingGrids = [];
  let gridSerial = 0;

  fileInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    loadPaper(JSON.parse(text), file.name);
  });

  sampleSelect.addEventListener("change", async () => {
    const url = sampleSelect.value;
    if (!url) return;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      loadPaper(data, url);
    } catch (error) {
      paperMeta.textContent = `Failed to load ${url}: ${error.message}`;
    }
  });

  prevBtn.addEventListener("click", () => showQuestion(index - 1));
  nextBtn.addEventListener("click", () => showQuestion(index + 1));

  function loadPaper(data, label) {
    if (!data || !Array.isArray(data.questions)) {
      paperMeta.textContent = "JSON must include a questions array.";
      return;
    }
    paper = data;
    selections = {};
    index = 0;
    renderMeta(label);
    renderNav();
    showQuestion(0);
  }

  function renderMeta(label) {
    const v = paper.validation || {};
    const detected = v.questions_detected ?? v.questionsDetected ?? paper.questions.length;
    const expected = v.questions_expected ?? v.questionsExpected;
    const passCount = v.pass_count ?? v.passCount;
    const reviewCount = v.review_count ?? v.reviewCount;
    const title = paper.title ? `<div><strong>${escapeHtml(paper.title)}</strong></div>` : "";
    paperMeta.innerHTML = `
      ${title}
      <div class="muted">${escapeHtml(label || "loaded paper")}</div>
      <div>${detected}${expected != null ? ` / ${expected}` : ""} questions</div>
      ${passCount != null ? `<div>pass ${passCount}${reviewCount != null ? ` · review ${reviewCount}` : ""}</div>` : ""}
    `;
  }

  function renderNav() {
    questionNav.innerHTML = "";
    paper.questions.forEach((question, i) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "q-chip";
      const status = question.validation?.status || "pass";
      if (status === "review") button.classList.add("review");
      if (question.visual?.required) button.classList.add("visual");
      if ((question.tables || []).length) button.classList.add("has-table");
      button.textContent = String(question.questionNumber ?? question.question_number ?? i + 1);
      button.addEventListener("click", () => showQuestion(i));
      questionNav.appendChild(button);
    });
  }

  function showQuestion(nextIndex) {
    if (!paper) return;
    index = Math.max(0, Math.min(paper.questions.length - 1, nextIndex));
    prevBtn.disabled = index <= 0;
    nextBtn.disabled = index >= paper.questions.length - 1;

    [...questionNav.children].forEach((chip, i) => {
      chip.classList.toggle("active", i === index);
    });

    const question = paper.questions[index];
    emptyState.classList.add("hidden");
    questionView.classList.remove("hidden");
    pendingGrids = [];
    questionView.innerHTML = renderQuestion(question);
    hydrateGrids();
    wireOptionClicks(question);
  }

  function renderQuestion(question) {
    const number = question.questionNumber ?? question.question_number;
    const type = question.questionType ?? question.question_type ?? "mcq";
    const status = question.validation?.status || "pass";
    const pageStart = question.source?.pageStart ?? question.source?.page_start;
    const pageEnd = question.source?.pageEnd ?? question.source?.page_end;
    const pageLabel =
      pageStart == null ? "" : pageStart === pageEnd ? `page ${pageStart}` : `pages ${pageStart}–${pageEnd}`;

    const referenced = referencedTableIndexes(question);
    const parts = [
      `<div class="q-header">
        <h2 style="margin:0">Q${escapeHtml(String(number))}</h2>
        <span class="badge">${escapeHtml(type)}</span>
        <span class="badge ${status}">${escapeHtml(status)}</span>
        ${pageLabel ? `<span class="muted">${escapeHtml(pageLabel)}</span>` : ""}
        ${question.visual?.required ? `<span class="badge">visual</span>` : ""}
        ${(question.tables || []).length ? `<span class="badge">tables ${(question.tables || []).length}</span>` : ""}
      </div>`,
      question.stem ? `<p class="stem">${formatChem(question.stem)}</p>` : "",
      renderContent(question),
      renderTablesByRole(question, "stem", referenced),
      type === "structured" ? renderParts(question.parts || []) : "",
      renderTablesByRole(question, "options", referenced),
      // Any leftover tables (unknown role / not in content)
      renderRemainingTables(question, referenced),
      type === "mcq" ? renderOptions(question) : "",
      renderIssues(question),
    ];
    return parts.filter(Boolean).join("");
  }

  function referencedTableIndexes(question) {
    const used = new Set();
    for (const block of question.content || []) {
      if (block.type === "table") {
        used.add(block.tableIndex ?? block.table_index ?? 0);
      }
    }
    return used;
  }

  function renderContent(question) {
    const blocks = question.content || [];
    if (!blocks.length) return "";
    return blocks
      .map((block, blockIndex) => {
        const type = block.type;
        if (type === "text" && block.text) {
          return `<section class="content-block"><div class="label">text</div><div>${formatChem(block.text)}</div></section>`;
        }
        if (type === "diagram") {
          const src = assetUrl(block.assetPath || block.asset_path);
          return `<section class="content-block"><div class="label">diagram</div>${
            src
              ? `<img src="${escapeAttr(src)}" alt="Q diagram" loading="lazy" />`
              : `<div class="muted">diagram pending</div>`
          }</section>`;
        }
        if (type === "table") {
          const tableIndex = block.tableIndex ?? block.table_index ?? 0;
          const table = (question.tables || [])[tableIndex];
          return renderTableSection(table, `content-${tableIndex}`, table?.role || "table");
        }
        if (type === "options") {
          const src = assetUrl(block.assetPath || block.asset_path);
          if (src) {
            return `<section class="content-block"><div class="label">options (visual)</div><img src="${escapeAttr(src)}" alt="Options" loading="lazy" /></section>`;
          }
          return "";
        }
        return `<section class="content-block"><div class="label">${escapeHtml(type || "block")}</div><div class="muted">#${blockIndex}</div></section>`;
      })
      .join("");
  }

  function renderTablesByRole(question, role, referenced) {
    const tables = question.tables || [];
    return tables
      .map((table, i) => {
        if (referenced.has(i)) return "";
        if ((table.role || "stem") !== role) return "";
        referenced.add(i);
        return renderTableSection(table, `${role}-${i}`, role);
      })
      .join("");
  }

  function renderRemainingTables(question, referenced) {
    const tables = question.tables || [];
    return tables
      .map((table, i) => {
        if (referenced.has(i)) return "";
        referenced.add(i);
        return renderTableSection(table, `extra-${i}`, table.role || "table");
      })
      .join("");
  }

  function renderTableSection(table, key, role) {
    if (!table) return `<section class="content-block"><div class="muted">table missing</div></section>`;
    const id = `grid-${gridSerial++}-${key}`;
    pendingGrids.push({ id, table });
    const roleLabel = role === "options" ? "options table" : role === "stem" ? "stem table" : "table";
    return `<section class="content-block">
      <div class="label">${escapeHtml(roleLabel)}</div>
      <div id="${escapeAttr(id)}" class="grid-host"></div>
      <noscript>${renderFallbackTable(table)}</noscript>
    </section>`;
  }

  function hydrateGrids() {
    if (typeof gridjs === "undefined") {
      // CDN failed — fall back to plain HTML tables.
      pendingGrids.forEach(({ id, table }) => {
        const host = document.getElementById(id);
        if (host) host.innerHTML = renderFallbackTable(table);
      });
      pendingGrids = [];
      return;
    }

    pendingGrids.forEach(({ id, table }) => {
      const host = document.getElementById(id);
      if (!host) return;
      host.innerHTML = "";
      const { columns, data } = tableToGridPayload(table);
      const rowCount = data.length;
      new gridjs.Grid({
        columns,
        data,
        sort: rowCount > 1,
        search: rowCount > 8,
        pagination: rowCount > 12 ? { limit: 12 } : false,
        resizable: true,
        className: {
          table: "qb-grid-table",
          th: "qb-grid-th",
          td: "qb-grid-td",
        },
        style: {
          table: { width: "100%" },
          th: { "background-color": "#f1f4ef", "white-space": "nowrap" },
          td: { "white-space": "normal", "vertical-align": "top" },
        },
      }).render(host);
    });
    pendingGrids = [];
  }

  function tableToGridPayload(table) {
    const headers = [...(table.headers || [])];
    const rows = (table.rows || []).map((row) => [...(row || [])]);
    const width = Math.max(headers.length, ...rows.map((row) => row.length), 1);
    while (headers.length < width) headers.push("");
    const columns = headers.map((header, colIndex) => {
      const name = String(header || "").trim() || (colIndex === 0 ? "#" : `Col ${colIndex + 1}`);
      return {
        name,
        sort: true,
        formatter: (cell) => gridjs.html(formatChem(cell == null ? "" : String(cell))),
      };
    });
    const data = rows.map((row) => {
      const cells = [...row];
      while (cells.length < width) cells.push("");
      return cells.slice(0, width).map((cell) => (cell == null ? "" : String(cell)));
    });
    return { columns, data };
  }

  function renderFallbackTable(table) {
    const headers = table.headers || [];
    const rows = table.rows || [];
    return `<div class="table-wrap"><table>
      ${
        headers.length
          ? `<thead><tr>${headers.map((h) => `<th>${formatChem(h || "")}</th>`).join("")}</tr></thead>`
          : ""
      }
      <tbody>${rows
        .map((row) => `<tr>${(row || []).map((cell) => `<td>${formatChem(cell || "")}</td>`).join("")}</tr>`)
        .join("")}</tbody>
    </table></div>`;
  }

  function renderOptions(question) {
    const options = question.options || {};
    const labels = ["A", "B", "C", "D"];
    const number = question.questionNumber ?? question.question_number;
    const selected = selections[number];
    const hasOptionsTable = (question.tables || []).some((table) => table.role === "options");

    const optionAsset =
      (question.content || []).find((b) => b.type === "options" && (b.assetPath || b.asset_path)) ||
      (question.visual?.assets || []).find((a) => a.role === "option");

    if (optionAsset && labels.every((label) => options[label]?.requiresVisual || options[label]?.requires_visual)) {
      const src = assetUrl(optionAsset.assetPath || optionAsset.asset_path || optionAsset.path);
      const alreadyShown = (question.content || []).some(
        (block) => block.type === "options" && (block.assetPath || block.asset_path)
      );
      return `<section class="content-block"><div class="label">options</div>${
        !alreadyShown && src
          ? `<img src="${escapeAttr(src)}" alt="Options A–D" loading="lazy" />`
          : ""
      }<div class="options" style="margin-top:0.75rem">${labels
        .map(
          (label) => `
        <button type="button" class="option ${selected === label ? "selected" : ""}" data-option="${label}">
          <span class="key">${label}</span>
          <span class="muted">visual option</span>
        </button>`
        )
        .join("")}</div></section>`;
    }

    const hint = hasOptionsTable
      ? `<div class="muted" style="margin-bottom:0.5rem">Options also shown in the table above.</div>`
      : "";

    return `<section class="content-block"><div class="label">options</div>${hint}<div class="options">${labels
      .map((label) => {
        const option = options[label] || {};
        const visual = option.requiresVisual || option.requires_visual;
        const body = visual
          ? `<span class="muted">&lt;visual&gt;</span>`
          : formatChem(option.text || "—");
        return `
          <button type="button" class="option ${selected === label ? "selected" : ""}" data-option="${label}">
            <span class="key">${label}</span>
            <span>${body}</span>
          </button>`;
      })
      .join("")}</div></section>`;
  }

  function renderParts(parts, depth = 0) {
    if (!parts?.length) return "";
    return `<section class="content-block"><div class="label">${depth ? "sub-parts" : "parts"}</div><div class="parts">${parts
      .map((part) => {
        const marks = part.marks != null ? `<div class="marks">[${part.marks}]</div>` : "";
        return `<div class="part" style="margin-left:${depth * 0.6}rem">
          <strong>(${escapeHtml(part.label)})</strong>
          <div>${formatChem(part.prompt || "")}</div>
          ${marks}
          ${renderParts(part.children || [], depth + 1)}
        </div>`;
      })
      .join("")}</div></section>`;
  }

  function renderIssues(question) {
    const issues = question.validation?.issues || [];
    if (!issues.length) return "";
    return `<section class="issues"><div class="label" style="text-transform:uppercase;font-size:0.75rem;color:var(--muted)">validation</div>${issues
      .map(
        (issue) =>
          `<div class="issue ${escapeAttr(issue.severity || "warning")}"><strong>${escapeHtml(
            issue.code || ""
          )}</strong> — ${escapeHtml(issue.message || "")}</div>`
      )
      .join("")}</section>`;
  }

  function wireOptionClicks(question) {
    const number = question.questionNumber ?? question.question_number;
    questionView.querySelectorAll("[data-option]").forEach((button) => {
      button.addEventListener("click", () => {
        selections[number] = button.getAttribute("data-option");
        showQuestion(index);
      });
    });
  }

  function assetUrl(path) {
    if (!path) return null;
    const normalized = String(path).replace(/\\/g, "/");
    if (/^https?:\/\//i.test(normalized)) return normalized;
    return normalized.startsWith("/") ? normalized : `/${normalized}`;
  }

  function formatChem(text) {
    const value = String(text ?? "");
    if (/<\/?(?:sub|sup)>/i.test(value)) {
      return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/&lt;(\/?(?:sub|sup))&gt;/gi, "<$1>");
    }
    return escapeHtml(value);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }
})();
