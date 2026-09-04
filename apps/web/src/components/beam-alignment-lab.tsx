"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import styles from "./beam-alignment-lab.module.css";

const methods = [
  {
    id: "01_raw_ifc",
    name: "1. IFC ตรง",
    count: 62,
    status: "ไม่ควรใช้จริง",
    description: "ฉายพิกัด IFC ด้วย Affine เดิม เห็นคานผีเหนือ Grid A และแนวระเบียงที่ไม่ตรงแบบ",
  },
  {
    id: "02_legacy_snap",
    name: "2. Grid Snap เดิม",
    count: 62,
    status: "ไม่ควรใช้จริง",
    description: "ระยะช่วง Grid ดูถูกขึ้น แต่คานผิดตัวยังคงถูกยืดไปยังตำแหน่งที่ไม่มีคาน",
  },
  {
    id: "03_raster_hough",
    name: "3. ตรวจเส้นจาก PNG",
    count: 64,
    status: "ใช้เสนอเส้นเท่านั้น",
    description: "ใช้ได้เมื่อมีแค่ภาพ แต่เก็บ Grid เส้นบอกระยะ และเส้นประกอบปนมาด้วย",
  },
  {
    id: "04_vector_pdf",
    name: "4. อ่าน Vector PDF",
    count: 64,
    status: "ฐานข้อมูลอัตโนมัติที่ดี",
    description: "ตำแหน่งเส้นมาจาก PDF จริง แต่ยังต้องรวมเส้นคู่และจำแนกคานออกจากเส้นรูปทรงอื่น",
  },
  {
    id: "05_reviewed_grid",
    name: "5. Grid ที่ตรวจทาน",
    count: 10,
    status: "แม่นสำหรับคานหลัก",
    description: "คานหลักอยู่ตรงแนวจริง แต่ยังไม่รวมคานย่อย ทางลาด และระเบียงทั้งหมด",
  },
  {
    id: "06_hybrid",
    name: "6. Hybrid Consensus",
    count: 10,
    status: "แนะนำให้พัฒนาต่อ",
    description: "รับเส้นเมื่อ PDF, ภาพ, Grid และผู้ตรวจสนับสนุนร่วมกัน เส้นไม่มั่นใจจะไม่ถูกนับ Progress",
  },
  {
    id: "07_cad_layers",
    name: "7. AutoCAD Layers",
    count: 53,
    status: "เลือกทีละช่วง",
    description: "คานที่ตรวจพบทุกช่วงคลิกได้ ช่วงที่จับคู่ป้าย B/CB ได้จะแสดงสีเขียว ส่วนช่วงรอตรวจป้ายจะแสดงสีส้ม",
  },
] as const;

type CadBeam = {
  id: string;
  beam_type: string | null;
  plan_start: [number, number];
  plan_end: [number, number];
  length_m: number;
  confidence: number;
};

type CadFloor = {
  count: number;
  labeled: number;
  accepted: number;
  total_length_m: number;
  beams: CadBeam[];
};

type CadInventory = {
  floors: Record<string, CadFloor>;
};

function CadBeamPicker() {
  const [inventory, setInventory] = useState<CadInventory | null>(null);
  const [floor, setFloor] = useState("1");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/beam-alignment-methods/cad_beam_inventory.json")
      .then((response) => response.json() as Promise<CadInventory>)
      .then(setInventory)
      .catch(() => setInventory(null));
  }, []);

  const beams = useMemo(
    () => inventory?.floors[floor]?.beams ?? [],
    [floor, inventory],
  );

  const selected = beams.find((beam) => beam.id === selectedId) ?? beams[0] ?? null;
  const confirmedCount = beams.filter((beam) => beam.confidence >= 0.95 && beam.beam_type).length;

  return (
    <div className={styles.cadPicker}>
      <div className={styles.cadControls}>
        <label>
          ชั้น
          <select onChange={(event) => setFloor(event.target.value)} value={floor}>
            {["1", "2", "3", "4"].map((level) => <option key={level} value={level}>ชั้น {level}</option>)}
          </select>
        </label>
        <label>
          คานที่ตรวจ
          <select onChange={(event) => setSelectedId(event.target.value)} value={selected?.id ?? ""}>
            {beams.map((beam, index) => (
              <option key={beam.id} value={beam.id}>
                {beam.beam_type ?? "รอตรวจป้าย"} · ช่วง {index + 1} · {beam.length_m.toFixed(3)} ม.
              </option>
            ))}
          </select>
        </label>
        <div className={styles.cadSelectionSummary}>
          <strong>{selected ? `${selected.beam_type ?? "รอตรวจป้าย"} · ${selected.length_m.toFixed(3)} ม.` : "ไม่พบช่วงคาน"}</strong>
          <span>คลิกได้ {beams.length} ช่วง · ยืนยันป้ายแล้ว {confirmedCount} · รอตรวจ {beams.length - confirmedCount}</span>
        </div>
      </div>
      <div className={styles.cadInteractivePlan}>
        <Image
          alt={`แบบโครงสร้างชั้น ${floor}`}
          fill
          priority
          sizes="(max-width: 1100px) 100vw, 75vw"
          src={`/beam-alignment-methods/floor_${floor}_plan.png`}
        />
        <svg aria-label={`เลือกคานชั้น ${floor}`} preserveAspectRatio="none" viewBox="0 0 1 1">
          {beams.map((beam) => (
            <line
              className={styles.cadHitTarget}
              key={`${beam.id}-hit`}
              onClick={() => setSelectedId(beam.id)}
              x1={beam.plan_start[0]}
              x2={beam.plan_end[0]}
              y1={beam.plan_start[1]}
              y2={beam.plan_end[1]}
            />
          ))}
          {selected ? (
            <>
              <line
                className={styles.cadSelectedHalo}
                x1={selected.plan_start[0]}
                x2={selected.plan_end[0]}
                y1={selected.plan_start[1]}
                y2={selected.plan_end[1]}
              />
              <line
                className={selected.confidence >= 0.95 && selected.beam_type ? styles.cadSelectedBeam : styles.cadReviewBeam}
                x1={selected.plan_start[0]}
                x2={selected.plan_end[0]}
                y1={selected.plan_start[1]}
                y2={selected.plan_end[1]}
              />
              <circle className={styles.cadEndpoint} cx={selected.plan_start[0]} cy={selected.plan_start[1]} r="0.004" />
              <circle className={styles.cadEndpoint} cx={selected.plan_end[0]} cy={selected.plan_end[1]} r="0.004" />
            </>
          ) : null}
        </svg>
      </div>
    </div>
  );
}

export function BeamAlignmentLab() {
  const [activeId, setActiveId] = useState<(typeof methods)[number]["id"]>("07_cad_layers");
  const active = methods.find((method) => method.id === activeId) ?? methods[6];

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Beam-to-plan experiment · ST-03 · ชั้น 1</p>
          <h1>เปรียบเทียบทุกวิธีจับคานกับแบบ</h1>
          <p>ผลทั้งหมดเป็นข้อเสนอทดลองและยังไม่บันทึกเป็น Progress จริง กดแต่ละวิธีเพื่อเทียบตำแหน่งบนแบบเดียวกัน</p>
        </div>
        <Link className={styles.back} href="/">กลับหน้าหลัก</Link>
      </header>

      <section aria-label="เลือกวิธีจับคาน" className={styles.tabs}>
        {methods.map((method) => (
          <button
            className={method.id === activeId ? styles.activeTab : styles.tab}
            key={method.id}
            onClick={() => setActiveId(method.id)}
            type="button"
          >
            <span>{method.name}</span>
            <small>{method.count} เส้น</small>
          </button>
        ))}
      </section>

      <section className={styles.viewer}>
        <div className={styles.canvas}>
          {active.id === "07_cad_layers" ? <CadBeamPicker /> : (
            <Image
              alt={`ผลการจับคานด้วยวิธี ${active.name}`}
              height={842}
              key={active.id}
              priority
              src={`/beam-alignment-methods/${active.id}.png`}
              width={1211}
            />
          )}
        </div>
        <aside className={styles.summary}>
          <span className={styles.status}>{active.status}</span>
          <h2>{active.name}</h2>
          <p>{active.description}</p>
          <dl>
            <div><dt>เส้นที่เสนอ</dt><dd>{active.count}</dd></div>
            <div><dt>แหล่งข้อมูล</dt><dd>{active.id === "07_cad_layers" ? "DWG: Layer + Text" : active.id === "04_vector_pdf" ? "PDF ต้นฉบับ" : active.id === "03_raster_hough" ? "ภาพ Raster" : active.id === "06_hybrid" ? "หลายหลักฐาน" : "IFC / Grid"}</dd></div>
          </dl>
          <p className={styles.warning}>เส้นที่อยู่นอกพื้นที่คานหรือไม่มีหลักฐานรองรับต้องถูกปฏิเสธ ไม่ใช่ยืดเข้าหา Grid อัตโนมัติ</p>
        </aside>
      </section>

      <section className={styles.notes}>
        <h2>สิ่งที่เห็นจากการทดลอง</h2>
        <ul>
          <li>วิธี 1–2 แสดงชัดว่าพิกัด IFC เดิมไม่ใช่หลักฐานเพียงพอสำหรับวางคานบนแบบ 2D</li>
          <li>วิธี 3 ตรวจจาก PNG ได้ แต่แยกคานออกจาก Grid และเส้นบอกระยะไม่ได้ทั้งหมด</li>
          <li>วิธี 4 รักษาตำแหน่งเส้นจาก PDF ได้ดีที่สุดในกลุ่มอัตโนมัติ แต่ต้องรวมเส้นคู่เป็นวัตถุคาน</li>
          <li>วิธี 5–6 ยังแสดงเฉพาะคานหลัก เพื่อไม่สร้างคานย่อยที่ระบบยังพิสูจน์ไม่ได้</li>
          <li>วิธี 7 รับเฉพาะคานที่มีเส้นคู่บน S-BEAM และป้าย B/CB ที่จับคู่ได้หนึ่งต่อหนึ่ง แล้วไฮไลต์ทีละช่วง</li>
        </ul>
      </section>

    </main>
  );
}
