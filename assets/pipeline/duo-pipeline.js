/* duo-pipeline: the duo-ready pipeline, preflight to assets, with a halftone iPhone Duo
   cycling through the pose matrix. Built on ascii-magic-art (MIT), in the style of its
   architecture-map piece. Every motion repeats on PERIOD seconds, so the GIF loops cleanly. */
import { Grid, palette } from "ascii-magic-art/lib/kit.js";

export const meta = {
  slug: "duo-pipeline",
  name: "duo-ready pipeline",
  cols: 98, rows: 28, fps: 12,
  // 0 text, 1 sub, 2 rule, 3 blue, 4 green, 5 orange, 6 purple, 7 cyan, 8 pink, 9 white, a yellow, b link, c red
  palette: palette(["#e6edf3", "#8b949e", "#30363d", "#79c0ff", "#7ee787", "#ffa657", "#d2a8ff", "#56d4dd", "#f778ba", "#ffffff", "#f2cc60", "#6e7681", "#ff7b72"]),
};

export const PERIOD = 12;
const TAU = Math.PI * 2;
const dirOf = (a, b) => (b[0] > a[0] ? "R" : b[0] < a[0] ? "L" : b[1] > a[1] ? "D" : "U");
const CORNER = { RD: "╮", RU: "╯", LD: "╭", LU: "╰", DR: "╰", DL: "╯", UR: "╭", UL: "╮" };
function cellsOf(pts) {
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    let [x, y] = out[out.length - 1];
    const [tx, ty] = pts[i];
    while (x !== tx || y !== ty) { x += Math.sign(tx - x); y += Math.sign(ty - y); out.push([x, y]); }
  }
  return out;
}

const POSES = ["closed-portrait", "closed-landscape", "open-landscape", "open-portrait", "book-landscape", "book-portrait", "closed>open", "open>book"];
// per iteration: which pose cells fail (the story: 3 failures, then 1, then none)
const FAILS = [[1, 4, 6], [4], []];
// device size in cells (w, h) and look per pose; cells are ~1.66x taller than wide
const SHAPE = {
  "closed-portrait": [9, 7, "closed"], "closed-landscape": [17, 6, "closed"],
  "open-landscape": [22, 8, "open"], "open-portrait": [12, 8, "open"],
  "book-landscape": [22, 8, "book"], "book-portrait": [12, 8, "book"],
};

export default function create() {
  const { cols, rows } = meta;
  const g = new Grid(cols, rows);
  const W = 16;
  // name, x, y, label, sub, colour
  const N = {
    preflight: [1, 2, "0 preflight", "Xcode, runtime", "3"],
    detect: [21, 2, "1 detect", "duo.yaml", "3"],
    scan: [41, 2, "2 scan", "36 rules", "7"],
    fix: [61, 2, "3 fix", "1 commit / rule", "7"],
    build: [81, 2, "4 build", ".app + SDK", "6"],
    assert: [81, 21, "6 assert", "ui.json", "6"],
    perf: [61, 21, "7 perf", "perf.json", "6"],
    report: [41, 21, "8 report", "duo-report.html", "a"],
    loop: [21, 21, "9 loop", "rerun failed", "5"],
    assets: [1, 21, "10 assets", "store shots", "4"],
  };
  const right = (k) => N[k][0] + W, left = (k) => N[k][0] - 1, midY = (k) => N[k][1] + 1, cx = (k) => N[k][0] + W / 2;
  const MX = 1, MY = 7, MW = 96, MH = 13; // matrix frame
  // from, to, cells, colour, gap (divides 120 so packets loop on PERIOD), active(phase)
  const always = () => true;
  const EDGES = [
    [cellsOf([[right("preflight"), 3], [left("detect"), 3]]), "3", 6, always],
    [cellsOf([[right("detect"), 3], [left("scan"), 3]]), "3", 6, always],
    [cellsOf([[right("scan"), 3], [left("fix"), 3]]), "7", 6, always],
    [cellsOf([[right("fix"), 3], [left("build"), 3]]), "7", 6, always],
    [cellsOf([[cx("build"), 5], [cx("build"), MY - 1]]), "6", 4, always],
    [cellsOf([[cx("assert"), MY + MH], [cx("assert"), 20]]), "6", 4, always],
    [cellsOf([[left("assert"), 22], [right("perf"), 22]]), "6", 6, always],
    [cellsOf([[left("perf"), 22], [right("report"), 22]]), "a", 6, always],
    [cellsOf([[left("report"), 22], [right("loop"), 22]]), "5", 5, (p) => p < 2],
    [cellsOf([[cx("loop"), 20], [cx("loop"), MY + MH]]), "5", 4, (p) => p < 2],
    [cellsOf([[left("loop"), 22], [right("assets"), 22]]), "4", 5, (p) => p >= 2],
  ];

  function device(t, pose, x0, y0, bw, bh) {
    // closed>open and open>book are transitions: interpolate the shape over the cell's slot
    let w, h, kind, fold = 0;
    const slot = (t % 1);
    if (pose === "closed>open") { const k = 0.5 - 0.5 * Math.cos(slot * TAU); w = Math.round(9 + 13 * k); h = Math.round(7 + k); kind = k > 0.5 ? "open" : "closed"; }
    else if (pose === "open>book") { const k = 0.5 - 0.5 * Math.cos(slot * TAU); w = 22; h = 8; kind = "book"; fold = k; }
    else { [w, h, kind] = SHAPE[pose]; fold = kind === "book" ? 1 : 0; }
    const ox = x0 + Math.floor((bw - w) / 2), oy = y0 + Math.floor((bh - h) / 2);
    const hinge = kind === "closed" ? -1 : Math.floor(w / 2);
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const edge = i === 0 || j === 0 || i === w - 1 || j === h - 1;
      let ch;
      if (edge) ch = "█";
      else {
        // a slow light sweep across the screen; the far half of a book pose sits in shadow
        const v = 0.55 + 0.45 * Math.sin(TAU * (t / PERIOD) * 3 + i * 0.35 - j * 0.5);
        const shadow = i > hinge && hinge > 0 ? fold * 0.45 : 0;
        const s = v - shadow;
        ch = s > 0.8 ? "▓" : s > 0.45 ? "▒" : "░";
      }
      if (i === hinge) ch = kind === "closed" ? ch : "▌";
      g.set(ox + i, oy + j, ch, i === hinge ? "1" : kind === "book" && i > hinge ? "8" : "7");
    }
  }

  return (tRaw) => {
    const t = ((tRaw % PERIOD) + PERIOD) % PERIOD;
    const phase = Math.min(3, Math.floor(t / 3)); // 0..2 matrix iterations, 3 export
    const iter = Math.min(2, phase);
    const inPhase = (t % 3) / 3;
    const cursor = phase < 3 ? Math.min(POSES.length - 1, Math.floor(inPhase * POSES.length)) : -1;
    g.clear();

    // links
    for (const [cells, , , active] of EDGES) {
      const on = active(phase);
      for (let k = 0; k < cells.length; k++) {
        const [x, y] = cells[k];
        if (k === cells.length - 1 || k === 0) { const d = dirOf(cells[Math.max(0, k - 1)], cells[Math.min(cells.length - 1, Math.max(1, k))]); g.set(x, y, d === "U" || d === "D" ? "│" : "─", on ? "b" : "2"); continue; }
        const din = dirOf(cells[k - 1], cells[k]), dout = dirOf(cells[k], cells[k + 1]);
        g.set(x, y, din === dout ? (din === "R" || din === "L" ? "─" : "│") : CORNER[din + dout], on ? "b" : "2");
      }
    }
    // arrow heads
    const head = (x, y, ch, co) => g.set(x, y, ch, co);
    // packets: offset steps 10 cells per second, gaps divide 120, so frame t and t+PERIOD match
    EDGES.forEach(([cells, co, gap, active]) => {
      if (!active(phase)) return;
      const off = Math.floor(t * 10);
      for (let k = off % gap; k < cells.length; k += gap) {
        g.set(cells[k][0], cells[k][1], "●", co);
        if (k > 0) g.set(cells[k - 1][0], cells[k - 1][1], "•", co);
      }
    });

    // nodes
    const busy = { 0: null, 1: null, 2: null, 3: "assets" };
    for (const [k, [x, y, label, sub, co]] of Object.entries(N)) {
      const live = (k === "loop" && phase < 2) || (k === "assets" && phase === 3) || (k !== "loop" && k !== "assets");
      g.box(x, y, W, 3, k === "report" || k === "assets" ? "double" : "round", live ? co : "2");
      g.text(x + 2, y + 1, label, live ? "0" : "1");
      const blink = Math.sin(TAU * (t / PERIOD) * 12 + x) > 0;
      g.set(x + W - 3, y + 1, blink && live ? "●" : "○", k === "loop" && phase < 2 ? "5" : live ? "4" : "2");
      g.text(x + 1, y + 3, sub, "1");
    }
    head(left("detect"), 3, "▸", "3"); head(left("scan"), 3, "▸", "3"); head(left("fix"), 3, "▸", "7"); head(left("build"), 3, "▸", "7");
    head(right("perf"), 22, "◂", "6"); head(right("report"), 22, "◂", "a");
    head(cx("build"), MY - 1, "▾", "6"); head(cx("assert"), 20, "▾", "6"); head(cx("loop"), 20, "▴", phase < 2 ? "5" : "2");
    head(right("loop"), 22, "◂", phase < 2 ? "5" : "2"); head(right("assets"), 22, "◂", phase >= 2 ? "4" : "2");

    // matrix frame
    g.box(MX, MY, MW, MH, "round", "6");
    g.text(MX + 2, MY, " 5 matrix  flow x pose ", "0");
    const status = phase === 3 ? "pass  exporting screenshots" : `iteration ${iter + 1}/3`;
    g.text(MX + MW - 2 - status.length, MY, status, phase === 3 ? "4" : "5");
    // halftone device in the current pose
    const shown = cursor >= 0 ? POSES[cursor] : "open-landscape";
    device(inPhase * POSES.length, shown, MX + 3, MY + 2, 26, 8);
    g.text(MX + 4, MY + MH - 2, shown.padEnd(18), "7");
    // pose cells: two columns, revealed as the cursor reaches them
    const fails = FAILS[iter];
    POSES.forEach((p, i) => {
      const x = MX + 33 + Math.floor(i / 4) * 31, y = MY + 2 + (i % 4) * 2;
      const done = phase === 3 || i < cursor, now = i === cursor;
      const bad = fails.includes(i);
      g.text(x, y, now ? "▸" : " ", "a");
      g.text(x + 2, y, p, now ? "0" : "1");
      const dot = done ? "●" : now ? (Math.sin(TAU * (t / PERIOD) * 24) > 0 ? "●" : "○") : "○";
      const co = done ? (bad && phase < 3 ? "c" : "4") : now ? "a" : "2";
      g.set(x + 20, y, dot, co);
      g.text(x + 22, y, done ? (bad && phase < 3 ? "fail" : "pass") : now ? "run " : "    ", co);
    });
    const nf = phase === 3 ? 0 : fails.filter((i) => i < cursor).length;
    g.text(MX + 33, MY + MH - 2, `pose > launch > steps > capture > tree    ${nf} failing`, "1");

    // header and legend
    g.text(1, 0, "duo-ready", "0"); g.text(11, 0, "iPhone Duo pipeline", "1");
    g.text(cols - 30, 0, "●", phase === 3 ? "4" : "5"); g.text(cols - 28, 0, phase === 3 ? "ready to submit" : "fixing failures", "1");
    g.hline(0, cols - 1, rows - 3, "─", "2");
    g.text(1, rows - 2, "●", "3"); g.text(3, rows - 2, "code", "1");
    g.text(10, rows - 2, "●", "6"); g.text(12, rows - 2, "run + measure", "1");
    g.text(28, rows - 2, "●", "5"); g.text(30, rows - 2, "rerun failed cells (max 3)", "1");
    g.text(59, rows - 2, "●", "4"); g.text(61, rows - 2, "1398x2034  2007x2853  per locale", "1");
    return g.frame();
  };
}
