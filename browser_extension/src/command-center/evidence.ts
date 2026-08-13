import type {
  ActionEvent,
  CapturedEvent,
  DomMutationSummaryEvent,
  ElementRef,
  NavigationEvent,
  NetworkRequestEvent,
  NetworkResponseEvent,
  RedactedValue,
} from '@/shared/types';

export type CommandCenterPageDescriptor = {
  origin: string;
  path: string;
  query_parameter_names: string[];
  fingerprint: string;
};

export type CommandCenterBrowserEvent = {
  system_code?: string;
  tab_id?: number;
  event_id: string;
  client_sequence: number;
  occurred_at: string;
  event_type: 'click' | 'input' | 'select' | 'submit' | 'navigation';
  page: CommandCenterPageDescriptor;
  control?: {
    role?: string;
    accessible_name?: string;
    input_type?: string;
    selector_fingerprint: string;
  };
  value_fingerprint?: string;
};

export type CommandCenterNetworkExchange = {
  system_code?: string;
  tab_id?: number;
  exchange_id: string;
  client_sequence: number;
  started_at: string;
  completed_at: string;
  method: string;
  path_template: string;
  query_parameter_names: string[];
  query_parameter_fingerprints: Record<string, string[]>;
  body_field_fingerprints?: Record<string, string[]>;
  request_fingerprint?: string;
  response_status: number;
  response_fingerprint?: string;
  endpoint_fingerprint: string;
};

export type CommandCenterPageMutation = {
  system_code?: string;
  tab_id?: number;
  mutation_id: string;
  client_sequence: number;
  occurred_at: string;
  page: CommandCenterPageDescriptor;
  mutation_type: 'navigation' | 'route_change' | 'dom_change' | 'form_state_change';
  changed_control_fingerprints: string[];
};

export type CommandCenterEvidenceBatch = {
  batch_id: string;
  recording_id: string;
  events: Array<CommandCenterBrowserEvent | CommandCenterNetworkExchange>;
  page_mutations: CommandCenterPageMutation[];
  redaction_summary: {
    redacted_field_count: number;
    fingerprinted_value_count: number;
    dropped_evidence_count: number;
  };
};

export type EvidenceConverter = {
  append(event: CapturedEvent): void;
  flush(recordingId: string): Promise<CommandCenterEvidenceBatch | null>;
};

type PendingRequest = {
  event: NetworkRequestEvent;
  sequence: number;
};

type BufferedEvidence =
  | { kind: 'action'; event: ActionEvent; sequence: number }
  | { kind: 'navigation'; event: NavigationEvent; sequence: number }
  | { kind: 'mutation'; event: DomMutationSummaryEvent; sequence: number }
  | {
      kind: 'exchange';
      request: NetworkRequestEvent;
      response: NetworkResponseEvent;
      sequence: number;
    };

const ACTION_MAP = new Map<ActionEvent['action_type'], CommandCenterBrowserEvent['event_type']>([
  ['click', 'click'],
  ['dblclick', 'click'],
  ['input', 'input'],
  ['change', 'select'],
  ['submit', 'submit'],
]);
const IDENTIFIER = /^[A-Za-z][A-Za-z0-9_.-]*$/;
const METHOD = /^[A-Z]{3,10}$/;
const SENSITIVE_TEXT = /authorization|cookie|credential|token|api\s*key|password|captcha|local.?storage|file.?content/i;

export function createEvidenceConverter(options: {
  allowedOrigins: string[];
  originSystemCodes?: Record<string, string>;
  fingerprintKey: string;
  maxBufferedEvents?: number;
}): EvidenceConverter {
  const allowedOrigins = new Set(options.allowedOrigins.map(exactOrigin).filter(isString));
  const maxBufferedEvents = options.maxBufferedEvents ?? 2_000;
  const pendingRequests = new Map<string, PendingRequest>();
  let buffered: BufferedEvidence[] = [];
  let nextSequence = 1;
  let droppedEvidenceCount = 0;

  function reserveSequence(): number {
    const sequence = nextSequence;
    nextSequence += 1;
    return sequence;
  }

  function add(item: BufferedEvidence): void {
    if (buffered.length >= maxBufferedEvents) {
      buffered.shift();
      droppedEvidenceCount += 1;
    }
    buffered.push(item);
  }

  return {
    append(event) {
      if (event.kind === 'action' && ACTION_MAP.has(event.action_type) && allowedPage(event.url, allowedOrigins)) {
        add({ kind: 'action', event, sequence: reserveSequence() });
        return;
      }
      if (event.kind === 'navigation' && allowedPage(event.url, allowedOrigins)) {
        add({ kind: 'navigation', event, sequence: reserveSequence() });
        return;
      }
      if (event.kind === 'dom_mutation_summary' && allowedPage(event.url, allowedOrigins)) {
        add({ kind: 'mutation', event, sequence: reserveSequence() });
        return;
      }
      if (event.kind === 'network_request') {
        const requestUrl = safeUrl(event.full_url);
        if (!requestUrl || !allowedOrigins.has(requestUrl.origin) || !METHOD.test(event.method)) {
          droppedEvidenceCount += 1;
          return;
        }
        pendingRequests.set(event.request_id, { event, sequence: reserveSequence() });
        return;
      }
      if (event.kind === 'network_response') {
        const pending = pendingRequests.get(event.request_id);
        if (!pending) {
          droppedEvidenceCount += 1;
          return;
        }
        pendingRequests.delete(event.request_id);
        add({
          kind: 'exchange',
          request: pending.event,
          response: event,
          sequence: pending.sequence,
        });
      }
    },

    async flush(recordingId) {
      const current = buffered.sort((left, right) => left.sequence - right.sequence);
      buffered = [];
      if (current.length === 0) return null;

      const events: CommandCenterEvidenceBatch['events'] = [];
      const pageMutations: CommandCenterPageMutation[] = [];
      let fingerprintedValueCount = 0;
      let redactedFieldCount = 0;

      for (const item of current) {
        const sourceEvent = item.kind === 'exchange' ? item.request : item.event;
        const origin = safeUrl(
          item.kind === 'exchange' ? item.request.full_url : sourceEvent.url,
        )?.origin;
        const identity = origin ? options.originSystemCodes?.[origin] : undefined;
        const metadata = {
          ...(identity ? { system_code: identity } : {}),
          tab_id: sourceEvent.tab_id,
        };
        if (item.kind === 'action') {
          const converted = await convertAction(item.event, item.sequence, options.fingerprintKey);
          if (converted) {
            events.push({ ...converted.event, ...metadata });
            fingerprintedValueCount += converted.fingerprinted;
            redactedFieldCount += converted.redacted;
          }
        } else if (item.kind === 'navigation') {
          const page = await pageDescriptor(item.event.url, options.fingerprintKey);
          if (page) {
            events.push({
              ...metadata,
              event_id: randomUuid(),
              client_sequence: item.sequence,
              occurred_at: isoTime(item.event.timestamp),
              event_type: 'navigation',
              page,
            });
          }
        } else if (item.kind === 'mutation') {
          const mutation = await convertMutation(item.event, item.sequence, options.fingerprintKey);
          if (mutation) pageMutations.push({ ...mutation, ...metadata });
        } else {
          const exchange = await convertExchange(
            item.request,
            item.response,
            item.sequence,
            options.fingerprintKey,
          );
          if (exchange) {
            events.push({ ...exchange.event, ...metadata });
            fingerprintedValueCount += exchange.fingerprinted;
            redactedFieldCount += exchange.redacted;
          }
        }
      }

      events.sort((left, right) => left.client_sequence - right.client_sequence);
      pageMutations.sort((left, right) => left.client_sequence - right.client_sequence);
      if (events.length === 0 && pageMutations.length === 0) return null;

      return {
        batch_id: randomUuid(),
        recording_id: recordingId,
        events,
        page_mutations: pageMutations,
        redaction_summary: {
          redacted_field_count: redactedFieldCount,
          fingerprinted_value_count: fingerprintedValueCount,
          dropped_evidence_count: droppedEvidenceCount,
        },
      };
    },
  };
}

async function convertAction(event: ActionEvent, sequence: number, key: string) {
  const eventType = ACTION_MAP.get(event.action_type);
  const page = await pageDescriptor(event.url, key);
  if (!eventType || !page) return null;
  const control = event.target ? await controlDescriptor(event.target, key) : undefined;
  const rawValue = usableValue(event.value);
  const valueFingerprint = rawValue ? await fingerprint(rawValue, key) : undefined;
  return {
    event: {
      event_id: randomUuid(),
      client_sequence: sequence,
      occurred_at: isoTime(event.timestamp),
      event_type: eventType,
      page,
      ...(control ? { control } : {}),
      ...(valueFingerprint ? { value_fingerprint: valueFingerprint } : {}),
    } satisfies CommandCenterBrowserEvent,
    fingerprinted: 1 + (control ? 1 : 0) + (valueFingerprint ? 1 : 0),
    redacted: event.value ? 1 : 0,
  };
}

async function convertMutation(event: DomMutationSummaryEvent, sequence: number, key: string) {
  const page = await pageDescriptor(event.url, key);
  if (!page) return null;
  const fingerprints = await Promise.all(
    event.selectors.slice(0, 64).map((selector) => fingerprint(selector, key)),
  );
  return {
    mutation_id: randomUuid(),
    client_sequence: sequence,
    occurred_at: isoTime(event.timestamp),
    page,
    mutation_type: event.signals.some((signal) => signal.startsWith('form_control_'))
      ? 'form_state_change'
      : 'dom_change',
    changed_control_fingerprints: fingerprints,
  } satisfies CommandCenterPageMutation;
}

async function convertExchange(
  request: NetworkRequestEvent,
  response: NetworkResponseEvent,
  sequence: number,
  key: string,
) {
  const url = safeUrl(request.full_url);
  if (!url || !METHOD.test(request.method)) return null;
  const requestMaterial = usableValue(request.req_body);
  const responseMaterial = usableValue(response.res_body);
  const requestFingerprint = requestMaterial ? await fingerprint(requestMaterial, key) : undefined;
  const responseFingerprint = responseMaterial ? await fingerprint(responseMaterial, key) : undefined;
  const queryParameterNames = identifierList([...url.searchParams.keys()]);
  const queryParameterFingerprints: Record<string, string[]> = {};
  let queryFingerprintCount = 0;
  for (const name of queryParameterNames) {
    const values = url.searchParams.getAll(name).filter(Boolean);
    if (values.length === 0) continue;
    queryParameterFingerprints[name] = await Promise.all(
      values.map((value) => fingerprint(value, key)),
    );
    queryFingerprintCount += values.length;
  }
  const bodyFieldFingerprints = requestMaterial
    ? await fingerprintBodyFields(requestMaterial, key)
    : {};
  return {
    event: {
      exchange_id: randomUuid(),
      client_sequence: sequence,
      started_at: isoTime(request.timestamp),
      completed_at: isoTime(Math.max(request.timestamp, response.timestamp)),
      method: request.method,
      path_template: url.pathname || '/',
      query_parameter_names: queryParameterNames,
      query_parameter_fingerprints: queryParameterFingerprints,
      ...(Object.keys(bodyFieldFingerprints).length > 0
        ? { body_field_fingerprints: bodyFieldFingerprints }
        : {}),
      ...(requestFingerprint ? { request_fingerprint: requestFingerprint } : {}),
      response_status: Number.isInteger(response.status) ? response.status! : 0,
      ...(responseFingerprint ? { response_fingerprint: responseFingerprint } : {}),
      endpoint_fingerprint: await fingerprint(`${request.method} ${url.pathname || '/'}`, key),
    } satisfies CommandCenterNetworkExchange,
    fingerprinted:
      1 +
      queryFingerprintCount +
      Object.values(bodyFieldFingerprints).reduce((total, values) => total + values.length, 0) +
      (requestFingerprint ? 1 : 0) +
      (responseFingerprint ? 1 : 0),
    redacted: (request.req_body ? 1 : 0) + (response.res_body ? 1 : 0) + Object.keys(request.req_headers).length,
  };
}

async function fingerprintBodyFields(
  body: string,
  key: string,
): Promise<Record<string, string[]>> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = Object.fromEntries(new URLSearchParams(body));
  }
  const fields = flattenScalarFields(parsed).slice(0, 256);
  const result: Record<string, string[]> = {};
  for (const [path, value] of fields) {
    if (!path || !value) continue;
    (result[path] ??= []).push(await fingerprint(value, key));
  }
  return result;
}

function flattenScalarFields(value: unknown, path = ''): Array<[string, string]> {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      flattenScalarFields(item, path ? `${path}.${index}` : String(index)),
    );
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).flatMap(([name, item]) =>
      flattenScalarFields(item, path ? `${path}.${name}` : name),
    );
  }
  if (!['string', 'number', 'boolean'].includes(typeof value)) return [];
  return [[path, String(value)]];
}

async function pageDescriptor(url: string, key: string): Promise<CommandCenterPageDescriptor | null> {
  const parsed = safeUrl(url);
  if (!parsed || !['http:', 'https:'].includes(parsed.protocol)) return null;
  return {
    origin: parsed.origin,
    path: parsed.pathname || '/',
    query_parameter_names: identifierList([...parsed.searchParams.keys()]),
    fingerprint: await fingerprint(`${parsed.origin}${parsed.pathname || '/'}`, key),
  };
}

async function controlDescriptor(target: ElementRef, key: string) {
  const role = safeIdentifier(target.role || target.tag);
  const inputType = safeIdentifier(target.inputType);
  const accessibleName = safeSemanticText(target.name || target.text);
  return {
    ...(role ? { role } : {}),
    ...(accessibleName ? { accessible_name: accessibleName } : {}),
    ...(inputType ? { input_type: inputType } : {}),
    selector_fingerprint: await fingerprint(target.selector, key),
  };
}

async function fingerprint(value: string, key: string): Promise<string> {
  const encoder = new TextEncoder();
  const importedKey = await crypto.subtle.importKey(
    'raw',
    encoder.encode(key),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const digest = await crypto.subtle.sign('HMAC', importedKey, encoder.encode(value));
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `hmac-sha256:${hex}`;
}

function usableValue(value: RedactedValue | undefined): string | null {
  return typeof value?.value === 'string' && value.value ? value.value : value?.redaction?.digest ?? null;
}

function identifierList(values: string[]): string[] {
  return [...new Set(values.filter((value) => IDENTIFIER.test(value)).slice(0, 128))].sort();
}

function safeIdentifier(value: string | undefined): string | null {
  const candidate = value?.trim().slice(0, 128);
  return candidate && IDENTIFIER.test(candidate) ? candidate : null;
}

function safeSemanticText(value: string | undefined): string | null {
  const candidate = value?.replace(/[\x00-\x1f\x7f]/g, ' ').trim().slice(0, 256);
  return candidate && !SENSITIVE_TEXT.test(candidate) ? candidate : null;
}

function allowedPage(url: string, origins: Set<string>): boolean {
  const parsed = safeUrl(url);
  return Boolean(parsed && origins.has(parsed.origin));
}

function exactOrigin(value: string): string | null {
  const parsed = safeUrl(value);
  return parsed && parsed.origin === value && ['http:', 'https:'].includes(parsed.protocol)
    ? parsed.origin
    : null;
}

function safeUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isoTime(timestamp: number): string {
  return new Date(Number.isFinite(timestamp) ? timestamp : Date.now()).toISOString();
}

function randomUuid(): string {
  return crypto.randomUUID();
}

function isString(value: string | null): value is string {
  return value !== null;
}
