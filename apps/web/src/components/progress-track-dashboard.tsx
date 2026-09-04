"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { Activity, Capture, Floor, HumanProgressEntry } from "@/lib/types";

type DashboardTab = "overview" | "details" | "productivity";
type DetailFilter = "all" | "not-started" | "in-progress" | "complete" | "behind";

type Props = {
  activities: Activity[];
  captures: Capture[];
  floors: Floor[];
  initialCaptureId: string | null;
  progress: HumanProgressEntry[];
  projectId: string;
};

const floorGroups = [
  { key: "1.2.1", label: "ชั้น 1", levelIndex: 1 },
  { key: "1.2.2", label: "ชั้น 2", levelIndex: 2 },
  { key: "1.2.3", label: "ชั้น 3", levelIndex: 3 },
  { key: "1.2.4", label: "ชั้น 4", levelIndex: 4 },
  { key: "1.2.5", label: "ชั้นหลังคา", levelIndex: 5 },
  { key: "1.2.6", label: "ดาดฟ้า", levelIndex: 6 },
] as const;

const workGroups = [
  { key: "foundation", label: "ฐานราก/ตอม่อ", test: (name: string) => /ฐานราก|ตอม่อ|ขุดดิน|ถมดิน/.test(name) },
  { key: "beam", label: "คาน", test: (name: string) => /คาน/.test(name) },
  { key: "slab", label: "พื้น", test: (name: string) => /พื้น|Topping/.test(name) },
  { key: "column", label: "เสา", test: (name: string) => /เสา/.test(name) && !/ตอม่อ/.test(name) },
  { key: "stair", label: "บันได", test: (name: string) => /บันได/.test(name) },
  { key: "roof", label: "หลังคา", test: (name: string) => /หลังคา/.test(name) },
] as const;

function time(value: string) {
  const result = new Date(value).getTime();
  return Number.isFinite(result) ? result : 0;
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("th-TH", { day: "2-digit", month: "short", year: "2-digit" });
}

function plannedPercent(activity: Activity, at: number) {
  const start = time(activity.planned_start);
  const finish = time(activity.planned_finish);
  if (at < start) return 0;
  if (at >= finish || finish <= start) return 100;
  return Math.max(0, Math.min(100, ((at - start) / (finish - start)) * 100));
}

function statusOf(actual: number | null, planned: number): Exclude<DetailFilter, "all"> {
  if (actual === null || actual <= 0) return "not-started";
  if (actual >= 100) return "complete";
  if (actual + 20 < planned) return "behind";
  return "in-progress";
}

const statusText = {
  "not-started": "ยังไม่เริ่ม",
  "in-progress": "กำลังทำ",
  complete: "เสร็จแล้ว",
  behind: "ล่าช้า",
} as const;

function evidenceKeyframe(note: string | null) {
  return note?.match(/\[keyframe:([0-9a-f-]{36})\]/i)?.[1] ?? null;
}

function cleanNote(note: string | null) {
  if (!note) return "—";
  return note
    .replace(/\s*\|?\s*หลักฐานภาพ 360 เวลา[^[]*\[keyframe:[^\]]+\]/i, "")
    .replace(/\s*\|?\s*หลักฐานจาก Capture นี้.*$/i, "")
    .trim() || "—";
}

function csvCell(value: string | number) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

type MatrixCell = {
  key: string;
  label: string;
  rows: Array<unknown>;
  reviewed: number;
  percent: number | null;
  status: Exclude<DetailFilter, "all"> | null;
};

function ProgressMatrixCell({ breakdown, cell, onOpen }: { breakdown: "status" | "percent" | "quantity"; cell: MatrixCell; onOpen: () => void }) {
  if (!cell.rows.length) return <span className="track-cell-empty">—</span>;
  const percent = cell.percent ?? 0;
  return <button className={`openspace-progress-cell is-${cell.status}`} onClick={onOpen} type="button">
    {breakdown === "status" && <span className={`track-status is-${cell.status}`}>{cell.status ? statusText[cell.status] : "—"}</span>}
    {breakdown === "percent" && <><span className="cell-progress-bar"><i style={{ width: `${percent}%` }} /></span><strong>{percent.toFixed(0)}%</strong></>}
    {breakdown === "quantity" && <><strong>{cell.reviewed} / {cell.rows.length}</strong><small>รายการที่ตรวจแล้ว</small></>}
  </button>;
}

export function ProgressTrackDashboard({ activities, captures, floors, initialCaptureId, progress, projectId }: Props) {
  const [tab, setTab] = useState<DashboardTab>("overview");
  const [breakdown, setBreakdown] = useState<"status" | "percent" | "quantity">("percent");
  const [captureId, setCaptureId] = useState(initialCaptureId ?? captures[0]?.id ?? "");
  const [filter, setFilter] = useState<DetailFilter>("all");
  const [query, setQuery] = useState("");
  const captureDates = useMemo(() => {
    const unique = new Map<string, Capture>();
    for (const capture of captures) {
      const key = new Date(capture.captured_at).toLocaleDateString("en-CA", { timeZone: "Asia/Bangkok" });
      if (!unique.has(key) || capture.id === captureId) unique.set(key, capture);
    }
    return [...unique.values()];
  }, [captureId, captures]);

  const measurable = useMemo(
    () => activities.filter((item) => !item.is_summary && item.wbs.startsWith("1.2.")),
    [activities],
  );
  const selectedCapture = captures.find((item) => item.id === captureId) ?? captures[0] ?? null;
  const snapshotTime = selectedCapture ? time(selectedCapture.captured_at) : 0;

  const snapshot = useMemo(() => {
    const latest = new Map<string, HumanProgressEntry>();
    for (const entry of progress) {
      if (time(entry.observed_at) <= snapshotTime && !latest.has(entry.activity_id)) latest.set(entry.activity_id, entry);
    }
    return measurable.map((activity) => {
      const entry = latest.get(activity.id) ?? null;
      const actual = entry ? Number(entry.progress_percent) : null;
      const planned = plannedPercent(activity, snapshotTime);
      return { activity, entry, actual, planned, status: statusOf(actual, planned) };
    });
  }, [measurable, progress, snapshotTime]);

  const totals = useMemo(() => {
    const actualValues = snapshot.map((row) => row.actual ?? 0);
    return {
      actual: actualValues.length ? actualValues.reduce((sum, value) => sum + value, 0) / actualValues.length : 0,
      planned: snapshot.length ? snapshot.reduce((sum, row) => sum + row.planned, 0) / snapshot.length : 0,
      reviewed: snapshot.filter((row) => row.entry).length,
      complete: snapshot.filter((row) => row.status === "complete").length,
      behind: snapshot.filter((row) => (row.actual ?? 0) + 20 < row.planned).length,
    };
  }, [snapshot]);

  const matrix = useMemo(() => floorGroups.map((floorGroup) => {
    const floor = floors.find((item) => item.level_index === floorGroup.levelIndex) ?? null;
    const floorCaptures = captures.filter((item) => item.start_floor_id === floor?.id && time(item.captured_at) <= snapshotTime);
    const lastCapture = floorCaptures.sort((a, b) => time(b.captured_at) - time(a.captured_at))[0] ?? null;
    return {
    ...floorGroup,
    floor,
    lastCapture,
    cells: workGroups.map((work) => {
      const rows = snapshot.filter((row) => row.activity.wbs.startsWith(`${floorGroup.key}.`) && work.test(row.activity.name));
      const reviewed = rows.filter((row) => row.entry).length;
      const percent = rows.length ? rows.reduce((sum, row) => sum + (row.actual ?? 0), 0) / rows.length : null;
      const planned = rows.length ? rows.reduce((sum, row) => sum + row.planned, 0) / rows.length : 0;
      return { ...work, rows, reviewed, percent, status: rows.length ? statusOf(percent, planned) : null };
    }),
  }}).filter((floor) => floor.cells.some((cell) => cell.rows.length)), [captures, floors, snapshot, snapshotTime]);

  const projectCells = useMemo(() => workGroups.map((work) => {
    const rows = snapshot.filter((row) => work.test(row.activity.name));
    const reviewed = rows.filter((row) => row.entry).length;
    const percent = rows.length ? rows.reduce((sum, row) => sum + (row.actual ?? 0), 0) / rows.length : null;
    const planned = rows.length ? rows.reduce((sum, row) => sum + row.planned, 0) / rows.length : 0;
    return { ...work, rows, reviewed, percent, status: rows.length ? statusOf(percent, planned) : null };
  }), [snapshot]);

  const visibleRows = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("th-TH");
    return snapshot.filter((row) => {
      if (filter !== "all" && row.status !== filter) return false;
      if (!normalized) return true;
      const haystack = `${row.activity.wbs} ${row.activity.name}`.toLocaleLowerCase("th-TH");
      const terms = normalized.includes("/") ? normalized.split("/").map((term) => term.trim()).filter(Boolean) : [normalized];
      return terms.some((term) => haystack.includes(term));
    });
  }, [filter, query, snapshot]);

  const chart = useMemo(() => {
    const dateKeys = [...new Set([
      ...captures.map((item) => new Date(item.captured_at).toISOString().slice(0, 10)),
      ...progress.map((item) => new Date(item.observed_at).toISOString().slice(0, 10)),
    ])].sort();
    const points = dateKeys.map((key) => {
      const at = time(`${key}T23:59:59+07:00`);
      const latest = new Map<string, HumanProgressEntry>();
      for (const entry of progress) if (time(entry.observed_at) <= at && !latest.has(entry.activity_id)) latest.set(entry.activity_id, entry);
      const actual = measurable.length
        ? measurable.reduce((sum, item) => sum + Number(latest.get(item.id)?.progress_percent ?? 0), 0) / measurable.length
        : 0;
      const planned = measurable.length
        ? measurable.reduce((sum, item) => sum + plannedPercent(item, at), 0) / measurable.length
        : 0;
      return { key, actual, planned };
    });
    const width = 900;
    const height = 260;
    const x = (index: number) => points.length <= 1 ? 40 : 40 + (index / (points.length - 1)) * (width - 70);
    const y = (value: number) => 20 + ((100 - value) / 100) * (height - 55);
    return {
      points,
      width,
      height,
      actualLine: points.map((point, index) => `${x(index)},${y(point.actual)}`).join(" "),
      plannedLine: points.map((point, index) => `${x(index)},${y(point.planned)}`).join(" "),
      x,
      y,
    };
  }, [captures, measurable, progress]);

  function downloadCsv() {
    const header = ["WBS", "งานโครงสร้าง", "แผน (%)", "ผลจริง (%)", "สถานะ", "วันที่ตรวจ", "หมายเหตุ"];
    const lines = visibleRows.map((row) => [
      row.activity.wbs,
      row.activity.name,
      row.planned.toFixed(1),
      row.actual?.toFixed(1) ?? "ยังไม่ตรวจ",
      statusText[row.status],
      row.entry ? new Date(row.entry.observed_at).toLocaleString("th-TH") : "—",
      cleanNote(row.entry?.note ?? null),
    ]);
    const csv = `\uFEFF${[header, ...lines].map((line) => line.map(csvCell).join(",")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `structural-progress-${selectedCapture?.captured_at.slice(0, 10) ?? "report"}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!selectedCapture) return <div className="empty-state"><strong>ยังไม่มี Capture</strong><p>อัปโหลด Capture ก่อนเปิด Dashboard</p></div>;

  return <div className="track-dashboard">
    <div className="track-toolbar">
      <nav aria-label="มุมมอง Progress">
        <button className={tab === "overview" ? "is-active" : ""} onClick={() => setTab("overview")} type="button">ภาพรวม</button>
        <button className={tab === "details" ? "is-active" : ""} onClick={() => setTab("details")} type="button">รายละเอียดบนแผนงาน</button>
        <button className={tab === "productivity" ? "is-active" : ""} onClick={() => setTab("productivity")} type="button">Productivity</button>
      </nav>
      <div><label>Progress ณ วันที่<select onChange={(event) => setCaptureId(event.target.value)} value={selectedCapture.id}>{captureDates.map((item) => <option key={item.id} value={item.id}>{new Date(item.captured_at).toLocaleDateString("th-TH", { day: "2-digit", month: "long", year: "numeric" })}</option>)}</select></label><button className="button button-secondary" onClick={downloadCsv} type="button">ส่งออก CSV</button></div>
    </div>

    <section className="track-kpis">
      <article><span>ความก้าวหน้าจริง</span><strong>{totals.actual.toFixed(1)}%</strong><small>คนตรวจจากภาพ 360</small></article>
      <article><span>ตามแผนควรได้</span><strong>{totals.planned.toFixed(1)}%</strong><small className={totals.actual + 20 < totals.planned ? "is-danger" : ""}>ต่าง {(totals.actual - totals.planned).toFixed(1)} จุด</small></article>
      <article><span>ตรวจแล้ว</span><strong>{totals.reviewed}/{snapshot.length}</strong><small>{totals.complete} งานเสร็จสมบูรณ์</small></article>
      <article><span>ต้องติดตาม</span><strong>{totals.behind}</strong><small className={totals.behind ? "is-danger" : ""}>งานล่าช้ากว่าแผน</small></article>
    </section>

    {tab === "overview" && <section className="panel track-overview openspace-overview">
      <div className="openspace-breakdown"><span>แสดงผลตาม</span><div><button className={breakdown === "status" ? "is-active" : ""} onClick={() => setBreakdown("status")} type="button">สถานะ</button><button className={breakdown === "percent" ? "is-active" : ""} onClick={() => setBreakdown("percent")} type="button">% สำเร็จ</button><button className={breakdown === "quantity" ? "is-active" : ""} onClick={() => setBreakdown("quantity")} type="button">ปริมาณ</button></div><small>ผลล่าสุดถึง {formatDate(selectedCapture.captured_at)}</small></div>
      <div className="track-matrix-wrap"><table className="track-matrix openspace-matrix"><thead><tr><th>ชั้น / พื้นที่</th><th>Capture ล่าสุด</th><th>สถานะการตรวจ</th>{workGroups.map((work) => <th key={work.key}>{work.label}</th>)}</tr></thead><tbody>
        <tr className="project-total-row"><th>ทั้งโครงการ</th><td>{formatDate(selectedCapture.captured_at)}</td><td><span className="tracking-summary">เสร็จ {totals.complete}<br />กำลังทำ {snapshot.filter((row) => row.status === "in-progress").length}<br />ยังไม่เริ่ม {snapshot.filter((row) => row.status === "not-started").length}</span></td>{projectCells.map((cell) => <td key={cell.key}><ProgressMatrixCell breakdown={breakdown} cell={cell} onOpen={() => { setQuery(cell.label); setFilter("all"); setTab("details"); }} /></td>)}</tr>
        {matrix.map((floor) => <tr key={floor.key}><th>{floor.lastCapture ? <Link href={`/projects/${projectId}/captures/${floor.lastCapture.id}?mode=track&floorId=${floor.floor?.id ?? ""}`}>{floor.label}<small>เปิด Sheet View</small></Link> : floor.label}</th><td>{floor.lastCapture ? formatDate(floor.lastCapture.captured_at) : "—"}</td><td><span className={`track-status is-${statusOf(floor.cells.some((cell) => (cell.percent ?? 0) > 0) ? 1 : 0, 0)}`}>{floor.cells.every((cell) => !cell.rows.length || (cell.percent ?? 0) >= 100) ? "เสร็จแล้ว" : floor.cells.some((cell) => (cell.percent ?? 0) > 0) ? "กำลังทำ" : "ยังไม่เริ่ม"}</span></td>{floor.cells.map((cell) => <td key={cell.key}><ProgressMatrixCell breakdown={breakdown} cell={cell} onOpen={() => { setQuery(cell.label); setFilter("all"); setTab("details"); }} /></td>)}</tr>)}
      </tbody></table></div>
    </section>}

    {tab === "details" && <section className="panel track-details">
      <div className="panel-header"><div><h2>งานคงเหลือและหลักฐาน</h2><p>เลือก “ยังไม่เริ่ม” เพื่อดูงานที่ต้องปิด หรือเปิดภาพ 360 ที่ใช้ตรวจได้ทันที</p></div><span>{visibleRows.length} รายการ</span></div>
      <div className="track-detail-tools"><input aria-label="ค้นหางาน" onChange={(event) => setQuery(event.target.value)} placeholder="ค้นหา WBS หรืองาน" type="search" value={query} /><div>{(["all", "not-started", "in-progress", "complete", "behind"] as DetailFilter[]).map((value) => <button className={filter === value ? "is-active" : ""} key={value} onClick={() => setFilter(value)} type="button">{value === "all" ? "ทั้งหมด" : statusText[value]}</button>)}</div></div>
      <div className="table-scroll"><table className="data-table track-detail-table"><thead><tr><th>WBS / งาน</th><th>แผน</th><th>ผลจริง</th><th>สถานะ</th><th>หลักฐาน</th><th>หมายเหตุ</th></tr></thead><tbody>{visibleRows.map((row) => {
        const frameId = evidenceKeyframe(row.entry?.note ?? null);
        const evidenceCaptureId = row.entry?.capture_id;
        const href = evidenceCaptureId ? `/projects/${projectId}/captures/${evidenceCaptureId}${frameId ? `?keyframe=${frameId}` : ""}` : null;
        return <tr key={row.activity.id}><td><strong>{row.activity.wbs}</strong><span>{row.activity.name}</span></td><td>{row.planned.toFixed(0)}%</td><td><b>{row.actual === null ? "—" : `${row.actual.toFixed(0)}%`}</b></td><td><span className={`track-status is-${row.status}`}>{statusText[row.status]}</span></td><td>{href ? <Link className="track-evidence-link" href={href}>เปิดภาพ 360</Link> : "—"}</td><td>{cleanNote(row.entry?.note ?? null)}</td></tr>;
      })}</tbody></table></div>
    </section>}

    {tab === "productivity" && <section className="panel track-productivity">
      <div className="panel-header"><div><h2>Productivity งานโครงสร้าง</h2><p>เส้นทึบคือผลที่คนตรวจสะสม เส้นประคือแผนตามกำหนดเวลา</p></div><div className="track-chart-legend"><span className="is-actual">ผลจริง</span><span className="is-planned">แผน</span></div></div>
      {chart.points.length > 1 ? <div className="track-chart-scroll"><svg aria-label="กราฟความก้าวหน้าสะสม" className="track-chart" role="img" viewBox={`0 0 ${chart.width} ${chart.height}`}>
        {[0, 25, 50, 75, 100].map((value) => <g key={value}><line x1="40" x2={chart.width - 30} y1={chart.y(value)} y2={chart.y(value)} /><text x="4" y={chart.y(value) + 4}>{value}%</text></g>)}
        <polyline className="is-planned" points={chart.plannedLine} /><polyline className="is-actual" points={chart.actualLine} />
        {chart.points.map((point, index) => <g key={point.key}><circle className="is-actual" cx={chart.x(index)} cy={chart.y(point.actual)} r="4"><title>{formatDate(point.key)} ผลจริง {point.actual.toFixed(1)}%</title></circle>{(index === 0 || index === chart.points.length - 1 || index % Math.ceil(chart.points.length / 6) === 0) && <text className="date-label" textAnchor="middle" x={chart.x(index)} y={chart.height - 7}>{new Date(point.key).toLocaleDateString("th-TH", { day: "2-digit", month: "short" })}</text>}</g>)}
      </svg></div> : <div className="empty-state"><strong>ยังมีข้อมูลไม่พอสร้างกราฟ</strong><p>บันทึก Progress อย่างน้อยสองวันเพื่อดูอัตราการทำงาน</p></div>}
      <div className="track-productivity-summary"><div><span>ผลล่าสุด</span><strong>{totals.actual.toFixed(1)}%</strong></div><div><span>อัตราเฉลี่ยจากผลตรวจ</span><strong>{chart.points.length > 1 ? `${((chart.points.at(-1)!.actual - chart.points[0].actual) / Math.max(1, chart.points.length - 1)).toFixed(2)} จุด/วันที่มีข้อมูล` : "—"}</strong></div><div><span>แนวโน้ม</span><strong className={totals.actual >= totals.planned ? "is-good" : "is-danger"}>{totals.actual >= totals.planned ? "ตามแผนหรือเร็วกว่า" : "ช้ากว่าแผน"}</strong></div></div>
    </section>}
  </div>;
}
