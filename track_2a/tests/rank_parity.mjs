// JS/Python agreement on topic location + news ranking (python output passed as JSON on stdin)
import { locatePhrase, rankNews } from "../src/extension/shared/core.js";
const cases = JSON.parse(await new Promise((r) => { let s = ""; process.stdin.on("data", (d) => (s += d)); process.stdin.on("end", () => r(s)); }));
let diff = 0;
for (const c of cases.loc) if (JSON.stringify(locatePhrase(c.summary, c.phrase)) !== JSON.stringify(c.py)) { diff++; console.log("LOC", c.phrase, c.py, locatePhrase(c.summary, c.phrase)); }
for (const c of cases.rank) if (JSON.stringify(rankNews(c.items, c.query, 3).map((x) => x.title)) !== JSON.stringify(c.py)) { diff++; console.log("RANK", c.query); }
console.log(`${cases.loc.length + cases.rank.length} cases, ${diff} differences`);
process.exit(diff ? 1 : 0);
