"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { CaptureDetail } from "@/lib/types";

type SpatialModel = {
  version: number;
  camera_height_m: number;
  point_count: number;
  positions: number[];
  colors: number[];
};

type Station = {
  id: string;
  index: number;
  timestampMs: number;
  x: number;
  y: number;
  z: number;
};

type Props = {
  projectId: string;
  captureId: string;
  detail: CaptureDetail;
  activeKeyframeId: string | null;
  onOpenStation: (keyframeId: string) => void;
};

function stationLabel(station: Station) {
  const seconds = station.timestampMs / 1000;
  return `จุด ${station.index + 1} · ${seconds.toFixed(1)} วินาที`;
}

export function SpatialTourInspector({
  projectId,
  captureId,
  detail,
  activeKeyframeId,
  onOpenStation,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [model, setModel] = useState<SpatialModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<Station | null>(null);
  const stations = useMemo<Station[]>(() => detail.keyframes
    .filter((frame) => frame.is_warp_point && frame.pose?.visual_x !== null && frame.pose?.visual_y !== null)
    .map((frame, index) => ({
      id: frame.id,
      index,
      timestampMs: frame.timestamp_ms,
      x: Number(frame.pose!.visual_x),
      y: Number(frame.pose!.relative_z_m ?? 0) - 1.65,
      z: Number(frame.pose!.visual_y),
    })), [detail.keyframes]);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/projects/${projectId}/captures/${captureId}/spatial-model`)
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail ?? "โหลดโมเดลสามมิติไม่สำเร็จ");
        }
        return response.json() as Promise<SpatialModel>;
      })
      .then((payload) => {
        if (!cancelled) {
          setError(null);
          setModel(payload);
        }
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "โหลดโมเดลสามมิติไม่สำเร็จ");
      });
    return () => { cancelled = true; };
  }, [captureId, projectId]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !model || !stations.length) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x101512);
    const camera = new THREE.PerspectiveCamera(48, 1, 0.02, 10000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.replaceChildren(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;

    const pointGeometry = new THREE.BufferGeometry();
    pointGeometry.setAttribute("position", new THREE.Float32BufferAttribute(model.positions, 3));
    const normalizedColors = Float32Array.from(model.colors, (value) => value / 255);
    pointGeometry.setAttribute("color", new THREE.Float32BufferAttribute(normalizedColors, 3));
    const points = new THREE.Points(
      pointGeometry,
      new THREE.PointsMaterial({ size: 0.075, vertexColors: true, sizeAttenuation: true }),
    );
    scene.add(points);

    const pathPositions: number[] = [];
    for (const station of stations) pathPositions.push(station.x, station.y + 1.65, station.z);
    const pathGeometry = new THREE.BufferGeometry();
    pathGeometry.setAttribute("position", new THREE.Float32BufferAttribute(pathPositions, 3));
    const path = new THREE.Line(
      pathGeometry,
      new THREE.LineBasicMaterial({ color: 0x42e7ae, transparent: true, opacity: 0.9 }),
    );
    scene.add(path);

    const ringGeometry = new THREE.RingGeometry(0.13, 0.23, 28);
    ringGeometry.rotateX(-Math.PI / 2);
    const rings = new THREE.InstancedMesh(
      ringGeometry,
      new THREE.MeshBasicMaterial({
        color: 0xffffff,
        side: THREE.DoubleSide,
        depthTest: false,
        transparent: true,
        opacity: 0.96,
      }),
      stations.length,
    );
    rings.renderOrder = 5;
    const hitGeometry = new THREE.CircleGeometry(0.34, 24);
    hitGeometry.rotateX(-Math.PI / 2);
    const hits = new THREE.InstancedMesh(
      hitGeometry,
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
      stations.length,
    );
    const matrix = new THREE.Matrix4();
    for (const [index, station] of stations.entries()) {
      matrix.makeTranslation(station.x, station.y + 0.025, station.z);
      rings.setMatrixAt(index, matrix);
      hits.setMatrixAt(index, matrix);
    }
    rings.instanceMatrix.needsUpdate = true;
    hits.instanceMatrix.needsUpdate = true;
    scene.add(rings, hits);
    const activeStation = stations.find((station) => station.id === activeKeyframeId);
    const activeRing = activeStation
      ? new THREE.Mesh(
        ringGeometry.clone(),
        new THREE.MeshBasicMaterial({
          color: 0xffd84d,
          side: THREE.DoubleSide,
          depthTest: false,
        }),
      )
      : null;
    if (activeRing && activeStation) {
      activeRing.position.set(activeStation.x, activeStation.y + 0.035, activeStation.z);
      activeRing.scale.setScalar(1.45);
      activeRing.renderOrder = 6;
      scene.add(activeRing);
    }

    // Frame the walked route rather than all sparse points. Distant SfM
    // landmarks are useful context but must not shrink the station rings.
    const bounds = new THREE.Box3();
    for (const station of stations) {
      bounds.expandByPoint(new THREE.Vector3(station.x, station.y, station.z));
      bounds.expandByPoint(new THREE.Vector3(station.x, station.y + 1.65, station.z));
    }
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z, 4);
    camera.position.set(center.x + radius * 0.68, center.y + radius * 0.62, center.z + radius * 0.68);
    controls.target.copy(center);
    controls.update();

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let down: { x: number; y: number } | null = null;
    const stationAt = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
        -((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(hits, false)[0];
      return hit?.instanceId === undefined ? null : stations[hit.instanceId] ?? null;
    };
    const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
    const pointerMove = (event: PointerEvent) => {
      const station = stationAt(event);
      setHovered(station);
      renderer.domElement.style.cursor = station ? "pointer" : "grab";
    };
    const pointerUp = (event: PointerEvent) => {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
      const station = stationAt(event);
      if (station) onOpenStation(station.id);
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointermove", pointerMove);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    const resize = () => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    let animation = 0;
    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      animation = requestAnimationFrame(animate);
    };
    animate();
    return () => {
      cancelAnimationFrame(animation);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointermove", pointerMove);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      controls.dispose();
      pointGeometry.dispose();
      (points.material as THREE.Material).dispose();
      pathGeometry.dispose();
      (path.material as THREE.Material).dispose();
      ringGeometry.dispose();
      (rings.material as THREE.Material).dispose();
      hitGeometry.dispose();
      (hits.material as THREE.Material).dispose();
      if (activeRing) {
        activeRing.geometry.dispose();
        (activeRing.material as THREE.Material).dispose();
      }
      renderer.dispose();
    };
  }, [activeKeyframeId, model, onOpenStation, stations]);

  return <section className="spatial-tour-inspector">
    <div className="spatial-tour-canvas" ref={containerRef} />
    <header><strong>3D จุดวาร์ป</strong><span>{stations.length} จุดวาร์ป · {model ? `${model.point_count.toLocaleString()} จุดสามมิติ` : "พิกัดเดียวกับ Virtual Tour"}</span></header>
    <aside><b>จุดสีเหลือง</b><span>ตำแหน่งภาพ 360 ปัจจุบัน</span><b>วงสีขาว</b><span>คลิกเพื่อเปิดภาพของจุดนั้น</span></aside>
    {hovered && <div className="spatial-station-tooltip">{stationLabel(hovered)}</div>}
    {!model && !error && <div className="spatial-model-message">กำลังตรวจสอบ Point Cloud…</div>}
    {error && <div className="spatial-model-message is-error">{error}</div>}
  </section>;
}
