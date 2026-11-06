#!/usr/bin/env node
/* test_web.js: проверка веб-тренажёра (index.html) без браузера.
   Запуск: node chess/test_web.js   (код возврата 1 при FAIL)

   Страница выполняется в vm с поддельным DOM. Проверяется:
   1. движок правил: perft на 5 эталонных позициях, легальность решений во всех задачах CSV,
      отсутствие падений на ходе чёрных с правом рокировки;
   2. сплит train/test (hashSet) совпадает с Python на общих векторах и на встроенных задачах;
   3. подсказки: рейтинг и темы не видны до ответа, видны после; режим подсказок исключается из отчёта;
   4. лог и экспорт: поля как в chess/session.py;
   5. паритет статистики с Python (common/golden/stats_vectors.json) с точностью 1e-9. */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const crypto = require("crypto");

const HERE = __dirname;
const GOLD = path.join(HERE, "..", "common", "golden");
const html = fs.readFileSync(path.join(HERE, "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

let ok = 0, total = 0;
function check(label, cond) { total++; if (cond) ok++; else console.log("FAIL: " + label); }
function close(a, b) {
  if (a === null || b === null || a === undefined || b === undefined) return a === b;
  if (typeof a === "string" || typeof b === "string") return a === b;
  return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b));
}
function sameObj(a, b) {
  const ka = Object.keys(b);
  return ka.every(function (k) { return close(a[k], b[k]); });
}

// ---------------------------------------------------------------- поддельный DOM
function makeEl(id) {
  const el = {
    id: id, textContent: "", className: "", value: "", checked: false, disabled: false,
    style: {}, dataset: {}, children: [], files: [], handlers: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, fn) { (el.handlers[type] = el.handlers[type] || []).push(fn); },
    appendChild(c) { el.children.push(c); return c; },
    click() { fire(el, "click"); },
    setAttribute() {},
  };
  Object.defineProperty(el, "innerHTML", { get() { return ""; }, set() { el.children.length = 0; } });
  return el;
}
function fire(el, type, ev) {
  (el.handlers[type] || []).forEach(function (f) { f.call(el, ev || { target: el }); });
}
function makePage() {
  const store = {}, blobs = [];
  // элементы создаются при первом обращении, как будто они есть в разметке
  const els = new Proxy({}, { get(t, id) { return t[id] || (t[id] = makeEl(id)); } });
  const ctx = {
    document: {
      getElementById(id) { return els[id]; },
      createElement() { return makeEl(null); },
    },
    console: console, alert() {}, confirm() { return true; },
    localStorage: { getItem(k) { return k in store ? store[k] : null; }, setItem(k, v) { store[k] = String(v); } },
    performance: { now() { return Date.now(); } },
    fetch() { return Promise.reject(new Error("offline")); },
    Blob: function (parts) { blobs.push(parts.join("")); },
    URL: { createObjectURL() { return "blob:test"; } },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(script, ctx, { filename: "index.html" });
  return { ctx: ctx, els: els, store: store, blobs: blobs };
}
function csvRows(file) {
  return fs.readFileSync(file, "utf8").split(/\r?\n/).filter(function (l) { return l.trim(); }).slice(1).map(function (l) {
    const p = l.split(",");
    return { id: p[0], fen: p[1], sol: p[2], rating: +p[3], themes: p[4] || "" };
  });
}

// ---------------------------------------------------------------- 1. загрузка и движок правил
const page = makePage();
const ctx = page.ctx;
check("страница загружается, встроено 200 задач", ctx.POOL.length === 200);

let md5bad = 0;
["", "abc", "00008", "0000D", "x".repeat(100)].forEach(function (s) {
  if (ctx.md5(s) !== crypto.createHash("md5").update(s).digest("hex")) md5bad++;
});
check("md5 в JS совпадает с crypto", md5bad === 0);

function perft(st, d) {
  if (d === 0) return 1;
  const ms = ctx.genLegal(st, st.turn);
  if (d === 1) return ms.length;
  let n = 0;
  for (const m of ms) n += perft(ctx.makeMove(st, m), d - 1);
  return n;
}
const POS = [
  ["startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", [20, 400, 8902, 197281]],
  ["kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039, 97862]],
  ["pos3", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238]],
  ["pos4", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467]],
  ["pos5", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]],
];
POS.forEach(function (p) {
  const st = ctx.parseFEN(p[1]);
  let got = [];
  try { for (let d = 1; d <= p[2].length; d++) got.push(perft(st, d)); } catch (e) { got = [String(e.message)]; }
  check("perft " + p[0] + " " + JSON.stringify(p[2]), JSON.stringify(got) === JSON.stringify(p[2]));
});

const PUZ = csvRows(path.join(HERE, "puzzles_sample.csv"));
let thrown = 0, illegal = 0, blackCastle = [];
PUZ.forEach(function (r) {
  let st;
  try {
    st = ctx.parseFEN(r.fen);
    const legal = ctx.genLegal(st, st.turn);
    if (!legal.some(function (m) { return ctx.moveUCI(m) === r.sol; })) illegal++;
  } catch (e) { thrown++; }
  if (st && st.turn === "b" && /[kq]/.test(st.castling) && st.board[4] && st.board[4].t === "k") blackCastle.push(r);
});
check("2000 задач CSV: генерация ходов без исключений (" + thrown + ")", thrown === 0 && PUZ.length === 2000);
check("2000 задач CSV: решение всегда легально (" + illegal + ")", illegal === 0);
check("в выборке есть ход чёрных с правами k/q (" + blackCastle.length + " задач), и они не падают", blackCastle.length > 0);

// ---------------------------------------------------------------- 2. сплит
const hv = JSON.parse(fs.readFileSync(path.join(GOLD, "holdout_vectors.json"), "utf8"));
check("hashSet совпадает с Python на " + hv.length + " векторах", hv.every(function (v) { return ctx.hashSet(v[0]) === v[1]; }));
check("метки set у встроенных 200 задач совпадают с hashSet", ctx.POOL.every(function (p) { return p.set === ctx.hashSet(p.id); }));
check("hashSet совпадает с точным BigInt-расчётом на всех 2000 id", PUZ.every(function (r) {
  const exact = Number(BigInt("0x" + crypto.createHash("md5").update(r.id).digest("hex")) % 1000n) / 1000 < 0.5;
  return ctx.hashSet(r.id) === (exact ? "train" : "test");
}));

// ---------------------------------------------------------------- 3. интерфейс: подсказки, лог, экспорт
function setup(pg, o) {
  pg.els.setSel.value = o.set || "train";
  pg.els.nInput.value = String(o.n || 4);
  pg.els.rating.value = "1600";
  pg.els.nick.value = o.nick === undefined ? "tester" : o.nick;
  pg.els.hintsChk.checked = !!o.hints;
  pg.els.startBtn.click();
}
function playSession(pg, n, wrongEvery) {
  const seen = [];
  for (let i = 0; i < n; i++) {
    const s = pg.ctx.session, p = s.puzzle;
    const before = pg.els.puzzleInfo.textContent;
    const wantWrong = wrongEvery && i % wrongEvery === 1;
    const mv = s.legal.filter(function (m) { return (pg.ctx.moveUCI(m) !== p.sol) === wantWrong; })[0] || s.legal[0];
    if (i === 0 && !wantWrong) {   // один раз идём настоящим путём: клики по клеткам
      pg.ctx.onSquare(mv.from);
      const cell = pg.els.board.children.filter(function (c) { return +c.dataset.sq === mv.to; })[0];
      if (mv.promotion) pg.ctx.applyMove(mv); else fire(cell, "click");
    } else pg.ctx.applyMove(mv);
    pg.els.conf.value = "70";
    pg.els.submitBtn.click();
    seen.push({ p: p, before: before, after: pg.els.feedback.textContent, correct: pg.ctx.moveUCI(mv) === p.sol });
    pg.els.nextBtn.click();
  }
  return seen;
}

const A = makePage();
setup(A, { n: 4 });
const runA = playSession(A, 4, 2);
check("без подсказок: до ответа в строке задачи нет рейтинга и тем",
  runA.every(function (x) { return !/рейтинг|темы/.test(x.before) && x.before.indexOf(x.p.themes) === -1; }));
check("после ответа показаны рейтинг и темы задачи",
  runA.every(function (x) { return x.after.indexOf("Рейтинг задачи " + x.p.rating) !== -1 && x.after.indexOf(x.p.themes) !== -1; }));
check("итог сессии выведен, в анализе 4 задачи",
  A.els.reportOut.textContent.indexOf("--- итог сессии ---") === 0 && A.els.reportOut.textContent.indexOf("задач в анализе: 4") !== -1);
const rowA = A.ctx.log[0];
check("строка лога: ts, user, session, hints=0",
  /^\d{4}-\d\d-\d\dT/.test(rowA.ts) && rowA.user === "tester" && /^\d{8}T\d{6}-\w{6}$/.test(rowA.session) && rowA.hints === 0);
check("все строки сессии с одним id сессии", A.ctx.log.length === 4 && A.ctx.log.every(function (r) { return r.session === rowA.session; }));
check("верные и неверные ответы записаны (correct 0 и 1)",
  A.ctx.log.some(function (r) { return r.correct === 1; }) && A.ctx.log.some(function (r) { return r.correct === 0; }));
check("лог сохранён в localStorage", JSON.parse(A.store.qgt_log).length === 4);

A.els.exportBtn.click();
const csvText = A.blobs[A.blobs.length - 1] || "";
const header = csvText.split("\n")[0];
const pyFields = (fs.readFileSync(path.join(HERE, "session.py"), "utf8").match(/FIELDS = \[([\s\S]*?)\]/)[1].match(/"([^"]+)"/g) || [])
  .map(function (s) { return s.replace(/"/g, ""); });
check("заголовок экспорта совпадает с FIELDS в session.py", header === pyFields.join(",") && pyFields.length === 20);
check("экспорт: 4 строки данных", csvText.split("\n").length === 5);

const B = makePage();
setup(B, { n: 3, hints: true, nick: "" });
const runB = playSession(B, 3, 0);
check("режим подсказок: рейтинг и темы видны до ответа",
  runB.every(function (x) { return /рейтинг/.test(x.before) && x.before.indexOf(x.p.themes) !== -1; }));
check("режим подсказок: hints=1 в логе, user=anon", B.ctx.log.every(function (r) { return r.hints === 1 && r.user === "anon"; }));
check("отчёт исключает строки с подсказками", /все строки лога с подсказками/.test(B.ctx.buildReport(B.ctx.log)));
const mixed = A.ctx.log.concat(B.ctx.log);
check("смешанный лог: в анализе только строки без подсказок",
  B.ctx.buildReport(mixed).indexOf("задач в анализе: 4 (с подсказками исключено: 3)") === 0);
check("пустой лог", B.ctx.buildReport([]) === "лог пуст");

// ход чёрных с правом рокировки не должен ронять показ задачи
const C = makePage();
C.ctx.POOL = blackCastle.map(function (r) { return Object.assign({}, r, { set: "train" }); });
let uiErr = null;
try {
  setup(C, { n: Math.min(100, blackCastle.length) });
  for (let i = 1; i < C.ctx.session.queue.length; i++) C.els.nextBtn.click();
} catch (e) { uiErr = e; }
check("показ " + blackCastle.length + " задач с ходом чёрных и рокировкой без исключений" + (uiErr ? " (" + uiErr.message + ")" : ""), uiErr === null);

// ---------------------------------------------------------------- 4. паритет статистики с Python
const sv = JSON.parse(fs.readFileSync(path.join(GOLD, "stats_vectors.json"), "utf8"));
check("wilson: " + sv.wilson.length + " векторов", sv.wilson.every(function (v) {
  const w = ctx.wilson(v[0], v[1]);
  return close(w[0], v[2]) && close(w[1], v[3]);
}));
sv.datasets.forEach(function (d) {
  check("паритет [" + d.name + "]: сводка калибровки", sameObj(ctx.calibrationSummary(d.records), d.summary));
  const rel = ctx.reliability(d.records);
  check("паритет [" + d.name + "]: корзины", rel.length === d.reliability.length && rel.every(function (b, i) { return sameObj(b, d.reliability[i]); }));
  const tt = ctx.themeTable(d.records), py = d.theme_table;
  check("паритет [" + d.name + "]: таблица тем (" + py.rows.length + " строк, tau2, усадка, флаги)",
    tt.rows.length === py.rows.length && tt.k === py.k && tt.n === py.n && close(tt.tau2, py.tau2) && close(tt.grand, py.grand) &&
    tt.rows.every(function (r, i) { return sameObj(r, py.rows[i]); }));
});
check("в векторах есть флаг weak (проверяется непустой случай)", sv.datasets.some(function (d) {
  return d.theme_table.rows.some(function (r) { return r.flag === "weak"; });
}));
check("tasksForGap(0.15) = 132 как в Python", ctx.tasksForGap(0.15) === 132);

// ---------------------------------------------------------------- 5. режимы: паритет скоринга и UI
const mv = JSON.parse(fs.readFileSync(path.join(GOLD, "mode_vectors.json"), "utf8"));
check("паритет scoreIntuition: " + mv.intuition.length + " векторов", mv.intuition.every(function (v) {
  const r = ctx.scoreIntuition(v.fen, v.move, v.sol, v.themes, v.dt, v.limit);
  return r.correct === v.correct && r.winning === v.winning && r.timeout === v.timeout && r.confidence === v.confidence;
}));
check("паритет scoreCalc: " + mv.calc.length + " векторов", mv.calc.every(function (v) {
  const r = ctx.scoreCalc(v.fen, v.entered, v.sol_line);
  return r.strict === v.strict && r.depth === v.depth;
}));

function makeClockPage() {
  const pg = makePage();
  let now = 1000000;
  pg.ctx.performance.now = function () { return now; };
  pg.advance = function (ms) { now += ms; };
  return pg;
}
function setupMode(pg, o) {
  pg.els.setSel.value = o.set || "train";
  pg.els.nInput.value = String(o.n || 2);
  pg.els.rating.value = String(o.rating || 886);
  pg.els.nick.value = "tester";
  pg.els.modeSel.value = o.mode;
  pg.els.startBtn.click();
}
function calcRows(file) {
  return fs.readFileSync(file, "utf8").split(/\r?\n/).filter(function (l) { return l.trim(); }).slice(1).map(function (l) {
    const p = l.split(",");
    return { id: p[0], fen: p[1], sol: p[2], line: p[3], rating: +p[4], themes: p[5] || "" };
  });
}

// интуиция: полоса, верный ход вовремя, таймаут, исключение виденных
const I = makeClockPage();
setupMode(I, { mode: "intuition", n: 3, rating: 886 });
check("intuition: очередь только в полосе ±200 и сете train",
  I.ctx.session.queue.length > 0 && I.ctx.session.queue.every(function (p) { return p.set === "train" && Math.abs(p.rating - 886) <= 200; }));
const sI = I.ctx.session, pI = sI.puzzle;
const solMv = sI.legal.filter(function (m) { return I.ctx.moveUCI(m) === pI.sol; })[0];
I.advance(3000);
I.ctx.applyMove(solMv);
I.els.conf.value = "70";
I.els.submitBtn.click();
check("intuition: верный ход вовремя -> correct 1, timeout 0, уверенность из слайдера",
  I.ctx.log[0].mode === "intuition" && I.ctx.log[0].correct === 1 && I.ctx.log[0].timeout === 0 && I.ctx.log[0].confidence === 70);
I.els.nextBtn.click();
I.advance(11000);
const sI2 = I.ctx.session, anyMv = sI2.legal[0];
I.ctx.applyMove(anyMv);
check("intuition: ход после 11 с -> таймаут, промах, уверенность 0, без кнопки «Ответить»",
  I.ctx.log[1].mode === "intuition" && I.ctx.log[1].correct === 0 && I.ctx.log[1].timeout === 1 &&
  I.ctx.log[1].confidence === 0 && /ТАЙМАУТ/.test(I.els.feedback.textContent));
const solvedI = I.ctx.log.map(function (r) { return r.puzzle_id; });
setupMode(I, { mode: "intuition", n: 3, rating: 886 });
check("intuition: уже решённые id не предлагаются снова",
  I.ctx.session.queue.every(function (p) { return solvedI.indexOf(p.id) === -1; }));

// интуиция: альтернативный мат в mateIn1 (задача 00EWi из векторов)
const M = makeClockPage();
const vMate = mv.intuition.filter(function (v) { return v.move === "h6h5"; })[0];
const rowMate = PUZ.filter(function (r) { return r.fen === vMate.fen; })[0];
M.ctx.POOL = [{ id: "00EWi", fen: vMate.fen, sol: vMate.sol, rating: rowMate.rating, themes: vMate.themes, set: "train" }];
setupMode(M, { mode: "intuition", n: 1, rating: rowMate.rating });
const altMv = M.ctx.session.legal.filter(function (m) { return M.ctx.moveUCI(m) === "h6h5"; })[0];
M.ctx.applyMove(altMv);
M.els.conf.value = "70";
M.els.submitBtn.click();
check("intuition: альтернативный мат в mateIn1 засчитан", M.ctx.log[0].correct === 1 && M.ctx.log[0].mode === "intuition");

// classic: другой выигрыш теперь считается движком (задача 0000D из векторов)
const W = makeClockPage();
const vWin = mv.intuition.filter(function (v) { return v.move === "b6d6"; })[0];
const rowWin = PUZ.filter(function (r) { return r.fen === vWin.fen; })[0];
W.ctx.POOL = [{ id: "0000D", fen: vWin.fen, sol: vWin.sol, rating: rowWin.rating, themes: vWin.themes, set: "train" }];
setupMode(W, { mode: "classic", n: 1, rating: rowWin.rating });
const winMv = W.ctx.session.legal.filter(function (m) { return W.ctx.moveUCI(m) === "b6d6"; })[0];
W.ctx.applyMove(winMv);
W.els.conf.value = "70";
W.els.submitBtn.click();
check("classic: другой выигрыш -> winning 1, correct 0", W.ctx.log[0].winning === 1 && W.ctx.log[0].correct === 0);
check("classic: фидбэк «ВЫИГРЫШ (другой ход)»", /ВЫИГРЫШ \(другой ход\)/.test(W.els.feedback.textContent));

// расчёт: полоса, верная линия, ошибка на 2-м ходу, мягкий лимит, экспорт
const CC = makeClockPage();
setupMode(CC, { mode: "calc", n: 2, rating: 886 });
check("calc: очередь из CALC_POOL, полоса ±200, сет train",
  CC.ctx.session.queue.length > 0 && CC.ctx.session.queue.every(function (p) { return p.line && p.set === "train" && Math.abs(p.rating - 886) <= 200; }));
const pC = CC.ctx.session.puzzle;
CC.els.lineInput.value = pC.line;
CC.els.conf.value = "70";
CC.els.submitBtn.click();
check("calc: верная линия -> strict 1, depth = длине линии",
  CC.ctx.log[0].mode === "calc" && CC.ctx.log[0].strict === 1 &&
  CC.ctx.log[0].depth === pC.line.split(" ").length && CC.ctx.log[0].line === pC.line);
CC.els.nextBtn.click();
const pC2 = CC.ctx.session.puzzle;
const sol2 = pC2.line.split(" ");
CC.advance(181000);
CC.els.lineInput.value = sol2[0] + " a1a1 " + sol2.slice(2).join(" ");
CC.els.conf.value = "60";
CC.els.submitBtn.click();
check("calc: ошибка на 2-м ходу -> strict 0, depth 1", CC.ctx.log[1].strict === 0 && CC.ctx.log[1].depth === 1);
check("calc: мягкий лимит 180 с только логируется",
  /Мягкий лимит превышен/.test(CC.els.feedback.textContent) && CC.ctx.log[1].seconds > 180);
CC.els.exportBtn.click();
const csvC = CC.blobs[CC.blobs.length - 1] || "";
check("экспорт: строки calc с line/depth/strict/mode (20 колонок)",
  csvC.split("\n").length === 3 && csvC.split("\n")[1].split(",").length === 20 && /calc/.test(csvC));

// отчёт разделяет режимы и даёт профиль
const mixedModes = A.ctx.log.concat(I.ctx.log, CC.ctx.log);
const rep = B.ctx.buildReport(mixedModes);
check("отчёт: разделы по режимам intuition и calc",
  rep.indexOf("===== режим intuition =====") !== -1 && rep.indexOf("===== режим calc =====") !== -1);
check("отчёт: профиль «выводы рано» при n < 100", /профиль: выводы рано/.test(rep));

console.log("web selftest: " + ok + "/" + total);
process.exit(ok === total ? 0 : 1);
