"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { Capture, CaptureDetail, FieldNote, ProgressComparison, Project } from "@/lib/types";

const NOTE_STATUS_LABELS: Record<FieldNote["status"], string> = {
  OPEN: "เปิดอยู่",
  P1: "ด่วนมาก P1",
  P2: "เร่งด่วน P2",
  P3: "ติดตาม P3",
  COMPLETED: "ดำเนินการแล้ว",
  VERIFIED: "ตรวจยืนยันแล้ว",
};

function formatDate(value: string, includeTime = false) {
  return new Intl.DateTimeFormat("th-TH", includeTime
    ? { dateStyle: "long", timeStyle: "short", timeZone: "Asia/Bangkok" }
    : { dateStyle: "long", timeZone: "Asia/Bangkok" }).format(new Date(value));
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function percent(value: number | null) {
  return value === null ? "ยังไม่มีข้อมูล" : `${value.toFixed(1)}%`;
}

export function DailyReportWorkspace({
  project,
  captures,
  detail,
  notes,
  comparison,
  previousComparison,
}: {
  project: Project;
  captures: Capture[];
  detail: CaptureDetail;
  notes: FieldNote[];
  comparison: ProgressComparison | null;
  previousComparison: ProgressComparison | null;
}) {
  const router = useRouter();
  const capture = detail.capture;
  const ordered = [...captures].sort((a, b) => b.captured_at.localeCompare(a.captured_at));
  const activeIndex = ordered.findIndex((item) => item.id === capture.id);
  const previous = ordered[activeIndex + 1] ?? null;
  const next = activeIndex > 0 ? ordered[activeIndex - 1] : null;
  const locatedFrames = detail.keyframes.filter((item) => item.pose);
  const reviewedFrames = locatedFrames.filter((item) => item.pose && !item.pose.needs_review);
  const floorCount = new Set(locatedFrames.map((item) => item.pose?.floor_id).filter(Boolean)).size;
  const coverage = detail.keyframes.length ? (locatedFrames.length / detail.keyframes.length) * 100 : 0;
  const currentActual = comparison
    ? average(comparison.items.map((item) => item.human_actual_percent).filter((value): value is string => value !== null).map(Number))
    : null;
  const currentPlanned = comparison ? average(comparison.items.map((item) => Number(item.planned_percent))) : null;
  const previousByActivity = new Map(previousComparison?.items.map((item) => [item.activity_id, item]) ?? []);
  const dailyChanges = comparison?.items.flatMap((item) => {
    const current = item.human_actual_percent;
    const prior = previousByActivity.get(item.activity_id)?.human_actual_percent;
    return current !== null && prior !== null && prior !== undefined ? [Number(current) - Number(prior)] : [];
  }) ?? [];
  const dailyGain = average(dailyChanges);
  const openNotes = notes.filter((note) => !["COMPLETED", "VERIFIED"].includes(note.status));
  const completedNotes = notes.filter((note) => ["COMPLETED", "VERIFIED"].includes(note.status));
  const evidenceFrames = detail.keyframes.length
    ? [0, Math.floor((detail.keyframes.length - 1) / 3), Math.floor(((detail.keyframes.length - 1) * 2) / 3), detail.keyframes.length - 1]
      .map((index) => detail.keyframes[index])
      .filter((frame, index, items) => frame && items.findIndex((item) => item.id === frame.id) === index)
    : [];
  const duration = detail.metadata ? Math.round(detail.metadata.duration_ms / 1000) : null;

  function selectCapture(captureId: string) {
    router.push(`/projects/${project.id}/reports/daily?captureId=${encodeURIComponent(captureId)}`);
  }

  return <section className="daily-report-page">
    <header className="daily-report-toolbar">
      <div>
        <p className="eyebrow">DAILY SITE REPORT · 360° EVIDENCE</p>
        <h1>รายงานประจำวัน</h1>
        <p>รวบรวมหลักฐานภาพ 360 ความก้าวหน้า และประเด็นหน้างานตามวันที่ Capture</p>
      </div>
      <div className="daily-report-actions">
        <div className="daily-report-date-picker">
          <button disabled={!previous} onClick={() => previous && selectCapture(previous.id)} title="วันก่อนหน้า" type="button">←</button>
          <select aria-label="เลือกวันที่รายงาน" onChange={(event) => selectCapture(event.target.value)} value={capture.id}>
            {ordered.map((item) => <option key={item.id} value={item.id}>{formatDate(item.captured_at, true)}</option>)}
          </select>
          <button disabled={!next} onClick={() => next && selectCapture(next.id)} title="วันถัดไป" type="button">→</button>
        </div>
        <button className="button button-primary" onClick={() => window.print()} type="button">พิมพ์ / บันทึก PDF</button>
      </div>
    </header>

    <article className="daily-report-sheet">
      <header className="daily-report-cover">
        <div><span>PROGRESS CONSTRUCTION 360</span><h2>รายงานความก้าวหน้าประจำวัน</h2><p>{project.name}</p></div>
        <dl><div><dt>วันที่สำรวจ</dt><dd>{formatDate(capture.captured_at, true)}</dd></div><div><dt>สถานที่</dt><dd>{project.location || "ไม่ระบุ"}</dd></div><div><dt>ผู้บันทึก</dt><dd>{capture.captured_by_text || "ไม่ระบุ"}</dd></div><div><dt>สถานะประมวลผล</dt><dd>{capture.status}</dd></div></dl>
      </header>

      <section className="daily-report-metrics" aria-label="สรุปรายงาน">
        <div><span>ความก้าวหน้าเฉลี่ย</span><strong>{percent(currentActual)}</strong><small>แผน {percent(currentPlanned)}</small></div>
        <div><span>เปลี่ยนจากครั้งก่อน</span><strong className={dailyGain !== null && dailyGain < 0 ? "is-negative" : ""}>{dailyGain === null ? "—" : `${dailyGain >= 0 ? "+" : ""}${dailyGain.toFixed(1)} จุด`}</strong><small>{previous ? `เทียบ ${formatDate(previous.captured_at)}` : "Capture แรก"}</small></div>
        <div><span>ความครอบคลุมภาพ</span><strong>{coverage.toFixed(1)}%</strong><small>{locatedFrames.length}/{detail.keyframes.length} จุดมีตำแหน่ง</small></div>
        <div><span>ประเด็นหน้างาน</span><strong>{notes.length}</strong><small>เปิดอยู่ {openNotes.length} · ปิดแล้ว {completedNotes.length}</small></div>
      </section>

      <section className="daily-report-section">
        <header><div><span>01</span><div><h3>ข้อมูลการสำรวจ</h3><p>ข้อมูลจาก Capture และกระบวนการระบุตำแหน่งจริงของระบบ</p></div></div><Link href={`/projects/${project.id}/captures/${capture.id}`}>เปิด Virtual Tour →</Link></header>
        <div className="daily-report-facts">
          <div><span>ภาพหลักฐานทั้งหมด</span><b>{detail.keyframes.length} จุด</b></div>
          <div><span>ยืนยันตำแหน่งแล้ว</span><b>{reviewedFrames.length} จุด</b></div>
          <div><span>จำนวนชั้นที่พบ</span><b>{floorCount} ชั้น</b></div>
          <div><span>ระยะเวลาวิดีโอ</span><b>{duration === null ? "—" : `${duration} วินาที`}</b></div>
          <div><span>ความละเอียด</span><b>{detail.metadata ? `${detail.metadata.width_px} × ${detail.metadata.height_px}` : "—"}</b></div>
          <div><span>หมายเหตุ Capture</span><b>{capture.notes || "ไม่มีหมายเหตุ"}</b></div>
        </div>
      </section>

      <section className="daily-report-section">
        <header><div><span>02</span><div><h3>ภาพหลักฐานประจำวัน</h3><p>ตัวอย่างภาพกระจายตามช่วงเวลาของเส้นทางสำรวจ</p></div></div></header>
        {evidenceFrames.length ? <div className="daily-report-gallery">{evidenceFrames.map((frame) => <Link href={`/projects/${project.id}/captures/${capture.id}?keyframe=${frame.id}`} key={frame.id}><div><Image alt={`ภาพหลักฐานวินาที ${Math.round(frame.timestamp_ms / 1000)}`} fill sizes="320px" src={frame.image_url} unoptimized /></div><span>วินาที {Math.round(frame.timestamp_ms / 1000)} · {frame.pose ? "มีตำแหน่งบนแปลน" : "รอตรวจตำแหน่ง"}</span></Link>)}</div> : <p className="daily-report-empty">Capture นี้ยังไม่มีภาพหลักฐาน</p>}
      </section>

      <section className="daily-report-section">
        <header><div><span>03</span><div><h3>ความก้าวหน้าเทียบแผน</h3><p>{comparison?.schedule_name || "ยังไม่มีแผนงานที่พร้อมใช้"}</p></div></div><Link href={`/projects/${project.id}/dashboard?captureId=${capture.id}`}>เปิด Dashboard →</Link></header>
        {comparison ? <div className="daily-report-progress-table" role="table">
          <div className="is-heading" role="row"><span>กิจกรรม</span><span>แผน</span><span>ผลงานจริง</span><span>ต่างจากแผน</span></div>
          {comparison.items.filter((item) => item.human_actual_percent !== null || Number(item.planned_percent) > 0).slice(0, 12).map((item) => <div key={item.activity_id} role="row"><span><b>{item.wbs}</b>{item.name}</span><span>{Number(item.planned_percent).toFixed(1)}%</span><span>{item.human_actual_percent === null ? "ยังไม่ตรวจ" : `${Number(item.human_actual_percent).toFixed(1)}%`}</span><span className={item.variance_pp !== null && Number(item.variance_pp) < 0 ? "is-negative" : ""}>{item.variance_pp === null ? "—" : `${Number(item.variance_pp) >= 0 ? "+" : ""}${Number(item.variance_pp).toFixed(1)}`}</span></div>)}
        </div> : <p className="daily-report-empty">นำเข้าแผนงานและบันทึก Progress เพื่อให้ระบบสรุปส่วนนี้อัตโนมัติ</p>}
      </section>

      <section className="daily-report-section">
        <header><div><span>04</span><div><h3>ประเด็นหน้างาน</h3><p>รายการที่สร้างจากหลักฐานของ Capture วันนี้</p></div></div><Link href={`/projects/${project.id}/field-notes`}>ดูประเด็นทั้งหมด →</Link></header>
        {notes.length ? <div className="daily-report-notes">{notes.map((note) => <article key={note.id}><div className="daily-report-note-image"><Image alt={note.title} fill sizes="180px" src={note.image_url} unoptimized /></div><div><span className={`field-note-status status-${note.status.toLowerCase()}`}>{NOTE_STATUS_LABELS[note.status]}</span><h4>{note.title}</h4><p>{note.description || "ไม่มีรายละเอียด"}</p><small>{note.floor_name} · ผู้รับผิดชอบ: {note.assignee_name || "ยังไม่มอบหมาย"}{note.due_date ? ` · กำหนด ${formatDate(note.due_date)}` : ""}</small></div></article>)}</div> : <p className="daily-report-empty">วันนี้ยังไม่มีประเด็นหน้างานที่บันทึกไว้</p>}
      </section>

      <footer className="daily-report-footer"><span>สร้างจากข้อมูลใน Progress Construction 360</span><span>สร้างเมื่อ {formatDate(new Date().toISOString(), true)}</span></footer>
    </article>
  </section>;
}
