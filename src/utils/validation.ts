export const validators = {
  required: (v?: string) => (v?.trim() ? undefined : 'This field is required'),
  mobile: (v?: string) => (/^[6-9]\d{9}$/.test(v ?? '') ? undefined : 'Enter a valid 10-digit mobile number'),
  email: (v?: string) => (/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v ?? '') ? undefined : 'Enter a valid email address'),
  pan: (v?: string) => (/^[A-Z]{5}\d{4}[A-Z]$/.test(v ?? '') ? undefined : 'PAN format: ABCDE1234F'),
  gstin: (v?: string) =>
    /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(v ?? '') ? undefined : 'Enter a valid 15-character GSTIN',
  tel: (v?: string) => (/^\+?[\d\s()-]{6,20}$/.test(v ?? '') ? undefined : 'Enter a valid phone number'),
  number: (v?: string) => (/^-?\d+(\.\d+)?$/.test(v ?? '') ? undefined : 'Enter a number'),
  pin: (v?: string) => (/^\d{6}$/.test(v ?? '') ? undefined : 'Enter a 6-digit PIN code'),
  url: (v?: string) => (/^(https?:\/\/)?[\w-]+(\.[\w-]+)+\S*$/i.test(v ?? '') ? undefined : 'Enter a valid website'),
  date: (v?: string) => {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(v ?? '');
    if (!m) return 'Use DD/MM/YYYY';
    const d = new Date(+m[3]!, +m[2]! - 1, +m[1]!);
    return d.getDate() === +m[1]! && d.getMonth() === +m[2]! - 1 ? undefined : 'Enter a valid date';
  },
};

type Rule = (v?: string) => string | undefined;

/** Runs rules per field. Optional fields (no `required` rule) are only validated when filled. */
export function validate<T extends Record<string, any>>(values: T, schema: Partial<Record<keyof T, Rule[]>>) {
  const errors: Partial<Record<keyof T, string>> = {};
  for (const key in schema) {
    const rules = schema[key]!;
    const value = values[key] as string | undefined;
    const optional = !rules.includes(validators.required);
    if (optional && !value?.trim()) continue;
    for (const rule of rules) {
      const err = rule(value);
      if (err) {
        errors[key] = err;
        break;
      }
    }
  }
  return errors;
}

/** DD/MM/YYYY -> YYYY-MM-DD (Salesforce Date format). */
export function toSfDate(ddmmyyyy?: string) {
  if (!ddmmyyyy) return undefined;
  const [d, m, y] = ddmmyyyy.split('/');
  return `${y}-${m}-${d}`;
}
