import assert from 'node:assert/strict';
import test from 'node:test';
import { joinApiUrl, readEventStream, unwrapResult } from '../src/lib/http.js';

test('unwrapResult returns data for successful payloads', () => {
  assert.deepEqual(unwrapResult({ success: true, data: { id: 1, name: '店铺' } }), { id: 1, name: '店铺' });
});

test('unwrapResult throws with server error messages', () => {
  assert.throws(() => unwrapResult({ success: false, errorMsg: 'boom' }), /boom/);
});

test('joinApiUrl normalizes path segments', () => {
  assert.equal(joinApiUrl('/shop/', '/of/type'), '/shop/of/type');
  assert.equal(joinApiUrl('shop', 'of/name'), '/shop/of/name');
});

test('readEventStream 解析 SSE event 和 JSON envelope', async () => {
  const encoder = new TextEncoder();
  const seen = [];
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('event: ack\n'));
      controller.enqueue(encoder.encode('data: {"traceId":"trace-1","payload":{"message":"ok"}}\n\n'));
      controller.enqueue(encoder.encode('event: final\n'));
      controller.enqueue(encoder.encode('data: {"payload":{"answer_text":"最终答案","source":"learning-agent-service"}}\n\n'));
      controller.close();
    },
  });

  await readEventStream(stream, (event) => {
    seen.push(event);
  });

  assert.deepEqual(seen, [
    {
      type: 'ack',
      data: {
        traceId: 'trace-1',
        payload: {
          message: 'ok',
        },
      },
    },
    {
      type: 'final',
      data: {
        payload: {
          answer_text: '最终答案',
          source: 'learning-agent-service',
        },
      },
    },
  ]);
});
