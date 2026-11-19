const { execSync } = require('child_process');
const path = require('path');

exports.handler = async function(event, context) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method Not Allowed' };
  }

  const secret = process.env.WEBHOOK_SECRET;
  if (secret) {
    const crypto = require('crypto');
    const signature = event.headers['x-webhook-signature'] || event.headers['X-Webhook-Signature'];
    const expected = crypto.createHmac('sha256', secret)
      .update(event.body || '')
      .digest('hex');
    if (signature !== expected) {
      return { statusCode: 401, body: 'Invalid signature' };
    }
  }

  try {
    const fs = require('fs');
    const tmpDir = '/tmp';
    const orderFile = path.join(tmpDir, `order_${Date.now()}.json`);
    fs.writeFileSync(orderFile, event.body);

    const pythonPath = 'python3';
    const scriptPath = path.join(__dirname, '../../automation/webhook_handler.py');
    
    const result = execSync(`${pythonPath} ${scriptPath} ${orderFile}`, {
      encoding: 'utf-8',
      timeout: 60000,
      env: { ...process.env, PATH: process.env.PATH }
    });

    fs.unlinkSync(orderFile);

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: result
    };
  } catch (error) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: error.message, stdout: error.stdout, stderr: error.stderr })
    };
  }
};
