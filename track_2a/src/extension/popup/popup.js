import { settings, summarize, summaryHtml, bindTopics, esc } from "../shared/engine.js";

const $ = (id) => document.getElementById(id);
const VIEWER = browser.runtime.getURL("viewer/viewer.html");
const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
const isPdf = /\.pdf($|\?|#)/i.test(tab.url) && !tab.url.startsWith(VIEWER);
const isViewer = tab.url.startsWith(VIEWER);

if (!(await settings()).apiKey) $("key").style.display = "block";
$("optLink").onclick = $("bOpt").onclick = (e) => { e.preventDefault(); browser.runtime.openOptionsPage(); window.close(); };
$("bBatch").onclick = () => { browser.tabs.create({ url: browser.runtime.getURL("batch/batch.html") }); window.close(); };
if (isPdf || isViewer) {
  $("bPdf").hidden = isViewer;
  $("bPage").hidden = $("bSel").hidden = true;
  $("status").textContent = isViewer ? "Use the buttons in the William viewer's side panel." : "PDFs open in the William viewer (summary, selection, extraction).";
}
$("bPdf").onclick = () => { browser.runtime.sendMessage({ type: "open-viewer", url: tab.url }); window.close(); };

async function run(code, label) {
  $("status").textContent = `Apertus is summarising the ${label}…`;
  $("out").innerHTML = '<div class="spin"></div>';
  try {
    const [text] = await browser.tabs.executeScript(tab.id, { code });
    if (!text || text.trim().length < 20) throw new Error(label === "selection" ? "Select some text on the page first." : "No readable text on this page.");
    const res = await summarize(text);
    $("status").textContent = `Summary · language ${res.language}`;
    $("out").innerHTML = summaryHtml(res);
    bindTopics($("out"), res);
  } catch (e) {
    $("status").textContent = "";
    $("out").innerHTML = `<p class="err">${esc(e.message || e)}</p>`;
  }
}
$("bPage").onclick = () => run("document.body.innerText", "page");
$("bSel").onclick = () => run("window.getSelection().toString()", "selection");
