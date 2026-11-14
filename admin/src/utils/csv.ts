type Cell = string | number | undefined | null;

/** Builds a CSV that opens cleanly in Excel and downloads it in the browser. */
export function downloadCsv(filename: string, header: string[], rows: Cell[][]) {
  const lines = [header, ...rows].map((r) => r.map(escapeCell).join(','));
  // BOM so Excel reads UTF-8 (₹, names); CRLF line endings for Windows Excel.
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function escapeCell(value: Cell) {
  let s = value === undefined || value === null ? '' : String(value);
  // Neutralise spreadsheet formulas from user-entered text (CSV injection).
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
