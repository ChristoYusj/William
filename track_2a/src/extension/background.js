import { settings, summarize } from "./shared/engine.js";

const VIEWER = browser.runtime.getURL("viewer/viewer.html");
export const viewerUrl = (file) => VIEWER + "?file=" + encodeURIComponent(file);

// 1. Open PDFs in William's viewer (toggle in settings).
browser.webRequest.onHeadersReceived.addListener(
  async (d) => {
    if (d.type !== "main_frame" || d.method !== "GET" || d.statusCode >= 300) return {};
    if (!(await settings()).autoOpenPdf) return {};
    const ct = (d.responseHeaders || []).find((h) => h.name.toLowerCase() === "content-type")?.value || "";
    const disp = (d.responseHeaders || []).find((h) => h.name.toLowerCase() === "content-disposition")?.value || "";
    const looksPdf = /application\/pdf/i.test(ct) ||
      (/octet-stream/i.test(ct) && (/\.pdf/i.test(disp + d.url) || /^https:\/\/files\.openparldata\.ch\/doc\//.test(d.url)));
    if (!looksPdf) return {};
    return { redirectUrl: viewerUrl(d.url) };
  },
  { urls: ["<all_urls>"], types: ["main_frame"] },
  ["blocking", "responseHeaders"],
);

// 2. Context menus.
browser.menus.create({ id: "w-sel", title: "William: summarise selection", contexts: ["selection"] });
browser.menus.create({ id: "w-page", title: "William: summarise this page", contexts: ["page"] });
browser.menus.create({ id: "w-link", title: "William: open link in William viewer", contexts: ["link"] });
browser.menus.create({ id: "w-batch", title: "William: batch extractor (OpenParlData JSON)", contexts: ["browser_action"] });

async function showInPage(tabId, payload) {
  await browser.tabs.insertCSS(tabId, { file: "/content/panel.css" });
  await browser.tabs.executeScript(tabId, { file: "/content/panel.js" });
  await browser.tabs.sendMessage(tabId, payload);
}

browser.menus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "w-link") return browser.tabs.create({ url: viewerUrl(info.linkUrl) });
  if (info.menuItemId === "w-batch") return browser.tabs.create({ url: browser.runtime.getURL("batch/batch.html") });
  if (tab.url.startsWith(VIEWER)) return; // the viewer has its own buttons
  let text = info.selectionText;
  if (info.menuItemId === "w-page" || !text) {
    [text] = await browser.tabs.executeScript(tab.id, { code: "document.body.innerText" });
  }
  try {
    await showInPage(tab.id, { type: "william-loading" });
    const res = await summarize(text);
    await showInPage(tab.id, { type: "william-summary", res, selection: info.menuItemId === "w-sel" });
  } catch (e) {
    await showInPage(tab.id, { type: "william-error", error: String(e.message || e) }).catch(() => {});
  }
});

// 3. Messages from popup / viewer.
browser.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "open-viewer") return browser.tabs.create({ url: viewerUrl(msg.url) });
  return undefined;
});
