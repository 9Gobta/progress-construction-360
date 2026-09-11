"use client";

import { useRef, useState, type PointerEvent } from "react";

export function FieldNoteMarkup({ paths: initialPaths, canEdit, onSave }: {
  paths: Array<Array<[number, number]>>;
  canEdit: boolean;
  onSave: (paths: Array<Array<[number, number]>>) => void;
}) {
  const [paths, setPaths] = useState(initialPaths);
  const pathsRef = useRef(initialPaths);
  const [drawing, setDrawing] = useState(false);
  const [active, setActive] = useState(false);
  function updatePaths(updater: (current: Array<Array<[number, number]>>) => Array<Array<[number, number]>>) {
    const next = updater(pathsRef.current);
    pathsRef.current = next;
    setPaths(next);
  }
  function point(event: PointerEvent<SVGSVGElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1000, (event.clientX - rect.left) / rect.width * 1000)), Math.max(0, Math.min(1000, (event.clientY - rect.top) / rect.height * 1000))];
  }
  function start(event: PointerEvent<SVGSVGElement>) {
    if (!active) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawing(true); updatePaths((current) => [...current, [point(event)]]);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    if (!drawing || !active) return;
    const next = point(event);
    updatePaths((current) => current.map((path, index) => index === current.length - 1 ? [...path, next] : path));
  }
  function finish() {
    if (!drawing) return;
    setDrawing(false); onSave(pathsRef.current);
  }
  function clear() { pathsRef.current = []; setPaths([]); onSave([]); }
  return <div className={`field-note-markup ${active ? "is-active" : ""}`}><svg onPointerCancel={finish} onPointerDown={start} onPointerMove={move} onPointerUp={finish} preserveAspectRatio="none" viewBox="0 0 1000 1000">{paths.map((path, index) => <polyline fill="none" key={index} points={path.map(([x, y]) => `${x},${y}`).join(" ")} stroke="#ef3d32" strokeLinecap="round" strokeLinejoin="round" strokeWidth="9" vectorEffect="non-scaling-stroke" />)}</svg>{canEdit && <div><button className={active ? "is-active" : ""} onClick={() => setActive((value) => !value)} type="button">✎ {active ? "กำลังวาด" : "ทำเครื่องหมาย"}</button>{paths.length > 0 && <button onClick={clear} type="button">ล้างเส้น</button>}</div>}</div>;
}
