import { describe, expect, it } from 'vitest';
import { createEvidenceConverter } from '@/command-center/evidence';
import type { CapturedEvent } from '@/shared/types';

const recordingId = '123e4567-e89b-42d3-a456-426614174000';
const pageUrl = 'http://yifeng.dtsum.com/purchase/apply?pageNo=1';

function base(kind: CapturedEvent['kind'], timestamp: number) {
  return {
    event_id: `ev_${timestamp}`,
    trace_id: 'tr_test',
    tab_id: 7,
    timestamp,
    url: pageUrl,
    kind,
  };
}

describe('CommandCenter evidence converter', () => {
  it('annotates evidence from two tabs with configured system identity', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://yifeng.dtsum.com', 'http://127.0.0.1:8101'],
      originSystemCodes: {
        'http://yifeng.dtsum.com': 'yifeng_mes',
        'http://127.0.0.1:8101': 'connected_system',
      },
      fingerprintKey: 'local-recording-key',
    });
    converter.append({
      ...base('action', 1_000), kind: 'action', action_type: 'click',
      target: { tag: 'button', selector: '#query', xpath: '//*[@id="query"]' },
    });
    converter.append({
      ...base('action', 1_010), tab_id: 9,
      url: 'http://127.0.0.1:8101/', kind: 'action', action_type: 'submit',
      target: { tag: 'form', selector: '#follow-up', xpath: '//*[@id="follow-up"]' },
    });

    const batch = await converter.flush(recordingId);

    expect(batch?.events).toMatchObject([
      { system_code: 'yifeng_mes', tab_id: 7 },
      { system_code: 'connected_system', tab_id: 9 },
    ]);
  });
  it('aligns UI values with repeated query values without exposing raw text', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://yifeng.dtsum.com'],
      fingerprintKey: 'local-recording-key',
    });

    converter.append({
      ...base('action', 1_000),
      kind: 'action',
      action_type: 'input',
      target: {
        tag: 'input',
        role: 'input',
        name: '申请人',
        selector: '#apply-by',
        xpath: '//*[@id="apply-by"]',
      },
      value: { value: 'alice' },
    });
    converter.append({
      ...base('network_request', 1_010),
      kind: 'network_request',
      request_id: 'req-query-values',
      method: 'GET',
      full_url:
        'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list?applyBy=alice&tag=a&tag=b&empty=',
      fetch_kind: 'xhr',
      req_headers: {},
    });
    converter.append({
      ...base('network_response', 1_020),
      kind: 'network_response',
      request_id: 'req-query-values',
      status: 200,
    });

    const batch = await converter.flush(recordingId);
    const input = batch?.events.find((event) => 'event_type' in event);
    const exchange = batch?.events.find((event) => 'method' in event);

    expect(exchange).toMatchObject({
      query_parameter_names: ['applyBy', 'empty', 'tag'],
      query_parameter_fingerprints: {
        applyBy: [expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/)],
        tag: [
          expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/),
          expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/),
        ],
      },
    });
    expect(exchange?.query_parameter_fingerprints.empty).toBeUndefined();
    const applyByFingerprints = exchange?.query_parameter_fingerprints.applyBy;
    const tagFingerprints = exchange?.query_parameter_fingerprints.tag;
    expect(applyByFingerprints).toHaveLength(1);
    expect(tagFingerprints).toHaveLength(2);
    expect(input?.value_fingerprint).toBe(
      applyByFingerprints?.[0],
    );
    expect(tagFingerprints?.[0]).not.toBe(tagFingerprints?.[1]);
    expect(JSON.stringify(batch)).not.toContain('alice');
  });

  it('aligns UI values with nested JSON body fields without exposing raw values', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://127.0.0.1:8101'],
      fingerprintKey: 'local-recording-key',
    });
    converter.append({
      ...base('action', 1_000),
      url: 'http://127.0.0.1:8101/',
      kind: 'action',
      action_type: 'input',
      target: {
        tag: 'input', role: 'input', name: '物料编码',
        selector: '[data-field="material_code"]', xpath: '//*[@data-field="material_code"]',
      },
      value: { value: 'LCF4607A' },
    });
    converter.append({
      ...base('network_request', 1_010),
      url: 'http://127.0.0.1:8101/',
      kind: 'network_request', request_id: 'req-json-body', method: 'POST',
      full_url: 'http://127.0.0.1:8101/api/purchase-follow-ups',
      fetch_kind: 'fetch', req_headers: {},
      req_body: {
        value: JSON.stringify({
          title: '采购申请跟进',
          items: [{ material_code: 'LCF4607A', quantity: 600 }],
        }),
      },
    });
    converter.append({
      ...base('network_response', 1_020),
      url: 'http://127.0.0.1:8101/',
      kind: 'network_response', request_id: 'req-json-body', status: 201,
    });

    const batch = await converter.flush(recordingId);
    const input = batch?.events.find((event) => 'event_type' in event);
    const exchange = batch?.events.find((event) => 'method' in event);

    expect(exchange).toMatchObject({
      body_field_fingerprints: {
        '/title': [expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/)],
        '/items/0/material_code': [expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/)],
        '/items/0/quantity': [expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/)],
      },
    });
    expect(input?.value_fingerprint).toBe(
      exchange && 'body_field_fingerprints' in exchange
        ? exchange.body_field_fingerprints?.['/items/0/material_code']?.[0]
        : undefined,
    );
    expect(JSON.stringify(batch)).not.toContain('LCF4607A');
    expect(JSON.stringify(batch)).not.toContain('采购申请跟进');
  });

  it('orders a page action and its completed API exchange without raw values', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://yifeng.dtsum.com'],
      fingerprintKey: 'local-recording-key',
    });

    converter.append({
      ...base('action', 1_000),
      kind: 'action',
      action_type: 'click',
      target: {
        tag: 'button',
        role: 'button',
        name: '查询',
        selector: '#query',
        xpath: '//*[@id="query"]',
      },
    });
    converter.append({
      ...base('network_request', 1_010),
      kind: 'network_request',
      request_id: 'req-1',
      method: 'GET',
      full_url:
        'http://yifeng.dtsum.com/jeecg-boot/purchase/apply/list?pageNo=1',
      fetch_kind: 'fetch',
      req_headers: {
        'X-Access-Token': { value: 'private-token' },
      },
      req_body: { value: '{"user":"admin"}' },
    });
    converter.append({
      ...base('network_response', 1_030),
      kind: 'network_response',
      request_id: 'req-1',
      status: 200,
      duration_ms: 20,
    });

    const batch = await converter.flush(recordingId);

    expect(batch?.events.map((event) => event.client_sequence)).toEqual([1, 2]);
    expect(batch?.events[0]).toMatchObject({ event_type: 'click' });
    expect(batch?.events[1]).toMatchObject({
      method: 'GET',
      path_template: '/jeecg-boot/purchase/apply/list',
      query_parameter_names: ['pageNo'],
      response_status: 200,
    });
    expect(JSON.stringify(batch)).not.toContain('admin');
    expect(JSON.stringify(batch)).not.toContain('private-token');
    expect(JSON.stringify(batch)).not.toContain('X-Access-Token');
  });

  it('ignores incomplete, foreign, and unsupported network evidence', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://yifeng.dtsum.com'],
      fingerprintKey: 'local-recording-key',
    });
    converter.append({
      ...base('network_response', 1_000),
      kind: 'network_response',
      request_id: 'missing-request',
      status: 200,
    });
    converter.append({
      ...base('network_request', 1_010),
      kind: 'network_request',
      request_id: 'foreign',
      method: 'GET',
      full_url: 'https://other.example/private',
      fetch_kind: 'xhr',
      req_headers: {},
    });
    converter.append({
      ...base('network_response', 1_020),
      kind: 'network_response',
      request_id: 'foreign',
      status: 200,
    });
    converter.append({
      ...base('network_stream', 1_030),
      kind: 'network_stream',
      stream_type: 'websocket',
      phase: 'message',
      stream_id: 'ws-1',
      full_url: 'ws://yifeng.dtsum.com/events',
    });

    expect(await converter.flush(recordingId)).toBeNull();
  });

  it('maps navigation and relevant DOM mutation evidence', async () => {
    const converter = createEvidenceConverter({
      allowedOrigins: ['http://yifeng.dtsum.com'],
      fingerprintKey: 'local-recording-key',
    });
    converter.append({
      ...base('navigation', 1_000),
      kind: 'navigation',
      nav_type: 'pushState',
      to_url: 'http://yifeng.dtsum.com/purchase/apply',
    });
    converter.append({
      ...base('dom_mutation_summary', 1_010),
      kind: 'dom_mutation_summary',
      added_nodes: 1,
      removed_nodes: 0,
      attribute_changes: 1,
      signals: ['status_added'],
      selectors: ['#result'],
      text_samples: { value: null },
    });

    const batch = await converter.flush(recordingId);
    expect(batch?.events[0]).toMatchObject({ event_type: 'navigation' });
    expect(batch?.page_mutations[0]).toMatchObject({ mutation_type: 'dom_change' });
    expect(batch?.events[0]?.client_sequence).toBeLessThan(
      batch?.page_mutations[0]?.client_sequence ?? 0,
    );
  });
});
