(function () {
  "use strict";

  const data = window.SRWZ_STORY_VIEWER_DATA;
  if (!data) {
    document.body.innerHTML = "<main class='no-results'>缺少剧情数据。请先在仓库根目录运行 <code>python3 tools/build_story_viewer.py</code>，再打开 <code>work/review/local-model/story-viewer/index.html</code>。</main>";
    return;
  }

  const resourceByStage = new Map(data.resource_stages.map((stage) => [String(stage.stage_index), stage]));
  const titleByOrdinal = data.stage_titles || {};
  const state = {
    stage: null,
    filter: "all",
    query: "",
    selectedKey: null,
    routeOrdinal: null,
  };

  const $ = (selector) => document.querySelector(selector);
  const escapeText = (value) => String(value == null ? "" : value);

  function setText(element, value) {
    element.textContent = escapeText(value);
    return element;
  }

  function statusClass(status) {
    if (status === "已审校") return "reviewed";
    if (status === "机器草稿") return "machine";
    if (status === "待翻译") return "missing";
    return "existing";
  }

  function entryMatches(entry, stage) {
    const status = entry.display_status;
    if (state.filter === "translated" && !entry.display_translation) return false;
    if (state.filter === "machine" && status !== "机器草稿") return false;
    if (state.filter === "missing" && status !== "待翻译") return false;
    if (!state.query) return true;
    const speakerText = (entry.speakers || []).map((speaker) => `${speaker.source} ${speaker.translation}`).join(" ");
    const haystack = `${stage.stage_index} ${entry.source_text} ${entry.display_translation} ${speakerText} ${(entry.occurrence_ids || []).join(" ")}`.toLowerCase();
    return haystack.includes(state.query.toLowerCase());
  }

  function allEntries() {
    const rows = [];
    for (const stage of data.resource_stages) {
      for (const section of stage.sections) {
        for (const entry of section.entries) rows.push({ stage, section, entry });
      }
    }
    return rows;
  }

  function renderTopStats() {
    const target = $("#top-stats");
    target.replaceChildren();
    const stats = [
      [data.counts.resource_stages, "资源段"],
      [data.counts.unique, "独特对白"],
      [data.counts.occurrences, "出现次数"],
      [data.counts.reviewed, "已审校"],
      [data.counts.missing, "待翻译"],
    ];
    for (const [number, label] of stats) {
      const item = document.createElement("div");
      item.className = "stat";
      const strong = document.createElement("strong");
      setText(strong, Number(number).toLocaleString("zh-CN"));
      const span = document.createElement("span");
      setText(span, label);
      item.append(strong, span);
      target.append(item);
    }
    setText($("#resource-count"), `${data.resource_stages.length} 段`);
    setText($("#source-note"), `队列 SHA-256 ${data.source.queue_sha256.slice(0, 16)}…`);
  }

  function renderRoutes() {
    const target = $("#route-list");
    target.replaceChildren();
    for (const group of data.route_groups) {
      const details = document.createElement("details");
      details.className = "route-group";
      details.open = true;
      const summary = document.createElement("summary");
      setText(summary, group.heading);
      details.append(summary);
      for (const row of group.rows) {
        const cells = row.titles || [];
        const titles = cells.filter(Boolean);
        if (!titles.length) {
          if (row.cells && row.cells.length) {
            const text = document.createElement("div");
            text.className = "route-row";
            text.style.gridTemplateColumns = "1fr";
            setText(text, row.cells.join(" · "));
            details.append(text);
          }
          continue;
        }
        for (const title of titles) {
          const item = document.createElement("div");
          item.className = "route-row";
          if (state.routeOrdinal === title.ordinal) item.style.background = "rgba(108, 230, 232, .16)";
          const ordinal = document.createElement("span");
          ordinal.className = "route-ordinal mono";
          setText(ordinal, String(title.ordinal).padStart(3, "0"));
          const body = document.createElement("span");
          const local = titleByOrdinal[String(title.ordinal)] || titleByOrdinal[title.ordinal] || {};
          const translated = local.translation || title.title;
          setText(body, translated);
          if (title.source_title) {
            const source = document.createElement("span");
            source.className = "route-source";
            setText(source, title.source_title);
            body.append(source);
          }
          item.append(ordinal, body);
          item.addEventListener("click", () => {
            state.routeOrdinal = title.ordinal;
            renderRoutes();
          });
          details.append(item);
        }
      }
      target.append(details);
    }
  }

  function renderResources() {
    const target = $("#resource-list");
    target.replaceChildren();
    for (const stage of data.resource_stages) {
      const button = document.createElement("button");
      button.className = "resource-button" + (String(stage.stage_index) === String(state.stage) ? " active" : "");
      const label = document.createElement("span");
      label.className = "resource-label mono";
      const name = document.createElement("span");
      setText(name, stage.label);
      const count = document.createElement("span");
      setText(count, stage.unique_count);
      label.append(name, count);
      const small = document.createElement("small");
      setText(small, `${stage.translated_count}/${stage.unique_count} 有译文`);
      button.append(label, small);
      button.addEventListener("click", () => selectStage(stage.stage_index));
      target.append(button);
    }
  }

  function renderSpeaker(entry) {
    const speakers = entry.speakers || [];
    if (!speakers.length) return null;
    const wrap = document.createElement("span");
    wrap.className = "speaker";
    const names = speakers.map((speaker) => speaker.translation || speaker.source || `#${speaker.id}`);
    setText(wrap, names.join(" / "));
    const sourceNames = speakers.map((speaker) => speaker.source).filter(Boolean);
    if (sourceNames.length) {
      const source = document.createElement("span");
      source.className = "speaker-source";
      setText(source, `（${sourceNames.join(" / ")}）`);
      wrap.append(source);
    }
    return wrap;
  }

  function renderEntry(stage, section, entry) {
    const article = document.createElement("article");
    const key = `${stage.stage_index}:${entry.unique_index}:${entry.source_hash}`;
    article.className = "entry" + (state.selectedKey === key ? " selected" : "");
    article.addEventListener("click", () => {
      state.selectedKey = key;
      renderDetails(stage, section, entry);
      document.querySelectorAll(".entry.selected").forEach((node) => node.classList.remove("selected"));
      article.classList.add("selected");
    });
    const head = document.createElement("div");
    head.className = "entry-head";
    const speaker = renderSpeaker(entry);
    if (speaker) head.append(speaker);
    const badge = document.createElement("span");
    badge.className = `badge ${statusClass(entry.display_status)}`;
    setText(badge, entry.display_status);
    head.append(badge);
    const translation = document.createElement("p");
    translation.className = "translation" + (entry.display_translation ? "" : " missing-text");
    setText(translation, entry.display_translation || "〈待翻译〉");
    const actions = document.createElement("div");
    actions.className = "entry-actions";
    const sourceButton = document.createElement("button");
    setText(sourceButton, "查看原文");
    sourceButton.addEventListener("click", (event) => {
      event.stopPropagation();
      const details = article.querySelector("details");
      details.open = !details.open;
    });
    const meta = document.createElement("span");
    meta.className = "entry-meta mono";
    setText(meta, `${entry.occurrence_count} 次出现 · ${entry.source_hash.slice(0, 10)}…`);
    actions.append(sourceButton, meta);
    const sourceDetails = document.createElement("details");
    sourceDetails.className = "source-details";
    const summary = document.createElement("summary");
    setText(summary, "日文原文与结构信息");
    const source = document.createElement("div");
    source.className = "source-text";
    setText(source, entry.source_text);
    sourceDetails.append(summary, source);
    if (entry.structural_tokens && entry.structural_tokens.length) {
      const tokens = document.createElement("div");
      tokens.className = "entry-meta mono";
      setText(tokens, `保留标记：${entry.structural_tokens.join(" ")}`);
      sourceDetails.append(tokens);
    }
    article.append(head, translation, actions, sourceDetails);
    return article;
  }

  function renderReader() {
    const stage = resourceByStage.get(String(state.stage));
    const target = $("#reader");
    target.replaceChildren();
    if (!stage) {
      const empty = document.createElement("div");
      empty.className = "no-results";
      setText(empty, "没有可显示的资源段。");
      target.append(empty);
      return;
    }
    const header = document.createElement("header");
    header.className = "reader-header";
    const heading = document.createElement("h2");
    setText(heading, `${stage.label} · 剧情对白`);
    const note = document.createElement("p");
    setText(note, `${stage.unique_count} 条独特对白 · ${stage.occurrence_count} 次出现 · ${stage.translated_count} 条已有显示文本`);
    header.append(heading, note);
    target.append(header);
    let visible = 0;
    for (const section of stage.sections) {
      const entries = section.entries.filter((entry) => entryMatches(entry, stage));
      if (!entries.length) continue;
      visible += entries.length;
      const sectionNode = document.createElement("section");
      sectionNode.className = "section";
      const title = document.createElement("h3");
      title.className = "section-title";
      setText(title, section.name);
      sectionNode.append(title);
      for (const entry of entries) sectionNode.append(renderEntry(stage, section, entry));
      target.append(sectionNode);
    }
    if (!visible) {
      const noResults = document.createElement("div");
      noResults.className = "no-results";
      setText(noResults, "当前筛选条件下没有条目。");
      target.append(noResults);
    }
    setText($("#search-summary"), state.query ? `资源 ${stage.stage_index} 中匹配 ${visible} 条` : "点击条目可在右侧查看详细来源信息");
  }

  function renderDetails(stage, section, entry) {
    const target = $("#details");
    target.className = "details";
    target.replaceChildren();
    const heading = document.createElement("h3");
    setText(heading, `资源 ${stage.stage_index} · 条目 ${entry.unique_index}`);
    const dl = document.createElement("dl");
    const rows = [
      ["状态", entry.display_status],
      ["分段", section.name],
      ["出现次数", entry.occurrence_count],
      ["说话人", (entry.speakers || []).map((speaker) => speaker.translation || speaker.source || `#${speaker.id}`).join(" / ") || "—"],
      ["哈希", entry.source_hash],
    ];
    for (const [label, value] of rows) {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      setText(dt, label);
      setText(dd, value || "—");
      if (label === "哈希") dd.className = "mono";
      dl.append(dt, dd);
    }
    const source = document.createElement("div");
    source.className = "source-text";
    setText(source, entry.source_text);
    target.append(heading, dl, source);
    if (entry.occurrence_ids && entry.occurrence_ids.length) {
      const ids = document.createElement("p");
      ids.className = "entry-meta mono";
      setText(ids, entry.occurrence_ids.join("\n"));
      target.append(ids);
    }
  }

  function selectStage(stageIndex, updateHash = true) {
    state.stage = Number(stageIndex);
    if (updateHash) history.replaceState(null, "", `#stage=${String(stageIndex).padStart(3, "0")}`);
    renderResources();
    renderReader();
  }

  function initialStage() {
    const match = location.hash.match(/stage=(\d+)/);
    if (match && resourceByStage.has(String(Number(match[1])))) return Number(match[1]);
    return data.resource_stages[0] ? data.resource_stages[0].stage_index : null;
  }

  $("#search-input").addEventListener("input", (event) => {
    state.query = event.target.value.trim();
    renderReader();
  });
  document.querySelectorAll(".filter").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll(".filter").forEach((node) => node.classList.toggle("active", node === button));
      renderReader();
    });
  });
  window.addEventListener("hashchange", () => {
    const stage = initialStage();
    if (stage !== state.stage) selectStage(stage, false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
    const index = data.resource_stages.findIndex((stage) => stage.stage_index === state.stage);
    if (event.key === "ArrowRight" && index < data.resource_stages.length - 1) selectStage(data.resource_stages[index + 1].stage_index);
    if (event.key === "ArrowLeft" && index > 0) selectStage(data.resource_stages[index - 1].stage_index);
  });

  renderTopStats();
  renderRoutes();
  selectStage(initialStage(), false);
})();
