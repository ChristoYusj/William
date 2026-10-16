import { settings } from "../shared/engine.js";

const ids = ["apiKey", "baseUrl", "model", "summaryLang", "autoOpenPdf"];
const s = await settings();
for (const id of ids) {
  const el = document.getElementById(id);
  if (el.type === "checkbox") el.checked = !!s[id];
  else el.value = s[id] ?? "";
}
document.getElementById("save").onclick = async () => {
  const v = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    v[id] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  await browser.storage.local.set(v);
  document.getElementById("msg").textContent = "Saved.";
};
