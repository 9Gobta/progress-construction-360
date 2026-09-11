export type PlanToIfcTransform = {
  coefficientsX: [number, number, number];
  coefficientsY: [number, number, number];
};

export type PlanIfcPair = {
  plan: [number, number];
  ifc: [number, number];
};

function solveThreeByThree(matrix: number[][], values: number[]) {
  const rows = matrix.map((row, index) => [...row, values[index]]);
  for (let column = 0; column < 3; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < 3; row += 1) {
      if (Math.abs(rows[row][column]) > Math.abs(rows[pivot][column])) pivot = row;
    }
    if (Math.abs(rows[pivot][column]) < 1e-10) return null;
    [rows[column], rows[pivot]] = [rows[pivot], rows[column]];
    const divisor = rows[column][column];
    for (let item = column; item < 4; item += 1) rows[column][item] /= divisor;
    for (let row = 0; row < 3; row += 1) {
      if (row === column) continue;
      const factor = rows[row][column];
      for (let item = column; item < 4; item += 1) rows[row][item] -= factor * rows[column][item];
    }
  }
  return rows.map((row) => row[3]);
}

export function fitPlanToIfc(pairs: PlanIfcPair[]): PlanToIfcTransform | null {
  if (pairs.length < 3) return null;
  const normal = Array.from({ length: 3 }, () => [0, 0, 0]);
  const targetX = [0, 0, 0];
  const targetY = [0, 0, 0];
  for (const pair of pairs) {
    const row = [pair.plan[0], pair.plan[1], 1];
    for (let y = 0; y < 3; y += 1) {
      targetX[y] += row[y] * pair.ifc[0];
      targetY[y] += row[y] * pair.ifc[1];
      for (let x = 0; x < 3; x += 1) normal[y][x] += row[y] * row[x];
    }
  }
  const coefficientsX = solveThreeByThree(normal, targetX);
  const coefficientsY = solveThreeByThree(normal, targetY);
  if (!coefficientsX || !coefficientsY) return null;
  return {
    coefficientsX: coefficientsX as [number, number, number],
    coefficientsY: coefficientsY as [number, number, number],
  };
}

export function transformPlanPoint(transform: PlanToIfcTransform, x: number, y: number): [number, number] {
  return [
    transform.coefficientsX[0] * x + transform.coefficientsX[1] * y + transform.coefficientsX[2],
    transform.coefficientsY[0] * x + transform.coefficientsY[1] * y + transform.coefficientsY[2],
  ];
}

export function planDirectionInThree(
  transform: PlanToIfcTransform,
  headingDeg: number,
): [number, number, number] | null {
  const heading = headingDeg * Math.PI / 180;
  const planX = Math.cos(heading);
  const planY = Math.sin(heading);
  const ifcX = transform.coefficientsX[0] * planX + transform.coefficientsX[1] * planY;
  const ifcY = transform.coefficientsY[0] * planX + transform.coefficientsY[1] * planY;
  const length = Math.hypot(ifcX, ifcY);
  if (!Number.isFinite(length) || length < 1e-10) return null;
  // web-ifc streams Y-up viewer geometry; its horizontal Z is the inverse of
  // the original IFC Y axis used by this registration.
  return [ifcX / length, 0, -ifcY / length];
}

export function validatePlanToIfcOrientation(transform: PlanToIfcTransform) {
  const xAxis: [number, number] = [transform.coefficientsX[0], transform.coefficientsY[0]];
  const yAxis: [number, number] = [transform.coefficientsX[1], transform.coefficientsY[1]];
  const xLength = Math.hypot(...xAxis);
  const yLength = Math.hypot(...yAxis);
  const determinant = xAxis[0] * yAxis[1] - yAxis[0] * xAxis[1];
  const orthogonalityError = Math.abs(xAxis[0] * yAxis[0] + xAxis[1] * yAxis[1])
    / Math.max(xLength * yLength, 1e-10);
  const scaleRatio = Math.max(xLength, yLength) / Math.max(Math.min(xLength, yLength), 1e-10);
  return {
    determinant,
    orthogonalityError,
    scaleRatio,
    // Project floor plans and the reviewed IFC inventory share the same grid
    // handedness. A negative determinant is a mirrored registration and must
    // never be silently accepted as a low-error match.
    valid: Number.isFinite(determinant)
      && determinant > 1e-8
      && orthogonalityError <= 0.08
      && scaleRatio <= 6,
  };
}
