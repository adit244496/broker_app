import { settingsApi } from '@/api/services';
import { useAsync } from '@/hooks/useAsync';
import type { AccountField, AccountForm, Broker } from '@/types';

// One fetch for every card on a page; Settings clears it when the form is saved.
let cached: Promise<AccountForm> | undefined;
export const forgetAccountForm = () => {
  cached = undefined;
};

/**
 * A broker's account details, listed the way Settings -> Account form defines them (labels, order,
 * sections).
 */
export function AccountDetails({ broker, extra = [] }: { broker: Broker; extra?: [string, string | undefined][] }) {
  const form = useAsync(() => {
    cached ??= settingsApi.getAccountForm().catch((e) => {
      cached = undefined;
      throw e;
    });
    return cached;
  });
  const fields = form.data?.fields.filter((f) => f.enabled);
  const rows = fields ? detailRows(fields, broker.raw) : fallbackRows(broker);
  return (
    <dl className="details">
      {[...rows, ...extra].map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value || '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

const text = (v: unknown) => (v === null || v === undefined || v === '' ? undefined : String(v));

function detailRows(fields: AccountField[], raw: Record<string, unknown>): [string, string | undefined][] {
  return fields.map((f) => [f.label, text(raw[f.sfField])]);
}

/** Until the form has loaded. */
function fallbackRows(b: Broker): [string, string | undefined][] {
  return [
    ['Mobile', `${b.countryCode ?? ''} ${b.cpMobile}`.trim()],
    ['Email', b.cpEmail],
    ['RERA No', b.reraNo],
    ['PAN', b.pan],
    ['GSTIN', b.gstin],
    ['Address', b.cpAddress],
  ];
}
