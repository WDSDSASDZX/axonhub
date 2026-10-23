"use strict";
let token = "";
let currentPage = "channels";
let offset = 0;
const $ = (id) => document.getElementById(id);
const labels = { channels: "渠道管理", keys: "API 密钥", requests: "请求记录" };
const statuses = {
  success: "成功",
  failed: "失败",
  disconnected: "客户端断开",
};
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function cell(row, text) {
  const el = node("td", text);
  row.append(el);
  return el;
}
function action(parent, label, callback) {
  const button = node("button", label);
  button.type = "button";
  button.onclick = () => callback().catch(showError);
  parent.append(button);
}
function showError(error) {
  $("notice").textContent = error.message || "操作失败，请重试";
  $("notice").hidden = false;
}
async function api(path, options = {}) {
  const response = await fetch("/admin" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
    },
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401) logout();
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "操作失败，请检查填写的内容",
    );
  }
  return data;
}
function logout() {
  token = "";
  $("console").hidden = true;
  $("login").hidden = false;
  $("created-key").value = "";
  $("new-key").hidden = true;
}
async function refresh() {
  $("notice").hidden = true;
  if (currentPage === "channels") await renderChannels();
  if (currentPage === "keys") await renderKeys();
  if (currentPage === "requests") await renderRequests();
}
async function navigate(page) {
  currentPage = page;
  for (const item of Object.keys(labels))
    $("page-" + item).hidden = item !== page;
  document
    .querySelectorAll("[data-page]")
    .forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("breadcrumb").textContent = labels[page];
  await refresh();
}
async function renderChannels() {
  const channels = await api("/channels");
  $("channel-count").textContent = channels.length;
  $("enabled-count").textContent = channels.filter((c) => c.enabled).length;
  $("dispatch-count").textContent = channels.reduce(
    (total, c) => total + c.requests_sent,
    0,
  );
  $("channel-rows").replaceChildren();
  $("channels-empty").hidden = channels.length > 0;
  for (const channel of channels) {
    const row = node("tr");
    const name = cell(row);
    name.append(node("strong", channel.name), node("small", channel.base_url));
    const models = cell(row);
    Object.entries(channel.model_map).forEach(([alias, upstream]) => {
      models.append(node("code", alias), node("small", "→ " + upstream));
    });
    cell(row, channel.weight);
    cell(
      row,
      channel.requests_sent + " / " + (channel.request_budget ?? "不限"),
    );
    cell(row).append(
      node(
        "span",
        channel.enabled ? (channel.cooling ? "冷却中" : "已启用") : "已停用",
        "badge " +
          (channel.enabled ? (channel.cooling ? "cooling" : "") : "off"),
      ),
    );
    const controls = cell(row);
    action(controls, channel.enabled ? "停用" : "启用", async () => {
      await api("/channels/" + channel.id, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !channel.enabled }),
      });
      await refresh();
    });
    action(controls, "重置计数", async () => {
      await api("/channels/" + channel.id + "/reset-budget", {
        method: "POST",
      });
      await refresh();
    });
    $("channel-rows").append(row);
  }
}
async function renderKeys() {
  const keys = await api("/keys");
  $("key-rows").replaceChildren();
  $("keys-empty").hidden = keys.length > 0;
  for (const key of keys) {
    const row = node("tr");
    cell(row, key.name);
    cell(row).append(node("code", key.prefix + "…"));
    cell(row).append(
      node(
        "span",
        key.enabled ? "有效" : "已撤销",
        "badge " + (key.enabled ? "" : "off"),
      ),
    );
    const controls = cell(row);
    if (key.enabled)
      action(controls, "撤销", async () => {
        await api("/keys/" + key.id, { method: "DELETE" });
        await refresh();
      });
    $("key-rows").append(row);
  }
}
async function renderRequests() {
  const filter = $("status-filter").value;
  const data = await api(
    "/requests?limit=20&offset=" +
      offset +
      (filter ? "&status=" + encodeURIComponent(filter) : ""),
  );
  $("request-rows").replaceChildren();
  $("requests-empty").hidden = data.items.length > 0;
  for (const entry of data.items) {
    const row = node("tr");
    const when = cell(row);
    when.append(
      node(
        "strong",
        new Date(
          entry.created_at.endsWith("Z") ||
            /[+-]\d\d:\d\d$/.test(entry.created_at)
            ? entry.created_at
            : entry.created_at + "Z",
        ).toLocaleString("zh-CN"),
      ),
      node("small", entry.id.slice(0, 8)),
    );
    cell(row).append(node("code", entry.model));
    cell(row).append(
      node(
        "span",
        statuses[entry.status] || entry.status,
        "badge " + entry.status,
      ),
    );
    cell(row, entry.duration_ms.toFixed(0) + " ms");
    cell(row, entry.ttft_ms == null ? "—" : entry.ttft_ms.toFixed(0) + " ms");
    cell(
      row,
      (entry.usage?.prompt_tokens ?? "—") +
        " / " +
        (entry.usage?.completion_tokens ?? "—"),
    );
    action(cell(row), entry.attempts.length + " 次 · 详情", async () => {
      $("trace-content").textContent = JSON.stringify(entry, null, 2);
      $("trace-dialog").showModal();
    });
    $("request-rows").append(row);
  }
  $("request-total").textContent =
    data.total +
    " 条记录" +
    (data.total
      ? " · 当前 " + (offset + 1) + "–" + (offset + data.items.length)
      : "");
  $("previous").disabled = offset === 0;
  $("next").disabled = offset + 20 >= data.total;
}
$("login-form").onsubmit = async (event) => {
  event.preventDefault();
  token = $("admin-token").value;
  $("login-error").textContent = "";
  try {
    await api("/channels");
    $("admin-token").value = "";
    $("login").hidden = true;
    $("console").hidden = false;
    await navigate("channels");
  } catch {
    $("login-error").textContent = "登录失败，请检查管理员凭证和服务状态";
    token = "";
  }
};
$("logout").onclick = logout;
document
  .querySelectorAll("[data-page]")
  .forEach(
    (button) =>
      (button.onclick = () => navigate(button.dataset.page).catch(showError)),
  );
document
  .querySelectorAll(".refresh")
  .forEach((button) => (button.onclick = () => refresh().catch(showError)));
document
  .querySelectorAll(".close-dialog")
  .forEach(
    (button) => (button.onclick = () => button.closest("dialog").close()),
  );
$("channel-dialog").addEventListener("close", () => $("channel-form").reset());
$("add-channel").onclick = () => {
  $("channel-form").reset();
  $("channel-dialog").querySelector(".form-error").textContent = "";
  $("channel-dialog").showModal();
};
$("add-key").onclick = () => {
  $("key-form").reset();
  $("key-dialog").querySelector(".form-error").textContent = "";
  $("key-dialog").showModal();
};
$("channel-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = {
    name: form.get("name"),
    base_url: form.get("base_url"),
    api_key: form.get("api_key"),
    model_map: { [form.get("alias")]: form.get("upstream_model") },
    weight: Number(form.get("weight")),
    request_budget:
      form.get("request_budget") === ""
        ? null
        : Number(form.get("request_budget")),
  };
  try {
    await api("/channels", { method: "POST", body: JSON.stringify(body) });
    $("channel-dialog").close();
    await refresh();
  } catch (error) {
    $("channel-dialog").querySelector(".form-error").textContent =
      error.message;
  }
};
$("key-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const data = await api("/keys", {
      method: "POST",
      body: JSON.stringify({ name: new FormData(event.target).get("name") }),
    });
    $("created-key").value = data.key;
    $("new-key").hidden = false;
    $("key-dialog").close();
    await refresh();
  } catch (error) {
    $("key-dialog").querySelector(".form-error").textContent = error.message;
  }
};
$("copy-key").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("created-key").value);
    $("copy-key").textContent = "已复制";
  } catch {
    showError(new Error("复制失败，请使用浏览器的复制功能"));
  }
};
$("dismiss-key").onclick = () => {
  $("created-key").value = "";
  $("new-key").hidden = true;
  $("copy-key").textContent = "复制";
};
$("status-filter").onchange = () => {
  offset = 0;
  refresh().catch(showError);
};
$("previous").onclick = () => {
  offset = Math.max(0, offset - 20);
  refresh().catch(showError);
};
$("next").onclick = () => {
  offset += 20;
  refresh().catch(showError);
};
