import { useState } from 'react';
import { formatNumber } from '@/utils/format';

// Single-series charts in the brand primary; identity comes from the axis labels, so no legend.
// Values live in tooltips and the tables beside each chart.

interface Column {
  key: string;
  label: string;
  value: number;
  /** Extra lines shown in the tooltip under the value. */
  details?: string[];
}

/** Vertical bars over time with a recessive grid and a hover/focus tooltip per bar. */
export function ColumnChart({ data, unit, ariaLabel }: { data: Column[]; unit: string; ariaLabel: string }) {
  const [active, setActive] = useState<string>();
  const max = niceMax(Math.max(1, ...data.map((d) => d.value)));
  const ticks = [max, max / 2];
  // Label every other column; styles.css thins this further on narrow screens.
  const every = data.length > 7 ? 2 : 1;

  return (
    <figure style={{ margin: 0 }} aria-label={ariaLabel}>
      <div className="chart-plot">
        <div className="chart-cols">
          {ticks.map((t) => (
            <div key={t} className="grid-line" style={{ bottom: `${(t / max) * 100}%` }}>
              <span>{formatNumber(t)}</span>
            </div>
          ))}
          {data.map((d) => (
            <div
              key={d.key}
              className="chart-col"
              tabIndex={0}
              aria-label={`${d.label}: ${d.value} ${unit}`}
              onMouseEnter={() => setActive(d.key)}
              onMouseLeave={() => setActive(undefined)}
              onFocus={() => setActive(d.key)}
              onBlur={() => setActive(undefined)}
            >
              <div className="bar" style={{ height: `${(d.value / max) * 100}%` }} />
              {active === d.key ? (
                <div className="tooltip" role="tooltip">
                  <strong>{d.label}</strong>
                  {formatNumber(d.value)} {unit}
                  {d.details?.map((line) => <div key={line}>{line}</div>)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <div className="chart-x" aria-hidden>
          {data.map((d, i) => (
            <span key={d.key} className={i % every === 0 ? 'labelled' : undefined}>
              {i % every === 0 ? d.label : ''}
            </span>
          ))}
        </div>
      </div>
    </figure>
  );
}

interface Row {
  key: string;
  label: string;
  value: number;
  details?: string[];
}

/** Horizontal bars for comparing categories, value labelled at the end of each row. */
export function BarList({ data, unit }: { data: Row[]; unit: string }) {
  const [active, setActive] = useState<string>();
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="hbars">
      {data.map((d) => (
        <div
          key={d.key}
          className="hbar"
          tabIndex={0}
          onMouseEnter={() => setActive(d.key)}
          onMouseLeave={() => setActive(undefined)}
          onFocus={() => setActive(d.key)}
          onBlur={() => setActive(undefined)}
        >
          <span className="name" title={d.label}>
            {d.label}
          </span>
          <div className="track">
            <div className="fill" style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
          <span className="val">{formatNumber(d.value)}</span>
          {active === d.key && d.details?.length ? (
            <div className="tooltip" role="tooltip">
              <strong>
                {d.label}: {formatNumber(d.value)} {unit}
              </strong>
              {d.details.map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/** Rounds an axis maximum up to 1, 2 or 5 × a power of ten so gridlines land on round numbers. */
function niceMax(v: number) {
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return Math.max(2, step * pow);
}
