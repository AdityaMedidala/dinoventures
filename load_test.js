import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m',  target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<750'],
  },
};

const BASE = 'https://dinoventures-production.up.railway.app';

export default function () {
  const txType = Math.random() > 0.5 ? 'TOPUP' : 'SPEND';

  const res = http.post(`${BASE}/transact`, JSON.stringify({
    user_id: 'user_123',
    amount: 1,
    transaction_type: txType,
    asset_code: 'GOLD_COIN',
  }), {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': uuidv4(),
    },
  });

  check(res, {
    'status 200 or 400': (r) => r.status === 200 || r.status === 400,
    'no 500s': (r) => r.status !== 500,
  });

  sleep(0.1);
}